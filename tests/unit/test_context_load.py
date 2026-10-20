from __future__ import annotations

from pathlib import Path

from agent_forge.models.capability import Platform
from agent_forge.registry.context_load import context_chars
from agent_forge.registry.loader import load_registry
from tests.conftest import base_manifest, skill_assets, write_capability


def _lc(tmp_path: Path, manifest: dict, assets: dict[str, str]):
    write_capability(tmp_path / "r", manifest, assets)
    return load_registry(tmp_path / "r").get(manifest["id"])


def test_model_invoked_skill_costs_its_name_and_description(tmp_path: Path) -> None:
    lc = _lc(tmp_path, base_manifest("t.s"), skill_assets("s", "long body " * 200))
    # "s" + "s skill for tests": the body and reference files are loaded on demand
    assert context_chars(lc, Platform.CLAUDE_CODE) == 1 + len("s skill for tests")


def test_user_invoked_skill_costs_nothing(tmp_path: Path) -> None:
    assets = {
        k: v.replace("---\n\n", "disable-model-invocation: true\n---\n\n")
        for k, v in skill_assets("m").items()
    }
    assert context_chars(_lc(tmp_path, base_manifest("t.m"), assets), Platform.CODEX) == 0


def test_sections_and_unscoped_rules_cost_their_full_text(tmp_path: Path) -> None:
    section = base_manifest(
        "t.sec",
        install_strategy="section_merge",
        platforms=["claude_code"],
        destinations=[
            {
                "platform": "claude_code",
                "source": "claude_code/s.md",
                "dest": "CLAUDE.md",
                "merge": "append_section",
                "section_id": "sec",
            }
        ],
    )
    lc = _lc(tmp_path, section, {"claude_code/s.md": "x" * 40})
    assert context_chars(lc, Platform.CLAUDE_CODE) == 40

    rules = base_manifest(
        "t.rules",
        kind="rule",
        platforms=["claude_code"],
        destinations=[
            {"platform": "claude_code", "source": "claude_code/r", "dest": ".claude/rules/r"}
        ],
    )
    assets = {
        "claude_code/r/always.md": "# Always\nbody\n",
        "claude_code/r/scoped.md": "---\npaths: ['src/**']\n---\n# Scoped\nbody\n",
        "claude_code/r/LICENSE.txt": "MIT",
    }
    lc = _lc(tmp_path, rules, assets)
    assert context_chars(lc, Platform.CLAUDE_CODE) == len("# Always\nbody")
