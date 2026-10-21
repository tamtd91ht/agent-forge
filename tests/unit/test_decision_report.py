"""scripts/decision_report.py: golden decisions compared cell by cell (no model run)."""

from __future__ import annotations

import importlib.util
import json

from agent_forge.models.decision import DecisionRecord
from tests.conftest import REPO_ROOT

_spec = importlib.util.spec_from_file_location(
    "decision_report", REPO_ROOT / "scripts" / "decision_report.py"
)
report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(report)  # type: ignore[union-attr]

GOLDEN = json.loads(
    (REPO_ROOT / "examples" / "lint-messy" / "expected_decisions.json").read_text(encoding="utf-8")
)


def _record(decisions: list[dict]) -> DecisionRecord:
    return DecisionRecord.model_validate(
        {
            "plan_id": "plan-golden",
            "assessed_by": "pytest",
            "assessed_at": "2026-10-21",
            "decisions": [{"confidence": "high", **d} for d in decisions],
        }
    )


def test_golden_file_covers_the_fixtures_designed_traps() -> None:
    d = GOLDEN["decisions"]
    assert d["ecc.tdd-workflow"]["basis"] == [".claude/rules/testing.md"]
    assert d["forge.hook.guard-secrets-python"]["verdict"] == "ASK"
    assert "|" in d["ecc.verification-loop"]["verdict"]  # judgement calls accept both


def test_compare_reports_only_the_cells_that_drift() -> None:
    rec = _record(
        [
            {
                "capability_id": "ecc.tdd-workflow",
                "verdict": "SKIP",
                "grounds": ["covered"],
                "covered_by": [{"path": ".claude/rules/testing.md", "quote": "failing test first"}],
            },
            {
                "capability_id": "ecc.security-review",
                "verdict": "ADD",
                "gap": "none",
            },  # drift: verdict
            {"capability_id": "ecc.verification-loop", "verdict": "ASK"},  # drift: basis missing
            {"capability_id": "forge.hook.guard-secrets-python", "verdict": "ASK"},
            {"capability_id": "mcp.context7", "verdict": "ASK"},
            {"capability_id": "forge.managed-notice", "verdict": "ASK"},
            {"capability_id": "karpathy.principles", "verdict": "ASK"},
            {
                "capability_id": "mattpocock.diagnosing-bugs",
                "verdict": "ADD",
                "gap": "no debugging routine",
            },
            {
                "capability_id": "ecc.error-handling",
                "verdict": "SKIP",
                "grounds": ["covered"],
                "covered_by": [{"path": "CLAUDE.md", "quote": "x"}],
            },
            {"capability_id": "ecc.agent.planner", "verdict": "ADD"},
            {"capability_id": "ecc.coding-standards", "verdict": "ADD"},
            {
                "capability_id": "forge.hook.python-ruff-format",
                "verdict": "SKIP",
                "grounds": ["duplicate_tool"],
                "covered_by": [{"path": ".claude/settings.json", "quote": "ruff format"}],
            },
            {
                "capability_id": "uiux.guidelines",
                "verdict": "SKIP",
                "grounds": ["stack_mismatch"],
            },  # not in golden
        ]
    )
    result = report.compare(GOLDEN, rec)
    rows = {r["capability"]: r for r in result["rows"]}
    assert result["total"] == len(GOLDEN["decisions"])
    assert result["drift"] == 2
    assert (
        not rows["ecc.security-review"]["ok"]
        and "verdict ADD" in rows["ecc.security-review"]["why"][0]
    )
    assert (
        not rows["ecc.verification-loop"]["ok"]
        and "basis CLAUDE.md not cited" in rows["ecc.verification-loop"]["why"]
    )
    assert rows["ecc.tdd-workflow"]["ok"] and rows["forge.hook.python-ruff-format"]["ok"]
    assert result["not_in_golden"] == ["uiux.guidelines"]
    # an unassessed capability is drift too
    partial = report.compare(GOLDEN, _record([{"capability_id": "mcp.context7", "verdict": "ASK"}]))
    assert partial["drift"] == partial["total"] - 1
    assert (
        "not assessed"
        in next(r for r in partial["rows"] if r["capability"] == "ecc.tdd-workflow")["why"]
    )
