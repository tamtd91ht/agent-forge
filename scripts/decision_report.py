"""Golden decisions: measure how far the entry skill's assessments drift (ADR-0007, fix list 3).

    python scripts/decision_report.py --record <decisions.json> --golden examples/lint-messy/expected_decisions.json
    python scripts/decision_report.py --fixture examples/lint-messy --run [--tool claude]

`--record` compares one decision record with its golden file cell by cell and prints the
drift table (verdict, grounds, basis). `--run` first produces the record: it copies the
fixture project to a temporary directory, installs the entry skill there with the local
`agent-forge setup`, runs the coding tool in print mode with `/agent-forge-upgrade`, and
picks up the record the skill wrote. Running costs real model time and needs the tool on
PATH, so it is never part of CI. Run it when SKILL.md changes, when the default model
changes, and before a release; commit the report under docs/evaluation/decisions/.

Golden file format (one object per capability; `*` is "any"):

    {"reviewed": "YYYY-MM-DD", "notes": "...",
     "decisions": {"<capability_id>": {"verdict": "SKIP", "grounds": ["covered"],
                                        "basis": [".claude/rules/testing.md"]}}}

A golden verdict of "SKIP|ASK" accepts either; `basis` lists paths that must appear among
`covered_by` / `contradicts`.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_forge.decisions.verify import latest_record_path, load_record  # noqa: E402
from agent_forge.models.decision import DecisionRecord  # noqa: E402


def compare(golden: dict, record: DecisionRecord) -> dict:
    """Cell-by-cell drift between a golden file and a record."""
    by_id = record.by_id()
    rows: list[dict] = []
    drift = 0
    for cid, want in sorted(golden["decisions"].items()):
        got = by_id.get(cid)
        row: dict = {"capability": cid, "expected": want, "got": None, "ok": False, "why": []}
        if got is None:
            row["why"].append("not assessed")
        else:
            row["got"] = {
                "verdict": got.verdict.value,
                "grounds": [g.value for g in got.grounds],
                "basis": sorted({c.path for c in got.citations}),
            }
            accepted = {v.strip() for v in str(want.get("verdict", "*")).split("|")}
            if "*" not in accepted and got.verdict.value not in accepted:
                row["why"].append(f"verdict {got.verdict.value} not in {sorted(accepted)}")
            want_grounds = want.get("grounds")
            if want_grounds is not None and sorted(want_grounds) != sorted(row["got"]["grounds"]):
                row["why"].append(f"grounds {row['got']['grounds']} != {sorted(want_grounds)}")
            for path in want.get("basis", []):
                if path not in row["got"]["basis"]:
                    row["why"].append(f"basis {path} not cited")
        row["ok"] = not row["why"]
        drift += 0 if row["ok"] else 1
        rows.append(row)
    extra = sorted(set(by_id) - set(golden["decisions"]))
    return {
        "assessed_by": record.assessed_by,
        "assessed_at": record.assessed_at,
        "plan_id": record.plan_id,
        "golden_reviewed": golden.get("reviewed"),
        "rows": rows,
        "drift": drift,
        "total": len(rows),
        "not_in_golden": extra,
    }


def print_table(result: dict) -> None:
    print(
        f"record {result['plan_id']} by {result['assessed_by']} ({result['assessed_at']}); "
        f"golden reviewed {result['golden_reviewed']}"
    )
    width = max((len(r["capability"]) for r in result["rows"]), default=10)
    print(f"{'capability':{width}} | expected          | got               | drift")
    for r in result["rows"]:
        exp = f"{r['expected'].get('verdict', '*')} {','.join(r['expected'].get('grounds', []) or [])}".strip()
        got = (
            "-"
            if r["got"] is None
            else f"{r['got']['verdict']} {','.join(r['got']['grounds'])}".strip()
        )
        why = "" if r["ok"] else "; ".join(r["why"])
        print(f"{r['capability']:{width}} | {exp:17} | {got:17} | {why}")
    print(
        f"{result['drift']} of {result['total']} decision(s) drifted; not in golden: {', '.join(result['not_in_golden']) or '-'}"
    )


def run_skill(fixture: Path, tool: str) -> Path:
    """Copy the fixture, install the entry skill, run the tool, return the record it wrote."""
    tmp = Path(tempfile.mkdtemp(prefix="golden-"))
    project = tmp / fixture.name
    shutil.copytree(fixture / "project", project)
    af = (
        os.environ.get("AGENT_FORGE_BIN")
        or shutil.which("agent-forge")
        or str(ROOT / ".venv" / ("Scripts" if os.name == "nt" else "bin") / "agent-forge")
    )
    subprocess.run([af, "setup", str(project)], check=True)
    if tool == "claude":
        cmd = [
            "claude",
            "-p",
            "/agent-forge-upgrade",
            "--permission-mode",
            "acceptEdits",
            "--output-format",
            "text",
        ]
    elif tool == "codex":
        cmd = ["codex", "exec", "--full-auto", "Run the agent-forge-upgrade skill on this project."]
    else:
        raise SystemExit(f"unknown tool {tool!r}")
    print("running:", " ".join(cmd), "in", project)
    subprocess.run(cmd, cwd=project, check=False)
    record = latest_record_path(project)
    if record is None:
        raise SystemExit(
            f"the skill wrote no decision record under {project / '.agent-forge' / 'decisions'}"
        )
    return record


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--golden",
        type=Path,
        help="expected_decisions.json (default: <fixture>/expected_decisions.json)",
    )
    ap.add_argument("--record", type=Path, help="decision record to compare")
    ap.add_argument("--fixture", type=Path, help="examples/<name> directory")
    ap.add_argument(
        "--run",
        action="store_true",
        help="produce the record by running the skill (costs model time)",
    )
    ap.add_argument("--tool", default="claude", choices=["claude", "codex"])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    golden_path = args.golden or (
        args.fixture / "expected_decisions.json" if args.fixture else None
    )
    if golden_path is None or not golden_path.is_file():
        ap.error("need --golden or a --fixture with expected_decisions.json")
    record_path = args.record
    if args.run:
        if args.fixture is None:
            ap.error("--run needs --fixture")
        record_path = run_skill(args.fixture, args.tool)
    if record_path is None:
        ap.error("need --record or --run")
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    result = compare(golden, load_record(record_path))
    result["record"] = str(record_path)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print_table(result)
    return 1 if result["drift"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
