"""Team and governance commands: policy, audit, impact, check, sync, stats."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.table import Table

from agent_forge.cli._app import app
from agent_forge.cli._common import (
    JsonOpt,
    WorkspaceOpt,
    _audit,
    _policies,
    _registry,
    _run,
    _store,
    _ws,
    console,
    err_console,
)
from agent_forge.cli._envelope import _print_json
from agent_forge.cli._tables import _print_plan_summary
from agent_forge.cli.plans import _approve_plan
from agent_forge.errors import PlanError, ValidationFailed
from agent_forge.models.capability import Platform


@app.command()
def policy(
    path: Annotated[
        Path | None,
        typer.Argument(help="Target project (adds its .agent-forge/policy.yaml layer)."),
    ] = None,
    workspace: WorkspaceOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Show the effective policy layers (default -> workspace -> project) and per-capability verdicts."""

    def body() -> None:
        from agent_forge.policy.engine import describe
        from agent_forge.registry.context_load import context_chars

        ws = _ws(workspace)
        reg = _registry(ws)
        ps = _policies(ws, path.resolve() if path else None)
        verdicts = {}
        for cap in reg.capabilities():
            for plat in cap.platforms:
                d, why = ps.evaluate(cap, plat, context_chars(reg.get(cap.id), plat))
                verdicts.setdefault(cap.id, {})[plat.value] = {
                    "decision": d.value,
                    "required": ps.is_required(cap.id),
                    "reasons": why,
                }
        required = sorted(cid for cid in verdicts if ps.is_required(cid))
        if as_json:
            _print_json({"layers": describe(ps), "required": required, "verdicts": verdicts})
            return
        console.print("layers: " + " -> ".join(ps.names))
        if required:
            console.print("required by policy: " + ", ".join(required))
        t = Table(title="policy verdicts")
        for col in ("capability", "platform", "decision", "reasons"):
            t.add_column(col, overflow="fold")
        for cid, per in verdicts.items():
            for plat, v in per.items():
                color = {"allow": "green", "require_request": "yellow", "deny": "red"}[
                    v["decision"]
                ]
                label = f"[{color}]{v['decision']}[/]" + (
                    " [bold](required)[/]" if v["required"] else ""
                )
                t.add_row(cid, plat, label, "\n".join(v["reasons"]) or "-")
        console.print(t)

    _run(body)


@app.command()
def audit(
    workspace: WorkspaceOpt = None,
    event: Annotated[str | None, typer.Option("--event", help="Filter by event name.")] = None,
    limit: Annotated[int, typer.Option("--limit")] = 50,
    as_json: JsonOpt = False,
) -> None:
    """Show the append-only audit log (plans created/approved, transactions, rollbacks)."""

    def body() -> None:
        store = _store(_ws(workspace))
        rows = store.audit.read(limit=limit, event=event)
        if as_json:
            _print_json(rows)
            return
        t = Table(title=f"audit ({len(rows)})")
        for col in ("at", "event", "details"):
            t.add_column(col, overflow="fold")
        for r in rows:
            details = ", ".join(f"{k}={v}" for k, v in r.items() if k not in ("at", "event"))
            t.add_row(r["at"], r["event"], details)
        console.print(t)

    _run(body)


@app.command()
def impact(
    capability_id: Annotated[str, typer.Argument(help="Capability id, e.g. ecc.tdd-workflow.")],
    workspace: WorkspaceOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Where is a capability installed? Checks every project this workspace has written to
    (read-only), so a deprecated or revoked entry can be traced before it is removed."""

    def body() -> None:
        from agent_forge.scanner.agent_detection import MANAGED_MANIFEST, parse_managed_manifest

        ws = _ws(workspace)
        reg = _registry(ws)
        store = _store(ws)
        cap = reg.items.get(capability_id)
        targets = sorted({row["target"] for row in store.list_transactions(limit=100_000)})
        rows: list[dict[str, Any]] = []
        for target in targets:
            manifest = Path(target) / MANAGED_MANIFEST
            if not manifest.is_file() or manifest.is_symlink():
                continue
            records, _ = parse_managed_manifest(manifest.read_text(encoding="utf-8"))
            for rec in records:
                if rec.capability_id == capability_id:
                    rows.append(
                        {
                            "target": target,
                            "installed": rec.version,
                            "transaction": rec.transaction_id,
                            "outdated": cap is not None and cap.capability.version != rec.version,
                        }
                    )
        result = {
            "capability_id": capability_id,
            "registry_version": cap.capability.version if cap else None,
            "registry_status": cap.capability.status.value if cap else "missing",
            "replaced_by": cap.capability.replaced_by if cap else None,
            "projects_checked": len(targets),
            "installations": rows,
        }
        if as_json:
            _print_json(result)
            return
        console.print(
            f"{capability_id}: registry {result['registry_version'] or '-'} "
            f"({result['registry_status']}), installed in {len(rows)} of "
            f"{len(targets)} project(s) this workspace has written to"
        )
        for r in rows:
            console.print(
                f"  {r['target']}  {r['installed']}"
                + ("  [yellow]outdated[/]" if r["outdated"] else "")
            )

    _run(body)


@app.command()
def check(
    path: Annotated[Path, typer.Argument(help="Target project directory.")],
    workspace: WorkspaceOpt = None,
    as_json: JsonOpt = False,
) -> int:
    """CI gate (read-only): one exit code for drift, revoked or missing capabilities, an
    invalid managed.json, unfinished transactions, config syntax, a missing policy-required
    capability, and decision records whose SKIPs no longer verify or whose applied plans lost
    their record. 0 = clean, 12 = problems."""

    def body() -> int:
        from agent_forge.decisions.gate import decision_gate
        from agent_forge.planner.maintenance import drift_report
        from agent_forge.scanner.project_profile import scan_project
        from agent_forge.validation.engine import validate_target

        ws = _ws(workspace)
        reg = _registry(ws)
        store = _store(ws)
        profile = scan_project(path, limits=ws.scan_limits)
        failures: list[str] = []
        warnings: list[str] = []
        if profile.managed_manifest_valid is False:
            failures.append(".agent-forge/managed.json is present but invalid")
        drift = drift_report(profile)
        for item in drift.drifted:
            failures.append(f"drift: {item.capability_id} {item.path} ({item.state})")
        rep = validate_target(ws, reg, store, profile)
        seen = set(failures)
        for f in rep.findings:
            if f.scope == "managed" and (
                "modified locally" in f.message or "no longer present" in f.message
            ):
                continue  # already reported as drift above
            line = f"{f.scope}: {f.message}"
            if f.level == "error" and line not in seen:
                failures.append(line)
            elif f.level == "warning":
                warnings.append(line)
        outdated = [
            f"{m.capability_id}: installed {m.version}, registry {reg.items[m.capability_id].capability.version}"
            for m in profile.managed
            if m.capability_id in reg.items
            and reg.items[m.capability_id].capability.version != m.version
        ]
        policies = _policies(ws, Path(profile.canonical_path))
        required_missing = _required_missing(reg, profile, policies)
        for cid, why in required_missing:
            failures.append(f"policy: {cid} is required but {why}")
        gate = decision_gate(reg, profile, store, policy=policies)
        failures.extend(gate.failures)
        warnings.extend(gate.warnings)
        ok = not failures
        result = {
            "target": profile.canonical_path,
            "ok": ok,
            "managed": [m.capability_id for m in profile.managed],
            "failures": failures,
            "warnings": warnings,
            "outdated": outdated,
            "drifted": len(drift.drifted),
            "required_missing": [cid for cid, _ in required_missing],
            "decisions": gate.to_dict(),
        }
        if as_json:
            _print_json(result)
        else:
            for f in failures:
                console.print(f"[red]fail   [/] {f}")
            for w in warnings:
                console.print(f"[yellow]warning[/] {w}")
            for o in outdated:
                console.print(f"[dim]outdated[/] {o}")
            console.print(
                f"{len(profile.managed)} managed capabilit{'y' if len(profile.managed) == 1 else 'ies'}, "
                f"{len(failures)} failure(s), {len(warnings)} warning(s): "
                + ("[green]OK[/]" if ok else "[red]FAILED[/]")
            )
            if not ok:
                console.print(
                    "fix: [bold]agent-forge sync PATH[/] restores managed files; "
                    "[bold]repair --strategy unmanage[/] keeps local edits"
                    + (
                        "; [bold]forge PATH --request <id>[/] installs a required capability"
                        if required_missing
                        else ""
                    )
                )
        return 0 if ok else ValidationFailed.exit_code

    _run(body)
    return 0


@app.command()
def sync(
    path: Annotated[
        Path | None, typer.Argument(help="Project directory (default: current).")
    ] = None,
    workspace: WorkspaceOpt = None,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Restore without asking (CI / fresh clone).")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Report what would be restored; write nothing.")
    ] = False,
    as_json: JsonOpt = False,
) -> int:
    """Bring a freshly cloned project in line with its committed .agent-forge/managed.json:
    restore managed files that are missing or modified, at the versions the repo pinned.
    Nothing new is chosen; that is `forge` / `/agent-forge-upgrade`."""

    def body() -> int:
        from agent_forge.apply.engine import apply_plan
        from agent_forge.planner.maintenance import build_repair_plan, drift_report
        from agent_forge.scanner.project_profile import scan_project

        ws = _ws(workspace)
        reg = _registry(ws)
        store = _store(ws)
        target = (path or Path.cwd()).resolve()
        profile = scan_project(target, limits=ws.scan_limits)
        out = err_console if as_json else console
        result: dict[str, Any] = {"target": profile.canonical_path, "status": "in_sync"}
        if profile.managed_manifest_valid is False:
            raise PlanError(
                ".agent-forge/managed.json is invalid; nothing restored",
                hint="Restore it from git, or `agent-forge status` to inspect.",
            )
        if profile.managed_manifest_valid is None:
            result["status"] = "nothing_managed"
            if as_json:
                _print_json(result)
            else:
                out.print("no .agent-forge/managed.json: nothing to sync (use `forge` to install)")
            return 0
        missing_versions = [
            f"{m.capability_id} {m.version}"
            for m in profile.managed
            if m.capability_id not in reg.items
            or reg.items[m.capability_id].capability.version != m.version
        ]
        drift = drift_report(profile)
        result["drifted"] = [
            {"capability": i.capability_id, "path": i.path, "state": i.state} for i in drift.drifted
        ]
        if not drift.drifted:
            if as_json:
                _print_json(result)
            else:
                out.print(
                    f"[green]in sync[/]: {len(profile.managed)} managed capabilit"
                    f"{'y' if len(profile.managed) == 1 else 'ies'}, no drift"
                )
            return 0
        blocked = sorted(
            {i.capability_id for i in drift.drifted} & {m.split()[0] for m in missing_versions}
        )
        if blocked:
            raise PlanError(
                "cannot restore "
                + ", ".join(blocked)
                + ": the pinned version is not in this workspace's registry",
                hint="Re-run the installer (or `agent-forge init --refresh-registry`) so the "
                "registry contains the versions the project pinned, or `upgrade` the project.",
            )
        plan = build_repair_plan(reg, profile, "restore", None)
        store.save_plan(plan)
        _audit(
            store,
            "PlanCreated",
            plan_id=plan.plan_id,
            kind=plan.kind,
            target=plan.target.canonical_path,
            registry_digest=plan.registry_digest,
            operations=len(plan.operations),
        )
        result["plan_id"] = plan.plan_id
        if not as_json:
            _print_plan_summary(plan)
        if dry_run:
            result["status"] = "planned"
            if as_json:
                _print_json(result)
            else:
                out.print("[yellow]dry run:[/] nothing written")
            return 0
        if not yes:
            if not sys.stdin.isatty():
                raise PlanError(
                    "interactive confirmation required (no TTY)", hint="Re-run with --yes."
                )
            if not typer.confirm(
                f"Restore {len(plan.operations)} managed file(s) to the committed state?",
                default=False,
            ):
                result["status"] = "declined"
                out.print(f"[yellow]declined[/]; plan {plan.plan_id} kept as draft")
                return 0
        # The content being restored is exactly what managed.json already records (reviewed
        # and committed with the project), so every approval class is granted here.
        _approve_plan(
            store, reg, plan, shared_files=True, hooks=True, mcp=True, by="agent-forge sync"
        )
        tx = apply_plan(ws, store, reg, plan, confirm=None)
        _audit(
            store,
            "TransactionCompleted",
            transaction_id=tx.transaction_id,
            plan_id=plan.plan_id,
            target=tx.target_canonical_path,
            status=tx.status.value,
            capabilities=sorted(tx.capabilities),
        )
        result["status"] = "restored"
        result["transaction_id"] = tx.transaction_id
        if as_json:
            _print_json(result)
        else:
            out.print(
                f"[green]restored[/] {len([o for o in tx.operations if o.applied])} file(s); "
                f"transaction {tx.transaction_id}"
            )
        return 0

    _run(body)
    return 0


@app.command()
def stats(
    workspace: WorkspaceOpt = None,
    since: Annotated[
        int | None, typer.Option("--since", help="Only the last N days.", min=1)
    ] = None,
    as_json: JsonOpt = False,
) -> None:
    """Local usage statistics from the audit log: installs, rollbacks and projects per
    capability. Read-only; nothing is sent anywhere."""

    def body() -> None:
        from agent_forge.storage.audit import AuditLog
        from agent_forge.storage.stats import usage_stats

        ws = _ws(workspace)
        data = usage_stats(AuditLog(ws.audit_path), since_days=since)
        if as_json:
            _print_json(data)
            return
        console.print(
            f"{data['records']} audit record(s)"
            + (f" in the last {since} day(s)" if since else "")
            + f"; {data['projects']} project(s); {data['transactions_failed']} failed transaction(s)"
        )
        if data["by_capability"]:
            t = Table(title="capabilities")
            for col in ("capability", "installs", "rollbacks"):
                t.add_column(col)
            for row in data["by_capability"]:
                t.add_row(row["capability"], str(row["installs"]), str(row["rollbacks"]))
            console.print(t)
        if data["by_project"]:
            t = Table(title="projects")
            t.add_column("target", overflow="fold")
            t.add_column("transactions")
            for row in data["by_project"]:
                t.add_row(row["target"], str(row["transactions"]))
            console.print(t)
        if data["events"]:
            console.print("events: " + ", ".join(f"{k} {v}" for k, v in data["events"].items()))

    _run(body)


def _required_missing(reg, profile, policies) -> list[tuple[str, str]]:
    """Required capability ids that are not installed, with the reason it counts as missing."""
    from agent_forge.policy.engine import Decision as PolicyDecision
    from agent_forge.registry.context_load import context_chars

    installed = {m.capability_id for m in profile.managed}
    platforms = [p.platform for p in profile.platforms] or [Platform.CLAUDE_CODE]
    out: list[tuple[str, str]] = []
    for cid in sorted(reg.items):
        if not policies.is_required(cid) or cid in installed:
            continue
        cap = reg.items[cid].capability
        usable = [pl for pl in platforms if pl in cap.platforms]
        if not usable:
            out.append((cid, "not available for the detected platforms"))
            continue
        verdicts = {
            pl: policies.evaluate(cap, pl, context_chars(reg.items[cid], pl))[0] for pl in usable
        }
        if all(v == PolicyDecision.DENY for v in verdicts.values()):
            out.append((cid, "also denied by policy (fix the policy)"))
        else:
            out.append((cid, "not installed"))
    return out
