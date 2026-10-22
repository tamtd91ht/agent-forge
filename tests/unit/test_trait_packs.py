"""Trait-gated capabilities (ADR-0010): proposed only to a project that shows the trait,
with the scanner's evidence; identical on-demand content for every platform."""

from __future__ import annotations

from pathlib import Path

from agent_forge.matching.rules import MatchContext, evaluate
from agent_forge.models.capability import CapabilityKind, Platform
from agent_forge.policy.engine import load_policies
from agent_forge.registry.context_load import context_chars
from agent_forge.registry.loader import load_registry
from agent_forge.scanner.project_profile import TRAIT_NAMES, scan_project
from agent_forge.util import parse_frontmatter
from tests.conftest import REAL_REGISTRY

REG = load_registry(REAL_REGISTRY)
POLICY = load_policies(REAL_REGISTRY)
PACKS = {
    "forge.skill.tenant-isolation": "multi_tenant",
    "forge.skill.money-safety": "money",
    "forge.skill.event-consumer-safety": "event_driven",
    "forge.skill.event-contract": "event_driven",
}


def _verdicts(root: Path) -> dict[str, str]:
    res = evaluate(
        REG, scan_project(root), MatchContext(platforms=(Platform.CLAUDE_CODE,), policy=POLICY)
    )
    out = {c.capability.id: "recommended" for c in res.recommended}
    out.update({c.capability.id: "optional" for c in res.optional})
    out.update({r.capability.id: r.category for r in res.rejected if r.capability.id not in out})
    return out


def test_every_trait_gated_capability_names_a_known_trait() -> None:
    gated = {
        lc.capability.id: lc.capability.applicability.traits
        for lc in REG.items.values()
        if lc.capability.applicability.traits
    }
    assert set(PACKS) <= set(gated)
    for cid, traits in gated.items():
        assert set(traits) <= set(TRAIT_NAMES), (cid, traits)
        assert not REG.get(cid).capability.applicability.always, cid


def test_packs_are_on_demand_skills_with_identical_codex_copies() -> None:
    for cid in PACKS:
        lc = REG.get(cid)
        assert lc.capability.kind == CapabilityKind.SKILL
        assert Platform.CODEX in lc.capability.platforms
        claude = (
            lc.directory
            / "assets"
            / lc.capability.destinations_for(Platform.CLAUDE_CODE)[0].source
            / "SKILL.md"
        ).read_bytes()
        codex = (
            lc.directory
            / "assets"
            / lc.capability.destinations_for(Platform.CODEX)[0].source
            / "SKILL.md"
        ).read_bytes()
        assert claude == codex, cid
        fm, _ = parse_frontmatter(claude.decode("utf-8"))
        assert fm["name"] == cid.rsplit(".", 1)[-1]
        # name + description only: the body is loaded on demand
        assert context_chars(lc, Platform.CLAUDE_CODE) == len(fm["name"]) + len(fm["description"])


def test_packs_stay_out_of_a_project_without_the_trait(make_project) -> None:
    verdicts = _verdicts(make_project("plain"))
    for cid in PACKS:
        assert verdicts[cid] == "not_applicable", (cid, verdicts[cid])


def test_packs_are_proposed_when_the_source_shows_the_trait(make_project) -> None:
    src = {f"src/orders/m{i}.py": "def f(tenant_id):\n    return tenant_id\n" for i in range(4)}
    src.update(
        {f"src/billing/w{i}.py": "class Wallet:\n    def refund(self): ...\n" for i in range(2)}
    )
    verdicts = _verdicts(make_project("saas", files=src))
    assert verdicts["forge.skill.tenant-isolation"] == "recommended"
    assert verdicts["forge.skill.money-safety"] == "recommended"


def test_event_pack_follows_a_broker_dependency(make_project) -> None:
    verdicts = _verdicts(
        make_project(
            "broker",
            files={
                "pyproject.toml": (
                    "[project]\nname='x'\nversion='0'\ndependencies=['pytest','aiokafka']\n"
                )
            },
        )
    )
    assert verdicts["forge.skill.event-consumer-safety"] == "recommended"
    assert verdicts["forge.skill.event-contract"] == "recommended"
    assert verdicts["forge.skill.tenant-isolation"] == "not_applicable"


def test_a_confirmed_trait_is_enough(make_project) -> None:
    verdicts = _verdicts(
        make_project("confirmed", files={".agent-forge/profile.yaml": "traits: [money]\n"})
    )
    assert verdicts["forge.skill.money-safety"] == "recommended"
    assert verdicts["forge.skill.tenant-isolation"] == "not_applicable"
