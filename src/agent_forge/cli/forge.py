"""One-shot and install commands that write to a project through saved plans: forge, setup, remove, repair."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.syntax import Syntax

from agent_forge.cli._app import app
from agent_forge.cli._common import (
    APPROVAL_FLAGS,
    ENTRY_CAPABILITY,
    JsonOpt,
    WorkspaceOpt,
    _audit,
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
from agent_forge.cli._tables import _print_plan_summary, _print_profile, _print_verify_report
from agent_forge.cli.plans import _approve_plan
from agent_forge.errors import PlanError, ValidationFailed


@app.command()
def forge(
    path: Annotated[Path, typer.Argument(help="Target project directory.")],
    workspace: WorkspaceOpt = None,
    platform: Annotated[
        list[str] | None,
        typer.Option(
            "--platform",
            "-p",
            help="claude_code, codex, cursor, copilot, gemini (default: detected).",
        ),
    ] = None,
    want: Annotated[
        list[str] | None, typer.Option("--want", help="Request capabilities carrying this tag.")
    ] = None,
    request: Annotated[
        list[str] | None, typer.Option("--request", help="Force-consider a capability id.")
    ] = None,
    exclude: Annotated[
        list[str] | None, typer.Option("--exclude", help="Never select this capability id.")
    ] = None,
    include_optional: Annotated[
        bool, typer.Option("--include-optional", help="Promote optional candidates.")
    ] = False,
    shared_files: Annotated[
        bool,
        typer.Option(
            "--shared-files",
            help="Allow managed sections in CLAUDE.md / AGENTS.md (otherwise those capabilities are left out).",
        ),
    ] = False,
    hooks: Annotated[
        bool,
        typer.Option(
            "--hooks",
            help="Allow hook capabilities (merged into .claude/settings.json; they run commands).",
        ),
    ] = False,
    mcp: Annotated[
        bool,
        typer.Option(
            "--mcp",
            help="Allow MCP server capabilities (merged into .mcp.json; they launch processes).",
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Non-interactive: approve and apply without prompting."),
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Scan, plan and show the diff only; write nothing.")
    ] = False,
    show_diff: Annotated[
        bool, typer.Option("--show-diff", help="Print full unified diffs before confirming.")
    ] = False,
    approval_file: Annotated[
        Path | None,
        typer.Option(
            "--approval-file",
            help="CI mode: non-interactive, approval classes and capabilities come from this "
            "committed file; a plan that goes beyond it is refused (exit 14) and nothing is written.",
        ),
    ] = None,
    decisions: Annotated[
        Path | None,
        typer.Option(
            "--decisions",
            help="Decision record written by /agent-forge-upgrade: verified first; effective "
            "SKIP/REMOVE become exclusions, ADD become requests, unresolved ASK stop a real run "
            "(--exclude/--request override per id). The record's digest is bound to the plan.",
        ),
    ] = None,
    as_json: JsonOpt = False,
) -> None:
    """One-shot upgrade: scan the project, upgrade what Agent Forge already manages, add the
    capabilities that fit, show the diff, ask once, then apply and validate.

    Still approval-first: every write is a saved plan with a digest-bound approval and a
    recoverable transaction. Hooks and MCP servers are separate approval classes: they are
    only planned when --hooks / --mcp are given (or confirmed interactively).
    """

    def body() -> int:
        from agent_forge.apply.engine import apply_plan
        from agent_forge.matching.rules import choose_platforms
        from agent_forge.planner import build_assign_plan, build_upgrade_plan, render_plan_diff
        from agent_forge.planner.approval_file import load_approval_file, require_plan_covered
        from agent_forge.scanner.project_profile import scan_project
        from agent_forge.validation.engine import validate_target

        ws = _ws(workspace)
        reg = _registry(ws)
        store = _store(ws)
        out = err_console if as_json else console
        report: dict[str, Any] = {"target": str(path), "steps": []}
        af = load_approval_file(approval_file) if approval_file is not None else None
        auto_yes = yes or af is not None  # an approval file replaces the interactive yes
        grant_shared, grant_hooks, grant_mcp = shared_files, hooks, mcp
        if af is not None:
            grant_shared, grant_hooks, grant_mcp = (
                af.granted("shared_file"),
                af.granted("hook"),
                af.granted("mcp"),
            )
            report["approval_file"] = str(approval_file)

        # 1. scan
        profile = scan_project(path, limits=ws.scan_limits)
        platforms, notes = choose_platforms(profile, _platform_list(platform))
        notes = [*notes, *_tool_notes(platforms)]
        if not as_json:
            _print_profile(profile)
            for n in notes:
                out.print(f"[dim]note:[/] {n}")
        report["profile"] = {
            "canonical_path": profile.canonical_path,
            "languages": sorted(profile.language_names),
            "frameworks": sorted(profile.framework_names),
            "project_types": sorted(profile.project_type_names),
            "traits": sorted(profile.trait_names),
            "platforms": [p.value for p in platforms],
            "managed": [m.capability_id for m in profile.managed],
        }
        from agent_forge.matching.rules import MatchContext

        # Approval classes granted up front decide what is even planned. Interactive runs
        # ask for the ungranted classes once, then re-plan with the answers.
        granted = {"standard"}
        if grant_shared:
            granted.add("shared_file")
        if grant_hooks:
            granted.add("hook")
        if grant_mcp:
            granted.add("mcp")
        if not auto_yes and not dry_run and sys.stdin.isatty():
            for klass, flag, what in (
                ("shared_file", "--shared-files", "managed sections in CLAUDE.md / AGENTS.md"),
                ("hook", "--hooks", "hook entries in .claude/settings.json (they run commands)"),
                ("mcp", "--mcp", "MCP servers in .mcp.json (they launch processes)"),
            ):
                if klass not in granted and typer.confirm(f"Allow {what}? [{flag}]", default=False):
                    granted.add(klass)
        policy_set = _policies(ws, Path(profile.canonical_path))
        requested_ids: frozenset[str] = frozenset(request or [])
        excluded_ids: frozenset[str] = frozenset(exclude or [])
        decisions_digest: str | None = None
        decision_notes: list[str] = []
        if decisions is not None:
            from agent_forge.decisions.plan_input import decisions_for_plan

            din = decisions_for_plan(
                decisions,
                reg,
                profile,
                policy=policy_set,
                platform=platforms[0],
                requested=set(requested_ids),
                excluded=set(excluded_ids),
            )
            report["decisions"] = din.report.to_dict()
            if not as_json:
                _print_verify_report(din.report, out)
            if din.unresolved and not dry_run:
                raise PlanError(
                    f"{len(din.unresolved)} decision(s) need the user: "
                    + ", ".join(din.unresolved),
                    hint="Answer each one with --exclude <id> or --request <id> (or amend the "
                    "record), or use --dry-run to preview. Downgraded SKIPs are listed above.",
                )
            requested_ids, excluded_ids = din.requested, din.excluded
            decisions_digest, decision_notes = din.digest, din.notes
        base_ctx = MatchContext(
            platforms=tuple(platforms),
            wanted_tags=frozenset(want or []),
            requested_ids=frozenset(requested_ids),
            excluded_ids=frozenset(excluded_ids),
            include_optional=include_optional,
            allowed_classes=frozenset(granted),
            policy=policy_set,
        )
        report["approval_classes"] = sorted(granted)

        def execute(plan, label: str) -> dict[str, Any]:
            step: dict[str, Any] = {"label": label, "plan_id": plan.plan_id}
            store.save_plan(plan)
            step["selected"] = [s.capability_id for s in plan.selected]
            step["rejected"] = {r.capability_id: r.category for r in plan.rejected}
            step["needs_approval"] = {
                r.capability_id: r.reasons for r in plan.rejected if r.category == "needs_approval"
            }
            if not as_json:
                out.rule(label)
                # already-managed entries were handled by the upgrade step just above;
                # not-applicable ones are a one-line footer rather than a row each
                _print_plan_summary(plan, hide=("already_installed", "not_applicable"))
                na = [r.capability_id for r in plan.rejected if r.category == "not_applicable"]
                if na:
                    out.print(
                        f"[dim]not applicable to this project ({len(na)}): {', '.join(na)}"
                        "  (add one with --request <id> or --want <tag>)[/]"
                    )
            if not plan.operations:
                step["status"] = "nothing_to_do"
                if not as_json:
                    out.print("[green]nothing to do[/]")
                return step
            diffs = render_plan_diff(plan, Path(plan.target.canonical_path))
            if show_diff and not as_json:
                for d in diffs:
                    out.rule(f"{d.op.op_id} {d.summary}")
                    out.print(Syntax(d.unified or "(no textual change)", "diff", theme="ansi_dark"))
            elif not as_json:
                for d in diffs:
                    out.print(f"  {d.summary}")
            if dry_run:
                step["status"] = "planned"
                if not as_json:
                    out.print(
                        f"[yellow]dry run:[/] nothing written. Re-run without --dry-run to apply "
                        f"(full diff: `agent-forge diff {plan.plan_id}`)"
                    )
                return step
            classes: dict[str, int] = {}
            for o in plan.operations_needing_extra_approval():
                classes[o.approval_class] = classes.get(o.approval_class, 0) + 1
            if not auto_yes:
                if not sys.stdin.isatty():
                    raise PlanError(
                        "interactive confirmation required (no TTY)",
                        hint="Re-run with --yes (plus --shared-files/--hooks/--mcp as needed) or use --dry-run.",
                    )
                question = f"Approve and apply {len(plan.operations)} operation(s)"
                if classes:
                    question += " including " + ", ".join(
                        f"{n} {k.replace('_', ' ')} change(s)" for k, n in classes.items()
                    )
                if not typer.confirm(question + "?", default=False):
                    step["status"] = "declined"
                    out.print(f"[yellow]declined[/]; plan {plan.plan_id} kept as draft")
                    return step
            if af is not None:
                require_plan_covered(plan, af, str(approval_file))
            _approve_plan(
                store,
                reg,
                plan,
                shared_files="shared_file" in granted,
                hooks="hook" in granted,
                mcp="mcp" in granted,
                by=f"approval-file:{af.approved_by}" if af is not None else "agent-forge forge",
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
            step["status"] = "applied"
            step["transaction_id"] = tx.transaction_id
            if not as_json:
                out.print(
                    f"[green]applied[/] {len([o for o in tx.operations if o.applied])} operation(s)"
                    f"; transaction {tx.transaction_id}"
                )
            return step

        # 2. upgrade what is already managed
        if profile.managed:
            up = build_upgrade_plan(reg, profile, base_ctx)
            up.notes = [*notes, *decision_notes, *up.notes]
            up.decisions_digest = decisions_digest
            report["steps"].append(execute(up, "upgrade managed capabilities"))
            if report["steps"][-1]["status"] == "applied":
                profile = scan_project(path, limits=ws.scan_limits)

        # 3. add what fits
        plan, _ = build_assign_plan(reg, profile, base_ctx)
        plan.notes = [*notes, *decision_notes, *plan.notes]
        plan.decisions_digest = decisions_digest
        report["steps"].append(execute(plan, "add recommended capabilities"))

        # 4. validate
        applied = any(s["status"] == "applied" for s in report["steps"])
        exit_code = 0
        if applied:
            profile = scan_project(path, limits=ws.scan_limits)
            rep = validate_target(ws, reg, store, profile)
            report["validation"] = {
                "ok": rep.ok,
                "errors": [f.message for f in rep.errors],
                "warnings": [f.message for f in rep.warnings],
            }
            if not as_json:
                out.rule("validate")
                for f in rep.findings:
                    color = {"error": "red", "warning": "yellow", "info": "dim"}[f.level]
                    out.print(f"[{color}]{f.level:7}[/] [{f.scope}] {f.message}")
                out.print(
                    f"managed now: {', '.join(m.capability_id for m in profile.managed) or '-'}"
                )
                out.print("[green]validation OK[/]" if rep.ok else "[red]validation FAILED[/]")
            if not rep.ok:
                exit_code = ValidationFailed.exit_code
        needs_runtime = {
            r.capability_id: r.reasons for r in plan.rejected if r.category == "needs_runtime"
        }
        report["needs_runtime"] = needs_runtime
        if needs_runtime and not as_json:
            out.rule("available with a native runtime (not installed by Agent Forge)")
            for cid, reasons in needs_runtime.items():
                out.print(f"[bold]{cid}[/]")
                for line in reasons[1:]:
                    out.print(f"    {line}")
        if as_json:
            _print_json(report)
        return exit_code

    _run(body)


@app.command()
def setup(
    path: Annotated[
        Path | None, typer.Argument(help="Project directory (default: current).")
    ] = None,
    workspace: WorkspaceOpt = None,
    platform: Annotated[
        list[str] | None,
        typer.Option(
            "--platform",
            "-p",
            help="claude_code, codex, cursor, copilot, gemini (default: detected).",
        ),
    ] = None,
    as_json: JsonOpt = False,
) -> None:
    """Install (or update) only the /agent-forge-upgrade entry skill into a project.

    Run by the one-line installer in the project root. Nothing else is selected: the agent in
    that project reviews it and proposes the rest. Writes go through a saved, approved plan and
    a transaction like every other install, so `status`, `remove` and `rollback` work on it.
    """

    def body() -> None:
        from agent_forge.apply.engine import apply_plan
        from agent_forge.matching.rules import MatchContext, choose_platforms
        from agent_forge.planner import build_assign_plan, build_upgrade_plan
        from agent_forge.scanner.project_profile import scan_project

        ws = _ws(workspace)
        reg = _registry(ws)
        store = _store(ws)
        reg.get(ENTRY_CAPABILITY)  # fails loudly on a registry without the entry skill
        target = path or Path.cwd()
        profile = scan_project(target, limits=ws.scan_limits)
        platforms, notes = choose_platforms(profile, _platform_list(platform))
        notes = [*notes, *_tool_notes(platforms)]
        ctx = MatchContext(
            platforms=tuple(platforms),
            requested_ids=frozenset({ENTRY_CAPABILITY}),
            excluded_ids=frozenset(set(reg.items) - {ENTRY_CAPABILITY}),
            allowed_classes=frozenset({"standard"}),
            policy=_policies(ws, Path(profile.canonical_path)),
        )
        result: dict[str, Any] = {"target": profile.canonical_path, "steps": []}
        builders = [build_upgrade_plan] if profile.managed else []
        builders.append(lambda r, p, c: build_assign_plan(r, p, c)[0])
        for build in builders:
            plan = build(reg, profile, ctx)
            if not plan.operations:
                continue
            store.save_plan(plan)
            _approve_plan(store, reg, plan, shared_files=False, by="agent-forge setup")
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
            result["steps"].append(
                {
                    "plan_id": plan.plan_id,
                    "transaction_id": tx.transaction_id,
                    "files": [o.path for o in plan.operations],
                }
            )
            profile = scan_project(target, limits=ws.scan_limits)
        installed = {m.capability_id: m for m in profile.managed}
        if ENTRY_CAPABILITY not in installed:
            rejected = [r for r in plan.rejected if r.capability_id == ENTRY_CAPABILITY]
            why = "; ".join(rejected[0].reasons) if rejected else "not selected"
            raise PlanError(f"could not install {ENTRY_CAPABILITY}: {why}")
        result["installed_version"] = installed[ENTRY_CAPABILITY].version
        result["platforms"] = [p.value for p in platforms]
        if as_json:
            _print_json(result)
            return
        for n in notes:
            console.print(f"[dim]note:[/] {n}")
        for step in result["steps"]:
            for f in step["files"]:
                console.print(f"  [green]wrote[/] {f}")
            console.print(f"  [dim]transaction {step['transaction_id']}[/]")
        if not result["steps"]:
            console.print(f"{ENTRY_CAPABILITY} {result['installed_version']} is already up to date")
        console.print(
            "[green]ready.[/] Open this project in Claude Code (or Codex) and run "
            "[bold]/agent-forge-upgrade[/]."
        )

    _run(body)


@app.command()
def remove(
    path: Annotated[Path, typer.Argument(help="Target project directory.")],
    capability_ids: Annotated[
        list[str], typer.Argument(help="Managed capability id(s) to remove.")
    ],
    workspace: WorkspaceOpt = None,
    keep_modified: Annotated[
        bool,
        typer.Option("--keep-modified", help="Unmanage files you edited instead of refusing."),
    ] = False,
    as_json: JsonOpt = False,
) -> None:
    """Plan the removal of managed capabilities (files, sections, merged entries). Writes nothing;
    approve + apply the plan as usual."""

    def body() -> None:
        from agent_forge.planner.maintenance import build_remove_plan
        from agent_forge.scanner.project_profile import scan_project

        ws = _ws(workspace)
        reg = _registry(ws)
        profile = scan_project(path, limits=ws.scan_limits)
        plan = build_remove_plan(reg, profile, list(capability_ids), keep_modified=keep_modified)
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
        flags = " ".join(
            sorted(
                {APPROVAL_FLAGS[o.approval_class] for o in plan.operations_needing_extra_approval()}
            )
        )
        console.print(
            f"next: [bold]agent-forge approve {plan.plan_id} {flags}[/] then [bold]agent-forge apply {plan.plan_id}[/]"
        )

    _run(body)


@app.command()
def repair(
    path: Annotated[Path, typer.Argument(help="Target project directory.")],
    workspace: WorkspaceOpt = None,
    strategy: Annotated[
        str,
        typer.Option(
            "--strategy",
            help="restore (rewrite from registry; your edits are replaced) | unmanage (drop from manifest, keep files)",
        ),
    ] = "restore",
    capability: Annotated[
        list[str] | None,
        typer.Option("--capability", help="Limit to these ids (default: all drifted)."),
    ] = None,
    as_json: JsonOpt = False,
) -> None:
    """Plan a repair for drifted capabilities. Writes nothing; approve + apply the plan."""

    def body() -> None:
        from agent_forge.planner.maintenance import build_repair_plan
        from agent_forge.scanner.project_profile import scan_project

        ws = _ws(workspace)
        reg = _registry(ws)
        profile = scan_project(path, limits=ws.scan_limits)
        plan = build_repair_plan(reg, profile, strategy, capability)
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
        if not plan.operations:
            console.print("[green]nothing to repair[/]")
        console.print(f"[dim]plan saved: {p}[/]")

    _run(body)
