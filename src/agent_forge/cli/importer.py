"""`agent-forge import`: adopt hand-written agent assets into the managed manifest (ADR-0011)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

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
from agent_forge.cli._tables import _print_plan_summary
from agent_forge.cli.plans import _approve_plan


@app.command(name="import")
def import_(
    path: Annotated[Path, typer.Argument(help="Target project directory.")],
    workspace: WorkspaceOpt = None,
    kind: Annotated[
        list[str] | None,
        typer.Option("--kind", help="Only this kind: skill, agent, rule, command (repeatable)."),
    ] = None,
    only: Annotated[
        list[str] | None,
        typer.Option("--path", help="Only assets under this project-relative path (repeatable)."),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Approve and apply the import plan right away."),
    ] = False,
    as_json: JsonOpt = False,
) -> None:
    """Record the project's hand-written skills, subagents, rules and commands in
    .agent-forge/managed.json as local.* entries, in place: files are never copied or
    rewritten, only their hashes are recorded, so status, usage, drift, remove and the
    decision record can see them. Writes a plan; `--yes` approves and applies it (the only
    operation is the manifest write)."""

    def body() -> None:
        from agent_forge.apply.engine import apply_plan
        from agent_forge.planner.adopt import build_import_plan
        from agent_forge.scanner.project_profile import scan_project

        ws = _ws(workspace)
        reg = _registry(ws)
        store = _store(ws)
        profile = scan_project(path, limits=ws.scan_limits)
        plan = build_import_plan(
            reg, profile, kinds=tuple(kind) if kind else None, paths=tuple(only or ())
        )
        result: dict[str, Any] = {
            "target": profile.canonical_path,
            "plan_id": plan.plan_id,
            "adopted": [
                {"capability": s.capability_id, "files": [a.removeprefix("track ") for a in s.adds]}
                for s in plan.selected
            ],
            "notes": plan.notes,
            "status": "planned" if plan.operations else "nothing_to_import",
        }
        if not plan.operations:
            if as_json:
                _print_json(result)
            else:
                for n in plan.notes:
                    console.print(f"[dim]note:[/] {n}")
                console.print("nothing to import")
            return
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
        if yes:
            _approve_plan(store, reg, plan, shared_files=False, by="agent-forge import --yes")
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
            result["status"] = "applied"
            result["transaction_id"] = tx.transaction_id
        if as_json:
            _print_json(result)
            return
        _print_plan_summary(plan, hide=("not_applicable",))
        if yes:
            console.print(
                f"[green]adopted[/] {len(plan.selected)} asset(s); transaction "
                f"{result['transaction_id']}. Undo with `agent-forge rollback {result['transaction_id']}`."
            )
            return
        console.print(f"[dim]plan saved: {p}[/]")
        console.print(
            f"next: [bold]agent-forge approve {plan.plan_id}[/]  then  "
            f"[bold]agent-forge apply {plan.plan_id}[/]  (or re-run with --yes)"
        )

    _run(body)
