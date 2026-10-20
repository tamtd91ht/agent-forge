"""`agent-forge-eval run` — baseline vs candidate on one fixture, locally, opt-in.

    agent-forge-eval run --fixture examples/python-fastapi --capability ecc.tdd-workflow \
        --tool claude --runs 3 --out docs/evaluation/results

Writes `<out>/<date>-<capability>-<fixture>.json` (every run) and `.md` (summary). The
report is evidence for a human decision (promote / revise / retire); it is never applied to
the registry automatically. `--tool scripted` runs a no-op agent for smoke tests of the
harness itself and must never be presented as a measurement.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from agent_forge_eval import __version__
from agent_forge_eval.harness import (
    Arm,
    claude_runner,
    codex_runner,
    load_tasks,
    records_to_json,
    run_matrix,
    scripted_runner,
)
from agent_forge_eval.stats import summarise, to_markdown


def _agent_forge_argv(explicit: str | None) -> list[str]:
    if explicit:
        return [explicit]
    for cand in ("agent-forge", str(Path.home() / ".agent-forge" / "bin" / "agent-forge")):
        if shutil.which(cand) or Path(cand).is_file():
            return [cand]
    raise SystemExit("agent-forge not found; pass --agent-forge PATH")


def _version_of(argv: list[str]) -> str:
    try:
        return subprocess.run(
            [*argv, "--version"], capture_output=True, text=True, check=False
        ).stdout.strip()
    except OSError:
        return "unknown"


def cmd_run(args: argparse.Namespace) -> int:
    fixture = Path(args.fixture).resolve()
    tasks = load_tasks(fixture)
    if args.task:
        tasks = [t for t in tasks if t.id in set(args.task)]
    if not tasks:
        raise SystemExit("no tasks selected")
    extra = args.tool_args or []
    if args.tool == "claude":
        runner = claude_runner(extra)
    elif args.tool == "codex":
        runner = codex_runner(extra)
    else:
        runner = scripted_runner(lambda project, prompt: 0)
    af = _agent_forge_argv(args.agent_forge)
    arms = [Arm("baseline", None), Arm("candidate", args.capability)]
    if args.arm:
        arms = [a for a in arms if a.name in set(args.arm)]
    print(
        f"agent-forge-eval {__version__}: {len(tasks)} task(s)  x  {len(arms)} arm(s)  x  {args.runs} run(s)",
        file=sys.stderr,
    )

    def progress(rec) -> None:
        print(
            f"  {rec.task_id:28} {rec.arm:9} run {rec.run}: {'PASS' if rec.passed else 'fail'} "
            f"({rec.tool.wall_seconds:.0f}s{', timeout' if rec.tool.timed_out else ''})",
            file=sys.stderr,
        )

    records = run_matrix(
        fixture,
        tasks,
        arms,
        runner,
        runs=args.runs,
        agent_forge=af,
        workspace=Path(args.workspace) if args.workspace else None,
        keep=args.keep,
        on_record=progress,
    )
    summary = summarise(records)
    meta = {
        "harness_version": __version__,
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "fixture": fixture.name,
        "capability": args.capability,
        "tool": args.tool if args.tool != "scripted" else "scripted (NOT a measurement)",
        "tool_args": extra,
        "runs": args.runs,
        "tasks": [t.id for t in tasks],
        "agent_forge_version": _version_of(af),
    }
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{datetime.now(UTC).strftime('%Y%m%d')}-{args.capability}-{fixture.name}"
    (out_dir / f"{stem}.json").write_text(
        json.dumps(
            {"meta": meta, "summary": summary, "records": records_to_json(records)}, indent=2
        ),
        encoding="utf-8",
    )
    (out_dir / f"{stem}.md").write_text(to_markdown(meta, summary), encoding="utf-8")
    print(to_markdown(meta, summary))
    print(f"written: {out_dir / (stem + '.json')}", file=sys.stderr)
    return 0


def cmd_tasks(args: argparse.Namespace) -> int:
    for t in load_tasks(Path(args.fixture)):
        print(
            f"{t.id:30} {t.category:9} budget {t.budget_seconds}s  {t.prompt.splitlines()[0][:70]}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="agent-forge-eval",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run baseline vs candidate on a fixture")
    r.add_argument("--fixture", required=True, help="examples/<name> directory (project/ + tasks/)")
    r.add_argument(
        "--capability", required=True, help="capability id installed in the candidate arm"
    )
    r.add_argument("--tool", choices=["claude", "codex", "scripted"], default="claude")
    r.add_argument("--tool-args", nargs="*", help="extra arguments for the tool (e.g. --model ...)")
    r.add_argument("--runs", type=int, default=3, help="runs per task and arm (>= 3 recommended)")
    r.add_argument("--task", action="append", help="limit to these task ids")
    r.add_argument("--arm", action="append", choices=["baseline", "candidate"])
    r.add_argument(
        "--agent-forge", help="agent-forge executable (default: PATH or ~/.agent-forge/bin)"
    )
    r.add_argument("--workspace", help="agent-forge workspace for the candidate install")
    r.add_argument("--out", default="docs/evaluation/results")
    r.add_argument("--keep", action="store_true", help="keep temporary project copies")
    r.set_defaults(fn=cmd_run)
    t = sub.add_parser("tasks", help="list a fixture's tasks")
    t.add_argument("--fixture", required=True)
    t.set_defaults(fn=cmd_tasks)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
