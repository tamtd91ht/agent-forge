"""Phase 3: evaluation evidence in manifests, and the plan-level always-loaded context budget."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from agent_forge.cli import app
from agent_forge.matching.rules import MatchContext
from agent_forge.models.capability import Capability, EvaluationEvidence, Platform
from agent_forge.planner import build_assign_plan
from agent_forge.policy.engine import load_policies
from agent_forge.registry.loader import load_registry
from agent_forge.scanner.project_profile import scan_project
from tests.conftest import base_manifest, write_capability

runner = CliRunner()

EVIDENCE = {
    "date": "2026-11-15",
    "fixture": "python-fastapi",
    "tool": "claude 2.1.304",
    "runs": 3,
    "tasks": 5,
    "baseline_pass_rate": 0.4,
    "candidate_pass_rate": 0.8,
    "candidate_ci95": [0.55, 0.93],
    "verdict": "improved",
    "report": "docs/evaluation/results/20261115-ecc.tdd-workflow-python-fastapi.md",
    "decided_by": "tech-lead",
}


def test_evidence_is_validated_and_optional() -> None:
    cap = Capability.model_validate(
        base_manifest("t.ev", review={**base_manifest("t.ev")["review"], "evidence": [EVIDENCE]})
    )
    assert cap.review.evidence[0].verdict == "improved"
    assert Capability.model_validate(base_manifest("t.none")).review.evidence == []
    with pytest.raises(ValidationError):
        EvaluationEvidence.model_validate({**EVIDENCE, "candidate_ci95": [0.9, 0.5]})
    with pytest.raises(ValidationError):
        EvaluationEvidence.model_validate({**EVIDENCE, "verdict": "great"})
    with pytest.raises(ValidationError):
        EvaluationEvidence.model_validate({**EVIDENCE, "extra": 1})


def test_catalog_show_displays_evidence_or_says_none(
    tmp_path: Path, synthetic_registry: Path, workspace
) -> None:
    write_capability(
        synthetic_registry,
        base_manifest("t.ev", review={**base_manifest("t.ev")["review"], "evidence": [EVIDENCE]}),
        {
            "claude_code/ev/SKILL.md": "---\nname: ev\ndescription: d\n---\nbody\n",
            "codex/ev/SKILL.md": "---\nname: ev\ndescription: d\n---\nbody\n",
        },
    )
    ws = str(workspace.root)
    out = runner.invoke(app, ["catalog", "show", "t.ev", "--workspace", ws], catch_exceptions=False)
    assert out.exit_code == 0 and "evaluation evid" in out.output  # table title (80-col runner)
    out = runner.invoke(
        app, ["catalog", "show", "t.always", "--workspace", ws], catch_exceptions=False
    )
    assert "none (value not measured" in out.output
    data = json.loads(
        runner.invoke(app, ["catalog", "show", "t.ev", "--workspace", ws, "--json"]).stdout
    )
    assert data["review"]["evidence"][0]["decided_by"] == "tech-lead"


def test_total_context_budget_becomes_a_decision(synthetic_registry: Path, make_project) -> None:
    root = make_project("budget", kind="claude")
    (root / ".agent-forge").mkdir()
    (root / ".agent-forge" / "policy.yaml").write_text(
        yaml.safe_dump({"name": "tight", "max_total_context_chars": 1}), encoding="utf-8"
    )
    reg = load_registry(synthetic_registry)
    profile = scan_project(root)
    ctx = MatchContext(
        platforms=(Platform.CLAUDE_CODE,), policy=load_policies(synthetic_registry, None, root)
    )
    assert ctx.policy is not None and ctx.policy.total_context_budget == 1
    plan, _ = build_assign_plan(reg, profile, ctx)
    assert plan.selected, "fixture must select something"
    assert any("max_total_context_chars=1" in n for n in plan.notes)
    assert any("exceeds the policy budget" in d for d in plan.user_decisions)
    # without a budget nothing is said
    ctx2 = MatchContext(
        platforms=(Platform.CLAUDE_CODE,), policy=load_policies(synthetic_registry, None, None)
    )
    plan2, _ = build_assign_plan(reg, scan_project(root), ctx2)
    assert not any("max_total_context_chars" in n for n in plan2.notes)
