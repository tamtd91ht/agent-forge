"""Plan lifecycle commands: assign, upgrade, plans, diff, approve, apply."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from agent_forge.cli._app import app
from agent_forge.cli._common import (
    APPROVAL_FLAGS,
    JsonOpt,
    WorkspaceOpt,
    _audit,
    _ctx,
    _platform_list,
    _policies,
    _registry,
    _run,
    _store,
    _tool_notes,
    _ws,
    console,
    err_console,
)
from agent_forge.cli._envelope import _print_json
from agent_forge.cli._tables import _print_plan_summary
from agent_forge.errors import PlanError
from agent_forge.models.plan import PlanStatus
from agent_forge.util import dump_yaml, now_iso


@app.command()
def assign(
    path: Annotated[Path, typer.Argument(help="Target project directory.")],
    workspace: WorkspaceOpt = None,
    platform: Annotated[
        list[str] | None,
        typer.Option(
            "--platform",
            "-p",
            help="Target platform(s): claude_code, codex, cursor, copilot, gemini. Default: detected.",
        ),
    ] = None,
    want: Annotated[
        list[str] | None,
        typer.Option("--want", help="Request capabilities carrying this tag (e.g. ui, security)."),
    ] = None,
    request: Annotated[
        list[str] | None, typer.Option("--request", help="Force-consider a capability id.")
    ] = None,
    exclude: Annotated[
        list[str] | None, typer.Option("--exclude", help="Never select this capability id.")
    ] = None,
    include_optional: Annotated[
        bool, typer.Option("--include-optional", help="Promote optional candidates into the plan.")
    ] = False,
    as_json: JsonOpt = False,
) -> None:
    """Recommend capabilities for a project and write a reviewable plan. Never modifies the target."""

    def body() -> None:
        from agent_forge.matching.rules import choose_platforms
        from agent_forge.planner import build_assign_plan
        from agent_forge.scanner.project_profile import scan_project

        ws = _ws(workspace)
        reg = _registry(ws)
        profile = scan_project(path, limits=ws.scan_limits)
        platforms, notes = choose_platforms(profile, _platform_list(platform))
        notes = [*notes, *_tool_notes(platforms)]
        ctx = _ctx(
            ws,
            Path(profile.canonical_path),
            tuple(platforms),
            want,
            request,
            exclude,
            include_optional,
        )
        plan, _match = build_assign_plan(reg, profile, ctx)
        plan.notes = [*notes, *plan.notes]
        store = _store(ws)
        p = store.save_plan(plan)
        _audit(
            store,
            "PlanCreated",
            plan_id=plan.plan_id,
            kind=plan.kind,
            target=plan.target.canonical_path,
            registry_digest=plan.registry_digest,
            operations=len(plan.operations),
        )
        if as_json:
            _print_json(plan.model_dump(mode="json"))
            return
        _print_plan_summary(plan)
        console.print(f"[dim]plan saved: {p}[/]")
        console.print(
            f"next: [bold]agent-forge diff {plan.plan_id}[/]  then  [bold]agent-forge approve {plan.plan_id}[/]"
        )

    _run(body)


@app.command()
def upgrade(
    path: Annotated[Path, typer.Argument(help="Target project directory.")],
    workspace: WorkspaceOpt = None,
    platform: Annotated[list[str] | None, typer.Option("--platform", "-p")] = None,
    as_json: JsonOpt = False,
) -> None:
    """Compare managed capabilities with the registry and write an upgrade plan. Never modifies the target."""

    def body() -> None:
        from agent_forge.matching.rules import choose_platforms
        from agent_forge.planner import build_upgrade_plan
        from agent_forge.scanner.project_profile import scan_project

        ws = _ws(workspace)
        reg = _registry(ws)
        profile = scan_project(path, limits=ws.scan_limits)
        platforms, notes = choose_platforms(profile, _platform_list(platform))
        notes = [*notes, *_tool_notes(platforms)]
        plan = build_upgrade_plan(
            reg,
            profile,
            _ctx(ws, Path(profile.canonical_path), tuple(platforms), None, None, None, False),
        )
        plan.notes = [*notes, *plan.notes]
        store = _store(ws)
        p = store.save_plan(plan)
        _audit(
            store,
            "PlanCreated",
            plan_id=plan.plan_id,
            kind=plan.kind,
            target=plan.target.canonical_path,
            registry_digest=plan.registry_digest,
            operations=len(plan.operations),
        )
        if as_json:
            _print_json(plan.model_dump(mode="json"))
            return
        _print_plan_summary(plan)
        console.print(f"[dim]plan saved: {p}[/]")
        if not plan.operations:
            console.print("[green]nothing to upgrade[/]")
            return
        console.print(
            f"next: [bold]agent-forge diff {plan.plan_id}[/]  then  [bold]agent-forge approve {plan.plan_id}[/]"
        )

    _run(body)


@app.command()
def plans(
    workspace: WorkspaceOpt = None,
    target: Annotated[Path | None, typer.Option(help="Only plans for this target.")] = None,
    as_json: JsonOpt = False,
) -> None:
    """List saved plans."""

    def body() -> None:
        store = _store(_ws(workspace))
        rows = store.list_plans(str(target.resolve()) if target else None)
        if as_json:
            _print_json(rows)
            return
        t = Table(title="plans")
        for col in ("plan", "kind", "status", "created", "target"):
            t.add_column(col, overflow="fold")
        for r in rows:
            t.add_row(r["plan_id"], r["kind"], r["status"], r["created_at"], r["target"])
        console.print(t)

    _run(body)


@app.command()
def diff(
    plan_id: str,
    workspace: WorkspaceOpt = None,
    full: Annotated[
        bool, typer.Option("--full", help="Show complete diffs for new files too.")
    ] = False,
    as_json: JsonOpt = False,
) -> None:
    """Show exact proposed additions, modifications and removals for a plan."""

    def body() -> None:
        from agent_forge.planner import render_plan_diff

        ws = _ws(workspace)
        store = _store(ws)
        plan = store.load_plan(plan_id)
        diffs = render_plan_diff(plan, Path(plan.target.canonical_path))
        if as_json:
            _print_json(
                [
                    {
                        "op_id": d.op.op_id,
                        "kind": d.op.kind.value,
                        "path": d.op.path,
                        "stale": d.stale,
                        "extra_approval": d.op.requires_extra_approval,
                        "summary": d.summary,
                        "diff": d.unified,
                        "warnings": d.warnings,
                    }
                    for d in diffs
                ]
            )
            return
        _print_plan_summary(plan)
        for d in diffs:
            flag = " [red]STALE[/]" if d.stale else ""
            extra = (
                " [yellow](shared file: extra approval)[/]" if d.op.requires_extra_approval else ""
            )
            console.rule(f"{d.op.op_id} {d.summary}{flag}{extra}")
            for w in d.warnings:
                console.print(f"[yellow]warning:[/] {w}")
            text = d.unified
            if not full and d.op.before_sha256 is None and text.count("\n") > 60:
                lines = text.splitlines()
                text = "\n".join(lines[:60]) + f"\n... ({len(lines) - 60} more lines; use --full)"
            console.print(
                Syntax(text or "(no textual change)", "diff", theme="ansi_dark", word_wrap=True)
            )
        if any(d.stale for d in diffs):
            console.print("[red]plan is stale for at least one file; re-run assign/upgrade[/]")

    _run(body)


def _approve_plan(
    store,
    reg,
    plan,
    *,
    shared_files: bool,
    by: str | None,
    hooks: bool = False,
    mcp: bool = False,
) -> list:
    """Shared approval logic: staleness checks, per-class gates, digest binding. Returns extra ops."""
    from agent_forge.errors import StalePlanError
    from agent_forge.planner import render_plan_diff

    if plan.status not in (PlanStatus.DRAFT, PlanStatus.APPROVED, PlanStatus.REVOKED):
        raise PlanError(f"plan is {plan.status.value}; create a new plan")
    if not plan.operations:
        raise PlanError("plan has no operations; nothing to approve")
    diffs = render_plan_diff(plan, Path(plan.target.canonical_path))
    stale = [d.op.path for d in diffs if d.stale]
    if stale:
        plan.status = PlanStatus.STALE
        store.save_plan(plan)
        raise StalePlanError(
            "plan is stale; target files changed since planning: " + ", ".join(stale),
            hint="Re-run `assign`/`upgrade`.",
        )
    if reg.digest != plan.registry_digest:
        plan.status = PlanStatus.STALE
        store.save_plan(plan)
        raise StalePlanError("registry changed since planning", hint="Re-run `assign`/`upgrade`.")
    if plan.is_expired(datetime.now(UTC)):
        plan.status = PlanStatus.STALE
        store.save_plan(plan)
        raise StalePlanError(
            f"plan expired at {plan.expires_at}", hint="Re-run `assign`/`upgrade`."
        )
    target = Path(plan.target.canonical_path)
    if plan.policy_digest is not None and (
        _policies(store.ws, target).digest != plan.policy_digest
    ):
        plan.status = PlanStatus.STALE
        store.save_plan(plan)
        raise StalePlanError("policy changed since planning", hint="Re-run `assign`/`upgrade`.")
    extra = plan.operations_needing_extra_approval()
    granted = {"shared_file": shared_files, "hook": hooks, "mcp": mcp}
    missing: dict[str, list[str]] = {}
    for o in extra:
        if not granted.get(o.approval_class, False):
            missing.setdefault(o.approval_class, []).append(o.path)
    if missing:
        detail = "; ".join(
            f"{klass} ({APPROVAL_FLAGS.get(klass, klass)}): {', '.join(sorted(set(paths)))}"
            for klass, paths in missing.items()
        )
        raise PlanError(
            "plan needs explicit approval for: " + detail,
            hint="Review `diff`, then re-run approve with the listed flag(s). Hooks run commands "
            "and MCP servers launch processes, so each class is approved separately.",
        )
    plan.approval.status = "approved"
    plan.approval.approved_at = now_iso()
    plan.approval.approved_by = by
    plan.approval.plan_digest = plan.content_digest()
    plan.approval.extra_approvals = [o.op_id for o in extra]
    plan.status = PlanStatus.APPROVED
    store.save_plan(plan)
    store.record_approval(plan)
    _audit(
        store,
        "PlanApproved",
        plan_id=plan.plan_id,
        target=plan.target.canonical_path,
        plan_digest=plan.approval.plan_digest,
        approved_by=by,
        classes=sorted({o.approval_class for o in extra}),
    )
    return extra


@app.command()
def approve(
    plan_id: str,
    workspace: WorkspaceOpt = None,
    shared_files: Annotated[
        bool,
        typer.Option(
            "--shared-files",
            help="Also approve operations that modify shared files (CLAUDE.md, AGENTS.md, settings).",
        ),
    ] = False,
    hooks: Annotated[
        bool,
        typer.Option(
            "--hooks", help="Also approve hook entries (they execute commands in your sessions)."
        ),
    ] = False,
    mcp: Annotated[
        bool,
        typer.Option(
            "--mcp", help="Also approve MCP server entries (they launch processes / use network)."
        ),
    ] = False,
    by: Annotated[
        str | None, typer.Option("--by", help="Approver name recorded in the plan.")
    ] = None,
    revoke: Annotated[bool, typer.Option("--revoke", help="Revoke a previous approval.")] = False,
    approval_file: Annotated[
        Path | None,
        typer.Option(
            "--approval-file",
            help="Approve non-interactively from a committed approval file (ids, versions, "
            "classes); refuses with exit 14 when the plan goes beyond it.",
        ),
    ] = None,
    export_approval: Annotated[
        Path | None,
        typer.Option(
            "--export-approval",
            help="After approving, write an approval file covering exactly this plan "
            "(commit it as .agent-forge/approval.yaml for CI).",
        ),
    ] = None,
) -> None:
    """Approve a plan. The approval is bound to the plan's content digest; any change invalidates it."""

    def body() -> None:
        from agent_forge.planner.approval_file import (
            approval_from_plan,
            load_approval_file,
            require_plan_covered,
        )

        ws = _ws(workspace)
        store = _store(ws)
        plan = store.load_plan(plan_id)
        granted_shared, granted_hooks, granted_mcp, approver = shared_files, hooks, mcp, by
        if approval_file is not None:
            af = load_approval_file(approval_file)
            require_plan_covered(plan, af, str(approval_file))
            granted_shared = af.granted("shared_file")
            granted_hooks = af.granted("hook")
            granted_mcp = af.granted("mcp")
            approver = by or f"approval-file:{af.approved_by}"
        if revoke:
            plan.approval.status = "revoked"
            plan.approval.plan_digest = None
            plan.approval.extra_approvals = []
            plan.status = PlanStatus.REVOKED
            store.save_plan(plan)
            store.revoke_approval(plan.plan_id)
            _audit(store, "PlanRevoked", plan_id=plan.plan_id, target=plan.target.canonical_path)
            console.print(f"[yellow]approval revoked for {plan_id}[/]")
            return
        reg = _registry(ws)
        extra = _approve_plan(
            store,
            reg,
            plan,
            shared_files=granted_shared,
            by=approver,
            hooks=granted_hooks,
            mcp=granted_mcp,
        )
        console.print(
            f"[green]approved[/] {plan_id} (digest {plan.approval.plan_digest[:16]}, {len(plan.operations)} operations"
            + (f", {len(extra)} shared-file" if extra else "")
            + ")"
        )
        if export_approval is not None:
            classes = [
                k
                for k, on in (
                    ("shared_file", granted_shared),
                    ("hook", granted_hooks),
                    ("mcp", granted_mcp),
                )
                if on
            ]
            doc = approval_from_plan(plan, by=approver or "unknown", classes=classes, note=None)
            export_approval.parent.mkdir(parents=True, exist_ok=True)
            export_approval.write_text(dump_yaml(doc), encoding="utf-8")
            console.print(f"approval file written: [bold]{export_approval}[/] (commit it)")
        console.print(f"next: [bold]agent-forge apply {plan_id}[/]")

    _run(body)


@app.command()
def apply(
    plan_id: str,
    workspace: WorkspaceOpt = None,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Skip the interactive confirmation (approval, hashes and scope are still enforced).",
        ),
    ] = False,
    as_json: JsonOpt = False,
) -> None:
    """Apply an approved, non-stale plan inside a recoverable transaction."""

    def body() -> None:
        from agent_forge.apply.engine import apply_plan

        ws = _ws(workspace)
        store = _store(ws)
        reg = _registry(ws)
        plan = store.load_plan(plan_id)

        def confirm(rep) -> bool:
            out = err_console if as_json else console
            out.print(
                Panel.fit(
                    "\n".join(rep.summary), title=f"apply {plan_id} -> {plan.target.canonical_path}"
                )
            )
            for w in rep.warnings:
                out.print(f"[yellow]warning:[/] {w}")
            if yes:
                return True
            if not sys.stdin.isatty():
                raise PlanError(
                    "interactive confirmation required (no TTY)",
                    hint="Re-run with --yes after reviewing `diff`.",
                )
            return typer.confirm("Write these changes to the target?", default=False)

        tx = apply_plan(ws, store, reg, plan, confirm=confirm)
        _audit(
            store,
            "TransactionCompleted",
            transaction_id=tx.transaction_id,
            plan_id=plan.plan_id,
            target=tx.target_canonical_path,
            status=tx.status.value,
            capabilities=sorted(tx.capabilities),
        )
        if as_json:
            _print_json(tx.model_dump(mode="json"))
            return
        console.print(
            f"[green]applied[/] {len([o for o in tx.operations if o.applied])} operation(s); transaction {tx.transaction_id}"
        )
        console.print(
            f"next: [bold]agent-forge validate {plan.target.canonical_path}[/]   "
            f"rollback: [bold]agent-forge rollback {tx.transaction_id}[/]"
        )

    _run(body)
