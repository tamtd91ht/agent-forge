"""Evaluation harness (tools/agent-forge-eval): task loading, the run matrix with a scripted
agent, statistics and the report. No LLM is launched."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml
from agent_forge_eval import cli
from agent_forge_eval.harness import Arm, load_tasks, run_matrix, scripted_runner
from agent_forge_eval.stats import compare, summarise, to_markdown, wilson
from tests.conftest import REPO_ROOT, unwrap

EXAMPLES = REPO_ROOT / "examples"
FIXTURES = sorted(p for p in EXAMPLES.iterdir() if (p / "project").is_dir())


def test_every_fixture_ships_reviewed_tasks() -> None:
    for fixture in FIXTURES:
        tasks = load_tasks(fixture)
        assert len(tasks) >= 5, f"{fixture.name}: {len(tasks)} task(s), need 5"
        assert len({t.category for t in tasks}) >= 2, f"{fixture.name}: one category only"
        for t in tasks:
            assert t.acceptance_files, f"{fixture.name}/{t.id}: acceptance needs hidden files"
            assert t.prompt and t.acceptance_command


def test_task_validation_rejects_bad_files(tmp_path: Path) -> None:
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "x.yaml").write_text(
        yaml.safe_dump(
            {"id": "y", "category": "feature", "prompt": "p", "acceptance": {"command": "true"}}
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must equal the file name"):
        load_tasks(tmp_path)
    (tmp_path / "tasks" / "x.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "x",
                "category": "feature",
                "prompt": "p",
                "acceptance": {"command": "true", "files": {"../o": "x"}},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsafe path"):
        load_tasks(tmp_path)


def _fixture(tmp_path: Path) -> Path:
    fx = tmp_path / "fx"
    (fx / "project" / "app").mkdir(parents=True)
    (fx / "project" / "app" / "calc.py").write_text(
        "def add(a, b):\n    return a - b\n", encoding="utf-8"
    )
    (fx / "tasks").mkdir()
    (fx / "tasks" / "fix-add.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "fix-add",
                "category": "bugfix",
                "prompt": "add() subtracts; fix it",
                "acceptance": {
                    "files": {
                        "test_calc.py": "from app.calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"
                    },
                    "command": f'"{sys.executable}" -m pytest -q test_calc.py',
                },
                "budget_seconds": 60,
            }
        ),
        encoding="utf-8",
    )
    return fx


def test_run_matrix_with_a_scripted_agent(tmp_path: Path, real_workspace) -> None:
    fx = _fixture(tmp_path)
    tasks = load_tasks(fx)

    def fixer(project: Path, prompt: str) -> int:
        # the "candidate" copy carries an installed capability; the fake agent only fixes
        # the bug when it sees it, so the two arms differ
        if (project / ".agent-forge" / "managed.json").exists():
            (project / "app" / "calc.py").write_text(
                "def add(a, b):\n    return a + b\n", encoding="utf-8"
            )
        return 0

    af = [str(REPO_ROOT / ".venv" / "Scripts" / "agent-forge.exe")]
    if not Path(af[0]).is_file():
        af = [str(REPO_ROOT / ".venv" / "bin" / "agent-forge")]
    records = run_matrix(
        fx,
        tasks,
        [Arm("baseline", None), Arm("candidate", "ecc.tdd-workflow")],
        scripted_runner(fixer),
        runs=2,
        agent_forge=af,
        workspace=real_workspace.root,
    )
    assert len(records) == 4
    by_arm = {}
    for r in records:
        by_arm.setdefault(r.arm, []).append(r.passed)
    assert by_arm["baseline"] == [False, False] and by_arm["candidate"] == [True, True]
    assert all(r.changed_files >= 0 for r in records)
    summary = summarise(records)
    assert summary["arms"]["candidate"]["pass_rate"] == 1.0
    assert summary["verdict"]["status"] == "improved"
    md = to_markdown(
        {"capability": "ecc.tdd-workflow", "fixture": "fx", "runs": 2, "tasks": ["fix-add"]},
        summary,
    )
    assert "| candidate | 2 | 1.0 |" in md and "improved" in md


def test_wilson_and_compare_are_honest_about_small_samples() -> None:
    rate, lo, hi = wilson(3, 3)
    assert rate == 1.0 and lo < 0.5 and hi == 1.0  # three of three is not certainty
    assert wilson(0, 0) == (0.0, 0.0, 0.0)
    base = {"pass_rate": 0.5, "ci95": [0.2, 0.8]}
    assert compare(base, {"pass_rate": 0.67, "ci95": [0.3, 0.9]})["status"] == "no_evidence"
    assert compare(base, {"pass_rate": 0.9, "ci95": [0.6, 1.0]})["status"] == "improved"
    assert compare(base, {"pass_rate": 0.1, "ci95": [0.0, 0.4]})["status"] == "worse"
    assert compare(None, base)["status"] == "incomplete"


def test_cli_run_scripted_writes_report(tmp_path: Path, real_workspace, capsys) -> None:
    fx = _fixture(tmp_path)
    af = REPO_ROOT / ".venv" / "Scripts" / "agent-forge.exe"
    if not af.is_file():
        af = REPO_ROOT / ".venv" / "bin" / "agent-forge"
    out = tmp_path / "results"
    code = cli.main(
        [
            "run",
            "--fixture",
            str(fx),
            "--capability",
            "ecc.tdd-workflow",
            "--tool",
            "scripted",
            "--runs",
            "1",
            "--arm",
            "baseline",
            "--agent-forge",
            str(af),
            "--workspace",
            str(real_workspace.root),
            "--out",
            str(out),
        ]
    )
    assert code == 0
    files = sorted(out.iterdir())
    assert [f.suffix for f in files] == [".json", ".md"]
    doc = unwrap(files[0].read_text(encoding="utf-8"))
    assert doc["meta"]["tool"].startswith("scripted") and "NOT a measurement" in doc["meta"]["tool"]
    assert doc["summary"]["verdict"]["status"] == "incomplete"
    assert cli.main(["tasks", "--fixture", str(fx)]) == 0
    assert "fix-add" in capsys.readouterr().out
