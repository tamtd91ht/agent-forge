"""The shipped team policy template is valid and tightens the defaults as documented."""

from __future__ import annotations

from pathlib import Path

import yaml

from agent_forge.models.capability import Platform, RiskLevel
from agent_forge.policy.engine import Policy, load_policies
from agent_forge.registry.loader import load_registry
from tests.conftest import REAL_REGISTRY, REPO_ROOT

TEMPLATE = REPO_ROOT / "examples" / "policy" / "team-default.yaml"


def test_team_default_policy_template_is_valid_and_strict(tmp_path: Path) -> None:
    pol = Policy.model_validate(yaml.safe_load(TEMPLATE.read_text(encoding="utf-8")))
    assert pol.name == "team-default"
    assert pol.max_risk == RiskLevel.MEDIUM and pol.classes.mcp == "deny"
    assert pol.max_context_chars == 4000

    project = tmp_path / "proj"
    (project / ".agent-forge").mkdir(parents=True)
    (project / ".agent-forge" / "policy.yaml").write_bytes(TEMPLATE.read_bytes())
    ps = load_policies(REAL_REGISTRY, None, project)
    assert ps.names == ["default", "project"]  # layer names come from where the file sits
    reg = load_registry(REAL_REGISTRY)
    mcp = reg.get("mcp.context7").capability
    decision, reasons = ps.evaluate(mcp, Platform.CLAUDE_CODE)
    assert decision.value == "deny" and any(r.startswith("[project]") for r in reasons)
    rea = reg.get("rea.reverse-engineer-anything").capability
    assert ps.evaluate(rea, Platform.CLAUDE_CODE)[0].value in ("require_request", "deny")
    assert (
        ps.evaluate(reg.get("ecc.tdd-workflow").capability, Platform.CLAUDE_CODE)[0].value
        == "allow"
    )
