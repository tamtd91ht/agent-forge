"""Review subagents (forge.agent.backend-reviewer / frontend-reviewer): one per detected part,
an existing reviewer is recognised instead of duplicated, and the entry skill knows the step."""

from __future__ import annotations

from pathlib import Path

from agent_forge.adapters import get_adapter
from agent_forge.matching.rules import MatchContext, evaluate
from agent_forge.models.capability import CapabilityKind, Platform
from agent_forge.policy.engine import load_policies
from agent_forge.registry.loader import load_registry
from agent_forge.scanner.project_profile import scan_project
from agent_forge.util import parse_frontmatter
from tests.conftest import REAL_REGISTRY, REPO_ROOT

REG = load_registry(REAL_REGISTRY)
POLICY = load_policies(REAL_REGISTRY)
BACKEND = "forge.agent.backend-reviewer"
FRONTEND = "forge.agent.frontend-reviewer"


def _verdicts(root: Path) -> dict[str, str]:
    res = evaluate(
        REG, scan_project(root), MatchContext(platforms=(Platform.CLAUDE_CODE,), policy=POLICY)
    )
    out = {c.capability.id: "recommended" for c in res.recommended}
    out.update({c.capability.id: "optional" for c in res.optional})
    out.update({r.capability.id: r.category for r in res.rejected if r.capability.id not in out})
    return out


def test_reviewers_are_read_only_agents_with_the_fixed_dimensions() -> None:
    for cid, dims in (
        (
            BACKEND,
            (
                "Security",
                "Money, inventory and transactions",
                "Data integrity",
                "Readiness for traffic",
                "API contract",
                "Correctness and clarity",
            ),
        ),
        (
            FRONTEND,
            (
                "Contract with the backend",
                "How the view loads its data",
                "State and correctness",
                "Client-side security",
                "Performance and readiness",
                "Resilience and accessibility",
                "Clarity and tests",
            ),
        ),
    ):
        lc = REG.get(cid)
        assert lc.capability.kind == CapabilityKind.AGENT and lc.capability.platforms == [
            Platform.CLAUDE_CODE
        ]
        path = lc.assets_dir / lc.capability.destinations[0].source
        text = path.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(text)
        assert fm["tools"] == "Read, Grep, Glob"  # no Bash: nothing to grant
        assert not lc.capability.permissions
        for d in dims:
            assert f"### {dims.index(d) + 1}. {d}" in body, (cid, d)
        flat = " ".join(body.split())
        assert "Not checked:" in flat and "Never claim a check you did not perform" in flat
        assert (
            get_adapter(Platform.CLAUDE_CODE).validate_content(
                CapabilityKind.AGENT, lc.capability.destinations[0].dest, text
            )
            == []
        )


def test_one_reviewer_per_detected_part() -> None:
    backend_only = _verdicts(REPO_ROOT / "examples" / "java-spring" / "project")
    assert backend_only[BACKEND] == "recommended" and backend_only[FRONTEND] == "not_applicable"
    web = _verdicts(REPO_ROOT / "examples" / "nextjs-ts" / "project")
    # Next.js is typed fullstack (API routes), so both reviewers apply there
    assert web[FRONTEND] == "recommended" and web[BACKEND] == "recommended"
    both = _verdicts(REPO_ROOT / "examples" / "mixed-monorepo" / "project")
    assert both[BACKEND] == "recommended" and both[FRONTEND] == "recommended"


def test_an_existing_reviewer_subagent_is_recognised_not_duplicated(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='api'\nversion='0'\ndependencies=['fastapi']\n", encoding="utf-8"
    )
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("x = 1\n", encoding="utf-8")
    agents = tmp_path / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "api-reviewer.md").write_text(
        "---\nname: api-reviewer\ndescription: Reviews our API changes\ntools: Read, Grep\n---\n\n"
        "Check every endpoint for authorization, idempotent money operations and N+1 queries.\n",
        encoding="utf-8",
    )
    got = _verdicts(tmp_path)
    assert got[BACKEND] == "equivalent_exists", got[
        BACKEND
    ]  # the skill opens it and judges coverage


def test_entry_skill_carries_the_review_coverage_step() -> None:
    skill = (
        REAL_REGISTRY
        / "capabilities/forge.skill.agent-forge-upgrade/assets/claude_code/agent-forge-upgrade/SKILL.md"
    ).read_text(encoding="utf-8")
    assert "**Review coverage.**" in skill
    assert BACKEND in skill and FRONTEND in skill
    assert "SKIP as `covered`" in skill and "ASK: name the missing dimensions" in skill
