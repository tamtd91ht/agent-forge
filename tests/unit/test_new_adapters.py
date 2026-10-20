"""Cursor, GitHub Copilot and Gemini CLI adapters: detection, inventory, content rules."""

from __future__ import annotations

import json
from pathlib import Path

from agent_forge.adapters import get_adapter, platform_owning
from agent_forge.models.capability import CapabilityKind, Platform
from agent_forge.scanner.filesystem import Walker
from agent_forge.scanner.project_profile import scan_project


def _walker(root: Path, files: dict[str, str]) -> Walker:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="\n")
    w = Walker(root, max_files=500, max_depth=8, max_file_bytes=100_000)
    w.ensure_walked()
    return w


def test_cursor_detects_rules_and_mcp(tmp_path: Path) -> None:
    w = _walker(
        tmp_path,
        {
            ".cursor/rules/frontend/components.mdc": "---\ndescription: UI rules\nglobs: src/**/*.tsx\nalwaysApply: false\n---\n\n# UI\n\nbody\n",
            ".cursor/rules/always.mdc": "---\nalwaysApply: true\n---\n\nAlways.\n",
            ".cursor/rules/ignored.md": "no frontmatter, ignored by Cursor\n",
            ".cursor/mcp.json": json.dumps(
                {"mcpServers": {"ctx": {"type": "stdio", "command": "npx"}}}
            ),
        },
    )
    a = get_adapter(Platform.CURSOR)
    det = a.detect(w)
    assert det is not None and det.confidence >= 0.8
    assets = {(x.kind, x.name) for x in a.collect_assets(w)}
    assert ("rule", "components") in assets and ("instruction", "always") in assets
    assert ("mcp", ".cursor/mcp.json") in assets
    assert not any(n == "ignored" for _, n in assets)
    assert platform_owning(".cursor/rules/x.mdc") == Platform.CURSOR
    assert a.validate_content(CapabilityKind.RULE, ".cursor/rules/x.mdc", "# no frontmatter\n")
    assert a.validate_content(
        CapabilityKind.RULE, ".cursor/rules/x.md", "---\ndescription: d\n---\nbody\n"
    )
    assert a.validate_content(
        CapabilityKind.MCP, ".cursor/mcp.json", json.dumps({"mcpServers": {"s": {"command": "x"}}})
    )
    assert (
        a.validate_content(
            CapabilityKind.MCP,
            ".cursor/mcp.json",
            json.dumps({"mcpServers": {"s": {"url": "https://h"}}}),
        )
        == []
    )


def test_copilot_detects_instructions_and_skills(tmp_path: Path) -> None:
    w = _walker(
        tmp_path,
        {
            ".github/copilot-instructions.md": "# Repo\n\nUse pnpm.\n",
            ".github/instructions/tests.instructions.md": "---\napplyTo: '**/*.test.ts'\n---\n\nTest rules.\n",
            ".github/skills/deploy/SKILL.md": "---\nname: deploy\ndescription: Deploys.\n---\n\nSteps.\n",
        },
    )
    a = get_adapter(Platform.COPILOT)
    det = a.detect(w)
    assert det is not None and det.confidence == 1.0
    assets = {(x.kind, x.name) for x in a.collect_assets(w)}
    assert {
        ("instruction", ".github/copilot-instructions.md"),
        ("rule", "tests"),
        ("skill", "deploy"),
    } <= assets
    assert platform_owning(".github/skills/deploy/SKILL.md") == Platform.COPILOT
    assert platform_owning(".github/workflows/ci.yml") is None  # not managed
    skill = "---\nname: Deploy\ndescription: d\n---\nbody\n"
    assert a.validate_content(
        CapabilityKind.SKILL, ".github/skills/deploy/SKILL.md", skill
    )  # uppercase
    ok = "---\nname: deploy\ndescription: d\n---\nbody\n"
    assert a.validate_content(CapabilityKind.SKILL, ".github/skills/deploy/SKILL.md", ok) == []
    assert a.validate_content(
        CapabilityKind.SKILL, ".github/skills/other/SKILL.md", ok
    )  # dir mismatch
    assert a.validate_content(
        CapabilityKind.RULE, ".github/instructions/x.instructions.md", "# no applyTo\n"
    )
    assert a.validate_content(CapabilityKind.HOOK, "x", "{}")


def test_gemini_detects_context_skills_and_settings(tmp_path: Path) -> None:
    w = _walker(
        tmp_path,
        {
            "GEMINI.md": "# Context\n\nbody\n",
            ".gemini/skills/review/SKILL.md": "---\nname: review\ndescription: Reviews.\n---\n\nbody\n",
            ".gemini/settings.json": json.dumps(
                {"mcpServers": {"ctx": {"command": "npx", "args": ["x"]}}}
            ),
        },
    )
    a = get_adapter(Platform.GEMINI)
    det = a.detect(w)
    assert det is not None and det.confidence == 1.0
    kinds = {(x.kind, x.name) for x in a.collect_assets(w)}
    assert {
        ("instruction", "GEMINI.md"),
        ("skill", "review"),
        ("settings", ".gemini/settings.json"),
    } <= kinds
    only_md = _walker(tmp_path / "weak", {"GEMINI.md": "# x\n"})
    weak = a.detect(only_md)
    assert weak is not None and weak.confidence == 0.5  # other tools read GEMINI.md too
    bad = json.dumps({"mcpServers": {"my_server": {"type": "stdio", "command": "x", "url": "u"}}})
    problems = a.validate_content(CapabilityKind.MCP, ".gemini/settings.json", bad)
    assert len(problems) == 3  # underscore, two transports, type key
    assert a.validate_content(CapabilityKind.RULE, "x.md", "body")


def test_scan_reports_the_new_platforms_once(tmp_path: Path) -> None:
    root = tmp_path / "multi"
    _walker(
        root,
        {
            "GEMINI.md": "# g\n",
            ".gemini/settings.json": "{}",
            ".github/copilot-instructions.md": "# c\n",
            ".cursor/rules/a.mdc": "---\nalwaysApply: true\n---\nx\n",
            ".cursorrules": "legacy\n",
            "package.json": '{"name": "x"}',
        },
    )
    profile = scan_project(root)
    assert {Platform.GEMINI, Platform.COPILOT, Platform.CURSOR} <= profile.platform_names
    paths = [a.path for a in profile.assets]
    assert paths.count("GEMINI.md") == 1 and paths.count(".github/copilot-instructions.md") == 1
    assert ".cursorrules" in paths  # legacy file recorded, not owned
