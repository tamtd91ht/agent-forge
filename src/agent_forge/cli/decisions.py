"""The decision layer (ADR-0007): decisions verify / diff / explain / report, and usage."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table

from agent_forge.cli._app import app, decisions_app
from agent_forge.cli._common import (
    JsonOpt,
    WorkspaceOpt,
    _platform_list,
    _policies,
    _registry,
    _run,
    _ws,
    console,
)
from agent_forge.cli._envelope import _COMMAND, _print_json
from agent_forge.cli._tables import _brief_decision, _print_verify_report
from agent_forge.errors import PlanError, ValidationFailed


@app.command()
def usage(
    path: Annotated[Path, typer.Argument(help="Project directory.")],
    workspace: WorkspaceOpt = None,
    since: Annotated[int, typer.Option("--since", help="Window in days.", min=1)] = 30,
    as_json: JsonOpt = False,
) -> None:
    """Invocations per installed skill / subagent from the project's local usage log
    (`forge.hook.usage-log`, opt-in). Nothing is sent anywhere; rules are never "invoked"."""

    def body() -> None:
        from agent_forge.decisions.usage import usage_summary
        from agent_forge.scanner.project_profile import scan_project

        ws = _ws(workspace)
        profile = scan_project(path, limits=ws.scan_limits)
        data = usage_summary(profile, since_days=since)
        if as_json:
            _print_json(data)
            return
        if not data["log_present"]:
            console.print(
                f"no usage log ({data['log_path']}); enable it with "
                "`agent-forge forge PATH --want usage --hooks` (forge.hook.usage-log)"
            )
            return
        console.print(
            f"{data['entries_in_window']} invocation(s) in the last {since} day(s); "
            f"log covers {data['observed_days']} day(s), {data['entries']} record(s)"
        )
        t = Table(title="installed capabilities")
        for col in (
            "capability",
            "kind",
            "invocations",
            "sessions",
            "last used",
            "installed",
            "verdict",
        ):
            t.add_column(col, overflow="fold")
        for r in data["by_capability"]:
            verdict = (
                "[yellow]unused[/]"
                if r["unused"]
                else "-"
                if not r["invocable"]
                else "[green]used[/]"
                if r["invocations"]
                else "no data yet"
            )
            t.add_row(
                r["capability"],
                ", ".join(r["kinds"]) or "always-on",
                str(r["invocations"]),
                str(r["sessions"]),
                (r["last_used"] or "-")[:10],
                f"{r['days_installed']} d" if r["days_installed"] is not None else "-",
                verdict,
            )
        console.print(t)
        if data["unmanaged"]:
            console.print(
                "not managed by Agent Forge: "
                + ", ".join(f"{k} ({n})" for k, n in data["unmanaged"].items())
            )

    _run(body)


@decisions_app.callback()
def _decisions(ctx: typer.Context) -> None:
    """Read, verify and summarise the agent's decision records (ADR-0007). Read-only."""
    if ctx.invoked_subcommand:
        _COMMAND.append(ctx.invoked_subcommand)


def _record_for(path: Path, plan: str | None, file: Path | None) -> Path:
    from agent_forge.decisions import latest_record_path
    from agent_forge.decisions.verify import record_path

    root = path.resolve()
    if file is not None:
        return file
    if plan is not None:
        return record_path(root, plan)
    found = latest_record_path(root)
    if found is None:
        raise PlanError(
            f"no decision record under {root / '.agent-forge' / 'decisions'}",
            hint="Run /agent-forge-upgrade; the skill writes <plan-id>.json there.",
        )
    return found


@decisions_app.command("verify")
def decisions_verify(
    path: Annotated[Path, typer.Argument(help="Project directory.")],
    workspace: WorkspaceOpt = None,
    plan: Annotated[str | None, typer.Option("--plan", help="Plan id of the record.")] = None,
    file: Annotated[Path | None, typer.Option("--file", help="Record file to verify.")] = None,
    platform: Annotated[
        str | None, typer.Option("--platform", "-p", help="Platform to assess for.")
    ] = None,
    as_json: JsonOpt = False,
) -> int:
    """Check every claim in a decision record that a program can check: paths exist, quotes
    are real, numbers match the catalog, each ground carries its evidence, policy is respected.
    A SKIP / REMOVE that fails becomes ASK. Exit 12 when anything failed."""

    def body() -> int:
        from agent_forge.decisions import load_record, verify_record
        from agent_forge.decisions.usage import usage_summary
        from agent_forge.matching.rules import choose_platforms
        from agent_forge.scanner.project_profile import scan_project

        ws = _ws(workspace)
        reg = _registry(ws)
        profile = scan_project(path, limits=ws.scan_limits)
        record_file = _record_for(path, plan, file)
        record = load_record(record_file)
        platforms, _notes = choose_platforms(
            profile, _platform_list([platform] if platform else None)
        )
        vrep = verify_record(
            record,
            reg,
            profile,
            policy=_policies(ws, Path(profile.canonical_path)),
            platform=platforms[0],
            usage=usage_summary(profile),
            path=record_file,
        )
        if as_json:
            _print_json(vrep.to_dict())
        else:
            _print_verify_report(vrep, console)
            console.print(
                f"{len(vrep.items)} decision(s), {len(vrep.errors)} failed check(s), "
                f"{len(vrep.downgraded)} downgraded: "
                + ("[green]OK[/]" if vrep.ok else "[red]FAILED[/]")
            )
        return 0 if vrep.ok else ValidationFailed.exit_code

    _run(body)
    return 0


@decisions_app.command("diff")
def decisions_diff(
    path: Annotated[Path, typer.Argument(help="Project directory.")],
    old: Annotated[
        Path | None, typer.Option("--old", help="Older record (default: second newest).")
    ] = None,
    new: Annotated[
        Path | None, typer.Option("--new", help="Newer record (default: newest).")
    ] = None,
    as_json: JsonOpt = False,
) -> None:
    """Only the decisions that changed between two records, with the old and the new reason.
    A changed verdict on an unchanged project is a reason to look, not to apply."""

    def body() -> None:
        from agent_forge.decisions import diff_records, load_record
        from agent_forge.decisions.verify import DECISIONS_DIR

        root = path.resolve()
        files = [old, new]
        if old is None or new is None:
            directory = root / DECISIONS_DIR
            candidates = sorted(
                (p for p in directory.glob("*.json") if p.is_file() and not p.is_symlink())
                if directory.is_dir()
                else [],
                key=lambda p: (load_record(p).assessed_at, p.name),
            )
            if len(candidates) < 2:
                raise PlanError(
                    f"need two records under {directory} (found {len(candidates)})",
                    hint="Pass --old and --new explicitly.",
                )
            files = [old or candidates[-2], new or candidates[-1]]
        a, b = load_record(files[0]), load_record(files[1])
        changes = diff_records(a, b)
        if as_json:
            _print_json(
                {
                    "old": {
                        "path": str(files[0]),
                        "plan_id": a.plan_id,
                        "assessed_at": a.assessed_at,
                    },
                    "new": {
                        "path": str(files[1]),
                        "plan_id": b.plan_id,
                        "assessed_at": b.assessed_at,
                    },
                    "changes": changes,
                }
            )
            return
        console.print(f"{a.plan_id} ({a.assessed_at}) -> {b.plan_id} ({b.assessed_at})")
        if not changes:
            console.print("[green]no decision changed[/]")
            return
        t = Table(title=f"{len(changes)} changed decision(s)")
        for col in ("capability", "change", "old", "new"):
            t.add_column(col, overflow="fold")
        for c in changes:
            t.add_row(
                c["capability_id"],
                c["change"],
                _brief_decision(c["old"]),
                _brief_decision(c["new"]),
            )
        console.print(t)

    _run(body)


@decisions_app.command("explain")
def decisions_explain(
    path: Annotated[Path, typer.Argument(help="Project directory.")],
    capability_id: Annotated[str, typer.Argument(help="Capability id.")],
    as_json: JsonOpt = False,
) -> None:
    """Why this capability is (or is not) in the project, from the latest decision record."""

    def body() -> None:
        from agent_forge.decisions import load_record

        record_file = _record_for(path, None, None)
        record = load_record(record_file)
        d = record.by_id().get(capability_id)
        if d is None:
            raise PlanError(
                f"{capability_id} was not assessed in {record_file.name}",
                hint="`agent-forge catalog show <id>` describes it; /agent-forge-upgrade assesses it.",
            )
        if as_json:
            _print_json(
                {
                    "record": str(record_file),
                    "plan_id": record.plan_id,
                    "assessed_by": record.assessed_by,
                    "assessed_at": record.assessed_at,
                    "decision": d.model_dump(mode="json"),
                }
            )
            return
        console.print(
            Panel.fit(
                f"[bold]{d.verdict.value}[/] ({d.confidence.value} confidence)\n"
                f"grounds: {', '.join(g.value for g in d.grounds) or '-'}\n"
                f"covered by: {', '.join(c.path for c in d.covered_by) or '-'}\n"
                f"contradicts: {', '.join(c.path for c in d.contradicts) or '-'}\n"
                f"gap: {d.gap or '-'}\n"
                f"context: {d.context_chars if d.context_chars is not None else '?'} chars, "
                f"{'always-on' if d.always_on else 'on-demand'}; evidence: {d.evidence}\n"
                f"reason: {d.reason or '-'}\n"
                f"[dim]{record.assessed_by}, {record.assessed_at}, {record_file.name}[/]",
                title=capability_id,
            )
        )

    _run(body)


@decisions_app.command("report")
def decisions_report(
    directories: Annotated[list[Path], typer.Argument(help="Directories holding repositories.")],
    as_json: JsonOpt = False,
) -> None:
    """Organisation-wide table: capability x verdict x ground across every repository's latest
    decision record, with threshold-based suggestions for the catalog review (ADR-0008)."""

    def body() -> None:
        from agent_forge.decisions.report import org_report

        data = org_report([d.resolve() for d in directories])
        if as_json:
            _print_json(data)
            return
        console.print(
            f"{data['records']} repositor{'y' if data['records'] == 1 else 'ies'} with a decision record"
        )
        for pr in data["problems"]:
            console.print(f"[yellow]skipped:[/] {pr}")
        t = Table(title="capability x verdict x ground")
        for col in ("capability", "repos", "verdicts", "grounds"):
            t.add_column(col, overflow="fold")
        for row in data["capabilities"]:
            t.add_row(
                row["capability"],
                str(row["repos"]),
                ", ".join(f"{k} {v}" for k, v in row["verdicts"].items()),
                ", ".join(f"{k} {v}" for k, v in row["grounds"].items()) or "-",
            )
        console.print(t)
        for sg in data["suggestions"]:
            console.print(f"[bold]{sg['capability']}[/]: {sg['suggestion']} ({sg['why']})")
        if not data["suggestions"]:
            console.print(
                f"[dim]no suggestion: thresholds need >= {data['thresholds']['min_repos']} repositories per capability[/]"
            )

    _run(body)
