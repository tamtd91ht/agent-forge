"""The entry skill pays its own context budget: zero always-loaded, bounded on demand
(ADR-0007 rubric, fix list phase 3)."""

from __future__ import annotations

from agent_forge.models.capability import Platform
from agent_forge.registry.context_load import context_chars
from agent_forge.registry.loader import load_registry
from agent_forge.util import parse_frontmatter
from tests.conftest import REAL_REGISTRY

SKILL_ID = "forge.skill.agent-forge-upgrade"
MAX_ON_DEMAND_CHARS = 16_000


def test_entry_skill_costs_no_always_loaded_context_and_stays_bounded() -> None:
    lc = load_registry(REAL_REGISTRY).get(SKILL_ID)
    for platform in (Platform.CLAUDE_CODE, Platform.CODEX):
        assert context_chars(lc, platform) == 0, platform
    skill = (lc.assets_dir / "claude_code" / "agent-forge-upgrade" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    fm, body = parse_frontmatter(skill)
    assert fm.get("disable-model-invocation") is True
    assert len(skill) < MAX_ON_DEMAND_CHARS, len(skill)
    # the rubric is complete: eight grounds, five verdicts, the record fields
    for ground in (
        "covered",
        "conflicts",
        "security",
        "context_cost",
        "stack_mismatch",
        "evidence_worse",
        "duplicate_tool",
        "unused",
    ):
        assert f"`{ground}`" in body, ground
    for verdict in ("ADD", "SKIP", "UPGRADE", "REMOVE", "ASK"):
        assert f"**{verdict}**" in body, verdict
    for field in ('"scope"', '"grounds"', '"covered_by"', '"confidence"', '"assessed_by"'):
        assert field in body, field
    assert "decisions verify" in body and "--decisions" in body
    codex = (lc.assets_dir / "codex" / "agent-forge-upgrade" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert codex == skill
