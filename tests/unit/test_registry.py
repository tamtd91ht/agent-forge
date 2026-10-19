from __future__ import annotations

from pathlib import Path

import pytest

from agent_forge.errors import RegistryError
from agent_forge.registry.loader import load_registry
from agent_forge.registry.validator import resolve_dependencies, validate_registry
from tests.conftest import REAL_REGISTRY, base_manifest, skill_assets, write_capability


def test_synthetic_registry_loads_and_validates(synthetic_registry: Path) -> None:
    reg = load_registry(synthetic_registry)
    assert "t.always" in reg.items
    rep = validate_registry(reg)
    assert rep.ok, rep.errors
    assert len(reg.digest) == 64


def test_real_registry_is_valid() -> None:
    reg = load_registry(REAL_REGISTRY)
    assert len(reg.items) >= 10
    rep = validate_registry(reg)
    assert rep.ok, rep.errors
    for cap in reg.curated():
        if cap.source.source_id != "workspace":
            assert cap.source.revision and len(cap.source.revision) == 40


def test_registry_digest_changes_with_content(synthetic_registry: Path) -> None:
    before = load_registry(synthetic_registry).digest
    p = (
        synthetic_registry
        / "capabilities"
        / "t.always"
        / "assets"
        / "claude_code"
        / "always"
        / "SKILL.md"
    )
    p.write_text(p.read_text(encoding="utf-8") + "\nmore\n", encoding="utf-8")
    assert load_registry(synthetic_registry).digest != before


def test_directory_name_must_match_id(tmp_path: Path) -> None:
    reg = tmp_path / "r"
    d = write_capability(reg, base_manifest("t.a"), skill_assets("a"))
    d.rename(d.parent / "t.b")
    with pytest.raises(RegistryError, match="must match its directory"):
        load_registry(reg)
    lenient = load_registry(reg, strict=False)
    assert lenient.problems and not lenient.items


def test_cross_checks_detect_missing_assets_and_deps(tmp_path: Path) -> None:
    reg = tmp_path / "r"
    write_capability(reg, base_manifest("t.a", dependencies=["t.missing"]))  # no assets
    rep = validate_registry(load_registry(reg))
    assert any("dependency 't.missing'" in e for e in rep.errors)
    assert any("assets directory missing" in e for e in rep.errors)


def test_dependency_cycle_detected(tmp_path: Path) -> None:
    reg = tmp_path / "r"
    write_capability(reg, base_manifest("t.a", dependencies=["t.b"]), skill_assets("a"))
    write_capability(reg, base_manifest("t.b", dependencies=["t.a"]), skill_assets("b"))
    rep = validate_registry(load_registry(reg))
    assert any("cycle" in e for e in rep.errors)


def test_resolve_dependencies_orders_deps_first(synthetic_registry: Path) -> None:
    reg = load_registry(synthetic_registry)
    order = resolve_dependencies(reg, ["t.needs-always"])
    assert order.index("t.always") < order.index("t.needs-always")


def test_broken_relative_markdown_links_are_errors(tmp_path: Path) -> None:
    reg = tmp_path / "r"
    body = (
        "See [ok](other.md), [anchor](#top), [web](https://example.com), "
        "[sub](other.md#part) and [gone](./missing.md).\n\n"
        "```markdown\n[example](not-checked.md)\n```\n"
    )
    assets = skill_assets("links", body)
    assets["claude_code/links/other.md"] = "# other\n"
    assets["codex/links/other.md"] = "# other\n"
    write_capability(reg, base_manifest("t.links"), assets)
    rep = validate_registry(load_registry(reg))
    broken = [e for e in rep.errors if "broken link" in e]
    assert broken == [
        "t.links: broken link in assets/claude_code/links/SKILL.md: ./missing.md",
        "t.links: broken link in assets/codex/links/SKILL.md: ./missing.md",
    ]


@pytest.mark.parametrize("name", ["agent-forge-upgrade", "agent-forge-scout"])
def test_repo_copy_of_meta_skill_matches_registry(name: str) -> None:
    # these skills are shipped twice on purpose (registry asset + the repo's own .claude/skills)
    asset = REAL_REGISTRY / f"capabilities/forge.skill.{name}/assets/claude_code/{name}/SKILL.md"
    repo_copy = REAL_REGISTRY.parent / f".claude/skills/{name}/SKILL.md"
    assert repo_copy.read_text(encoding="utf-8") == asset.read_text(encoding="utf-8")
