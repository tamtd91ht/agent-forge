from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_forge.errors import WorkspaceError
from agent_forge.matching.rules import MatchContext, evaluate
from agent_forge.models.capability import Capability, Platform
from agent_forge.policy.engine import Decision, Policy, PolicySet, load_policies
from agent_forge.registry.loader import load_registry
from agent_forge.scanner.project_profile import scan_project
from tests.conftest import REAL_REGISTRY, base_manifest


def _cap(**over) -> Capability:
    return Capability.model_validate(base_manifest("t.x", **over))


def test_default_policy_allows_plain_skill() -> None:
    ps = load_policies(REAL_REGISTRY)
    assert ps.names == ["default"]
    d, why = ps.evaluate(_cap(), Platform.CLAUDE_CODE)
    assert d == Decision.ALLOW and why == []


def test_risk_thresholds() -> None:
    ps = PolicySet([("t", Policy(max_risk="medium", require_request_from_risk="medium"))])
    assert ps.evaluate(_cap(risk="low"), Platform.CLAUDE_CODE)[0] == Decision.ALLOW
    assert ps.evaluate(_cap(risk="medium"), Platform.CLAUDE_CODE)[0] == Decision.REQUIRE_REQUEST
    assert ps.evaluate(_cap(risk="high"), Platform.CLAUDE_CODE)[0] == Decision.DENY


def test_strictest_layer_wins_and_cannot_be_loosened() -> None:
    loose = Policy(name="ws", max_risk="high")
    strict = Policy(name="project", capabilities={"deny": ["t.*"]})
    ps = PolicySet([("ws", loose), ("project", strict)])
    d, why = ps.evaluate(_cap(), Platform.CLAUDE_CODE)
    assert d == Decision.DENY and any("[project]" in w for w in why)
    # reversed order gives the same result: layering is monotone
    assert (
        PolicySet([("project", strict), ("ws", loose)]).evaluate(_cap(), Platform.CLAUDE_CODE)[0]
        == Decision.DENY
    )


def test_grants_derived_from_kind_feed_policy() -> None:
    hook = _cap(
        kind="hook",
        platforms=["claude_code"],
        destinations=[
            {
                "platform": "claude_code",
                "source": "h.json",
                "dest": ".claude/settings.json",
                "merge": "json_merge",
                "section_id": "h",
            }
        ],
    )
    assert hook.effective_grants.process_execute
    ps = PolicySet([("t", Policy(grants={"process_execute": "deny"}))])
    assert ps.evaluate(hook, Platform.CLAUDE_CODE)[0] == Decision.DENY
    ps = PolicySet([("t", Policy(classes={"hook": "deny"}))])
    assert ps.evaluate(hook, Platform.CLAUDE_CODE)[0] == Decision.DENY
    assert ps.evaluate(_cap(), Platform.CLAUDE_CODE)[0] == Decision.ALLOW


def test_platform_and_signoff_rules() -> None:
    ps = PolicySet([("t", Policy(platforms=["codex"]))])
    assert ps.evaluate(_cap(), Platform.CLAUDE_CODE)[0] == Decision.DENY
    assert ps.evaluate(_cap(), Platform.CODEX)[0] == Decision.ALLOW
    ps = PolicySet([("t", Policy(require_signoff=True))])
    assert ps.evaluate(_cap(), Platform.CLAUDE_CODE)[0] == Decision.DENY
    signed = _cap(
        review={
            "reviewed_at": "2026-10-16",
            "reviewer": "x",
            "rationale": "y",
            "signed_off_by": "lead",
        }
    )
    assert ps.evaluate(signed, Platform.CLAUDE_CODE)[0] == Decision.ALLOW


def test_project_policy_layer_is_loaded_and_only_tightens(tmp_path: Path, make_project) -> None:
    root = make_project("pol")
    (root / ".agent-forge").mkdir()
    (root / ".agent-forge" / "policy.yaml").write_text(
        yaml.safe_dump(
            {"name": "proj", "capabilities": {"deny": ["t.python-only"]}, "max_risk": "high"}
        ),
        encoding="utf-8",
    )
    ps = load_policies(REAL_REGISTRY, None, root)
    assert ps.names == ["default", "project"]
    assert ps.evaluate(_cap(id="t.python-only"), Platform.CLAUDE_CODE)[0] == Decision.DENY


def test_invalid_project_policy_fails_closed(make_project) -> None:
    root = make_project("pol-invalid")
    (root / ".agent-forge").mkdir()
    # meant to deny something, but malformed: ignoring it would silently loosen policy
    (root / ".agent-forge" / "policy.yaml").write_text(
        "capabilities: {deny: t.always}\nmax_risk: [not valid]\n", encoding="utf-8"
    )
    with pytest.raises(WorkspaceError, match="invalid policy") as exc:
        load_policies(REAL_REGISTRY, None, root)
    assert "nothing is planned" in (exc.value.hint or "")


def test_policy_digest_tracks_every_layer(make_project) -> None:
    root = make_project("pol-digest")
    before = load_policies(REAL_REGISTRY, None, root).digest
    (root / ".agent-forge").mkdir()
    (root / ".agent-forge" / "policy.yaml").write_text(
        yaml.safe_dump({"capabilities": {"deny": ["t.*"]}}), encoding="utf-8"
    )
    assert load_policies(REAL_REGISTRY, None, root).digest != before


def test_unknown_policy_keys_rejected(tmp_path: Path) -> None:
    reg = tmp_path / "reg"
    (reg / "policies").mkdir(parents=True)
    (reg / "policies" / "default.yaml").write_text("bogus: 1\n", encoding="utf-8")
    with pytest.raises(WorkspaceError, match="invalid policy"):
        load_policies(reg)


def test_matching_honours_policy(synthetic_registry: Path, make_project) -> None:
    reg = load_registry(synthetic_registry)
    profile = scan_project(make_project("mp"))
    ps = PolicySet(
        [("t", Policy(capabilities={"deny": ["t.always"], "require_request": ["t.python-only"]}))]
    )
    res = evaluate(reg, profile, MatchContext(platforms=(Platform.CLAUDE_CODE,), policy=ps))
    rej = {r.capability.id: r.category for r in res.rejected}
    assert rej["t.always"] == "policy_denied"
    assert rej["t.python-only"] == "policy_requires_request"
    assert rej["t.needs-always"] == "dependency_missing"  # its dependency was denied
    res2 = evaluate(
        reg,
        profile,
        MatchContext(
            platforms=(Platform.CLAUDE_CODE,), policy=ps, requested_ids=frozenset({"t.python-only"})
        ),
    )
    assert "t.python-only" in {c.capability.id for c in res2.recommended}


def test_context_budget_requires_request_above_limit() -> None:
    ps = PolicySet([("t", Policy(max_context_chars=500))])
    assert ps.evaluate(_cap(), Platform.CLAUDE_CODE, 500)[0] == Decision.ALLOW
    d, why = ps.evaluate(_cap(), Platform.CLAUDE_CODE, 501)
    assert d == Decision.REQUIRE_REQUEST and "501 always-loaded context chars" in why[0]
    # without a measured value the budget does not apply
    assert ps.evaluate(_cap(), Platform.CLAUDE_CODE)[0] == Decision.ALLOW


def test_matching_applies_context_budget(synthetic_registry: Path, make_project) -> None:
    reg = load_registry(synthetic_registry)
    profile = scan_project(make_project("mp"))
    ps = PolicySet([("t", Policy(max_context_chars=0))])
    res = evaluate(reg, profile, MatchContext(platforms=(Platform.CLAUDE_CODE,), policy=ps))
    rej = {r.capability.id: r.category for r in res.rejected}
    assert rej["t.always"] == "policy_requires_request"
