"""Read-only project commands: scan, drift, status; and rollback."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.panel import Panel
from rich.table import Table

from agent_forge.cli._app import app
from agent_forge.cli._common import (
    JsonOpt,
    WorkspaceOpt,
    _audit,
    _registry,
    _run,
    _store,
    _ws,
    console,
)
from agent_forge.cli._envelope import _print_json
from agent_forge.cli._tables import _print_profile
from agent_forge.errors import PlanError, UsageError
from agent_forge.util import write_json


@app.command()
def scan(
    path: Annotated[Path, typer.Argument(help="Target project directory (read-only).")],
    workspace: WorkspaceOpt = None,
    report: Annotated[
        Path | None,
        typer.Option(
            "--report", help="Write the JSON profile here (outside the target by default)."
        ),
    ] = None,
    as_json: JsonOpt = False,
) -> None:
    """Scan a project read-only: languages, frameworks, agent platforms, existing assets, managed state."""

    def body() -> None:
        from agent_forge.scanner.project_profile import scan_project

        ws = _ws(workspace)
        profile = scan_project(path, limits=ws.scan_limits)
        data = profile.model_dump(mode="json")
        dest = report
        if dest is None:
            safe = (
                profile.canonical_path.replace(":", "")
                .replace("\\", "_")
                .replace("/", "_")
                .strip("_")
            )
            dest = ws.reports_dir / f"scan-{safe[-80:]}.json"
        if Path(profile.canonical_path) in dest.resolve().parents:
            raise UsageError(
                "refusing to write the report inside the target project; choose --report outside it"
            )
        write_json(dest, data)
        if as_json:
            _print_json(data)
            return
        _print_profile(profile)
        console.print(f"[dim]report written to {dest}[/]")

    _run(body)


@app.command()
def drift(
    path: Annotated[Path, typer.Argument(help="Target project directory.")],
    workspace: WorkspaceOpt = None,
    as_json: JsonOpt = False,
) -> int:
    """Compare every managed file / section / merged entry with what was installed (read-only)."""

    def body() -> int:
        from agent_forge.decisions import evidence_drift, latest_record_path, load_record
        from agent_forge.planner.maintenance import drift_report
        from agent_forge.scanner.project_profile import scan_project

        ws = _ws(workspace)
        profile = scan_project(path, limits=ws.scan_limits)
        rep = drift_report(profile)
        root = Path(profile.canonical_path)
        basis: list = []
        record_file = latest_record_path(root)
        if record_file is not None:
            basis = evidence_drift(load_record(record_file), root)
        if as_json:
            _print_json(
                {
                    "target": rep.target,
                    "items": [i.__dict__ for i in rep.items],
                    "drifted": len(rep.drifted),
                    "decision_record": str(record_file) if record_file else None,
                    "decision_basis": [b.to_dict() for b in basis],
                }
            )
            return 0
        for b in basis:
            console.print(
                f"[yellow]decision basis {b.state}[/] {b.capability_id} ({b.verdict}): {b.detail}"
                " -> review it with /agent-forge-upgrade"
            )
        if not rep.items:
            console.print("no managed capabilities")
            return 0
        t = Table(title=f"drift: {len(rep.drifted)} of {len(rep.items)} item(s)")
        for col in ("capability", "kind", "path", "state", "expected", "actual"):
            t.add_column(col, overflow="fold")
        for i in rep.items:
            color = "green" if i.state == "ok" else "yellow"
            t.add_row(
                i.capability_id,
                i.kind,
                i.path,
                f"[{color}]{i.state}[/]",
                (i.expected or "-")[:12],
                (i.actual or "-")[:12],
            )
        console.print(t)
        if rep.drifted:
            console.print(
                "repair with [bold]agent-forge repair PATH --strategy restore|unmanage[/] (plan + approval)"
            )
        return 0

    _run(body)
    return 0


@app.command()
def status(
    path: Annotated[Path, typer.Argument(help="Target project directory.")],
    workspace: WorkspaceOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Report managed capabilities, drift, outdated versions, conflicts and recent transactions."""

    def body() -> None:
        from agent_forge.scanner.project_profile import scan_project

        ws = _ws(workspace)
        reg = _registry(ws)
        store = _store(ws)
        profile = scan_project(path, limits=ws.scan_limits)
        installed = {m.capability_id for m in profile.managed}
        rows = []
        for m in profile.managed:
            cap = reg.items.get(m.capability_id)
            reg_ver = cap.capability.version if cap else None
            conflicts = sorted(set(cap.capability.conflicts) & installed) if cap else []
            rows.append(
                {
                    "capability": m.capability_id,
                    "installed": m.version,
                    "registry": reg_ver,
                    "status": "local"
                    if m.is_local
                    else cap.capability.status.value
                    if cap
                    else "missing",
                    "drift": [f"{d} (edited since import)" for d in m.drift]
                    if m.is_local
                    else m.drift,
                    "conflicts": conflicts,
                    "files": len(m.files),
                    "transaction": m.transaction_id,
                    "installed_at": m.installed_at,
                }
            )
        txs = store.list_transactions(profile.canonical_path, limit=10)
        plans_ = [p for p in store.list_plans(profile.canonical_path)][:10]
        unfinished = store.transactions_needing_recovery(profile.canonical_path)
        absent, usage = _status_decisions(profile)
        if as_json:
            _print_json(
                {
                    "target": profile.canonical_path,
                    "managed_manifest_valid": profile.managed_manifest_valid,
                    "capabilities": rows,
                    "transactions": txs,
                    "needs_recovery": [{"transaction_id": t, "reason": r} for t, r in unfinished],
                    "plans": plans_,
                    "platforms": [p.platform.value for p in profile.platforms],
                    "decisions": absent,
                    "usage": usage,
                }
            )
            return
        console.print(
            Panel.fit(
                f"[bold]{profile.canonical_path}[/]\nplatforms: "
                f"{', '.join(p.platform.value for p in profile.platforms) or 'none'}  "
                f"managed manifest: {profile.managed_manifest_valid}",
                title="status",
            )
        )
        if rows:
            t = Table(title="managed capabilities")
            for col in (
                "capability",
                "installed",
                "registry",
                "status",
                "drift",
                "conflicts",
                "files",
                "transaction",
            ):
                t.add_column(col, overflow="fold")
            for r in rows:
                outdated = r["registry"] and r["registry"] != r["installed"]
                t.add_row(
                    r["capability"],
                    r["installed"],
                    ("[yellow]" + str(r["registry"]) + " (outdated)[/]")
                    if outdated
                    else str(r["registry"]),
                    r["status"],
                    "[yellow]" + ", ".join(r["drift"]) + "[/]" if r["drift"] else "-",
                    "[red]" + ", ".join(r["conflicts"]) + "[/]" if r["conflicts"] else "-",
                    str(r["files"]),
                    r["transaction"],
                )
            console.print(t)
        else:
            console.print("no managed capabilities")
        if txs:
            t = Table(title="recent transactions")
            for col in ("transaction", "plan", "status", "started", "finished"):
                t.add_column(col, overflow="fold")
            for x in txs:
                t.add_row(
                    x["transaction_id"],
                    x["plan_id"],
                    x["status"],
                    x["started_at"],
                    x["finished_at"] or "-",
                )
            console.print(t)
        if plans_:
            console.print("plans: " + ", ".join(f"{p['plan_id']} ({p['status']})" for p in plans_))
        for tx_id, why in unfinished:
            console.print(
                f"[red]needs recovery:[/] {tx_id}: {why}. Run `agent-forge rollback {tx_id}`."
            )
        for r in rows:
            if r["status"] in ("deprecated", "revoked"):
                cap = reg.items.get(r["capability"])
                instead = (
                    f"; use {cap.capability.replaced_by}"
                    if cap and cap.capability.replaced_by
                    else ""
                )
                color = "red" if r["status"] == "revoked" else "yellow"
                console.print(
                    f"[{color}]{r['status']}:[/] {r['capability']} is {r['status']} in the registry{instead} "
                    f"(docs/deprecation-policy.md; `agent-forge remove . {r['capability']}`)"
                )
        if absent:
            t = Table(title="absent by decision (/agent-forge-upgrade)")
            for col in ("capability", "verdict", "grounds", "basis", "assessed"):
                t.add_column(col, overflow="fold")
            for d in absent:
                t.add_row(
                    d["capability_id"],
                    d["verdict"],
                    ", ".join(d["grounds"]) or "-",
                    "\n".join(d["basis"]) or "-",
                    d["assessed_at"] or "-",
                )
            console.print(t)
        if usage and usage.get("log_present"):
            for cid in usage["unused"]:
                row = next(r for r in usage["by_capability"] if r["capability"] == cid)
                console.print(
                    f"[yellow]unused:[/] {cid} installed {row['days_installed']} day(s), "
                    f"0 invocations in {usage['window_days']} days -> `agent-forge remove PATH {cid}`?"
                )

    _run(body)


@app.command()
def rollback(
    transaction_id: str,
    workspace: WorkspaceOpt = None,
    partial: Annotated[
        bool,
        typer.Option(
            "--partial", help="Roll back untouched files even if others were modified after apply."
        ),
    ] = False,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip the interactive confirmation.")
    ] = False,
    as_json: JsonOpt = False,
) -> None:
    """Reverse a transaction. Files modified after apply are never overwritten."""

    def body() -> None:
        from agent_forge.rollback.engine import execute_rollback, plan_rollback

        ws = _ws(workspace)
        store = _store(ws)
        tx = store.load_transaction(transaction_id)
        rp = plan_rollback(store, tx)
        if not as_json:
            t = Table(title=f"rollback {transaction_id}")
            for col in ("action", "path", "detail"):
                t.add_column(col, overflow="fold")
            for c in rp.checks:
                color = {
                    "restore": "green",
                    "delete": "green",
                    "remove_section": "green",
                    "remove_json": "green",
                    "skip": "dim",
                    "conflict": "red",
                }[c.action]
                t.add_row(f"[{color}]{c.action}[/]", c.op.path, c.detail)
            console.print(t)
        if rp.conflicts and not partial:
            from agent_forge.errors import RollbackConflict

            raise RollbackConflict(
                "files changed independently after apply: "
                + ", ".join(c.op.path for c in rp.conflicts),
                hint="Inspect them, then re-run with --partial to roll back only the untouched files.",
            )
        if not rp.actionable:
            console.print("nothing to roll back")
            return
        if not yes and not as_json:
            if not sys.stdin.isatty():
                raise PlanError(
                    "interactive confirmation required (no TTY)", hint="Re-run with --yes."
                )
            if not typer.confirm(f"Roll back {len(rp.actionable)} file(s)?", default=False):
                raise PlanError("rollback cancelled by user")
        rb = execute_rollback(store, rp, partial=partial)
        _audit(
            store,
            "RollbackCompleted",
            transaction_id=rb.transaction_id,
            rollback_of=tx.transaction_id,
            target=tx.target_canonical_path,
            partial=bool(rp.conflicts),
        )
        if as_json:
            _print_json(rb.model_dump(mode="json"))
            return
        console.print(
            f"[green]rolled back[/] {len([o for o in rb.operations if o.applied])} file(s); record {rb.transaction_id}"
        )
        for n in rb.notes:
            console.print(f"[yellow]{n}[/]")

    _run(body)


def _status_decisions(profile) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Latest decision record (why capabilities are absent) and the local usage summary."""
    from agent_forge.decisions import latest_record_path, load_record
    from agent_forge.decisions.usage import USAGE_LOG, usage_summary
    from agent_forge.models.decision import Verdict

    root = Path(profile.canonical_path)
    absent: list[dict[str, Any]] = []
    record_file = latest_record_path(root)
    if record_file is not None:
        try:
            record = load_record(record_file)
        except PlanError:
            record = None
        if record is not None:
            for d in record.decisions:
                if d.verdict in (Verdict.SKIP, Verdict.REMOVE, Verdict.ASK):
                    absent.append(
                        {
                            "capability_id": d.capability_id,
                            "verdict": d.verdict.value,
                            "grounds": [g.value for g in d.grounds],
                            "basis": [c.path for c in d.citations],
                            "reason": d.reason,
                            "assessed_at": record.assessed_at,
                            "record": record_file.name,
                        }
                    )
    usage = usage_summary(profile) if (root / USAGE_LOG).is_file() else None
    return absent, usage
