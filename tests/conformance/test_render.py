"""Transpile conformance (ADR-0006): every adapter renders canonical content into something
its own `validate_content` accepts, deterministically, for every kind it supports; and every
curated destination in the real registry renders cleanly for its platform."""

from __future__ import annotations

import hashlib
import json

import pytest

from agent_forge.adapters import all_adapters, get_adapter
from agent_forge.adapters.base import PlatformAdapter
from agent_forge.models.capability import CapabilityKind, MergeStrategy
from agent_forge.planner.builder import _asset_files
from agent_forge.registry.loader import load_registry
from agent_forge.util import normalize_newlines
from tests.conftest import REAL_REGISTRY

ADAPTERS = all_adapters()
IDS = [a.platform.value for a in ADAPTERS]

# Canonical content = Claude Code formats (the identity for that adapter).
CANONICAL = {
    CapabilityKind.SKILL: "---\nname: sample-skill\ndescription: Does a sample thing. Use when sampling.\n---\n\n# Sample\n\nDo it.\n",
    CapabilityKind.RULE: '---\ndescription: Testing rules\npaths:\n  - "**/*.test.ts"\n  - "tests/**"\n---\n\n# Testing\n\nWrite tests first.\n',
    CapabilityKind.INSTRUCTION: "## Working principles\n\nThink before coding.\n",
    CapabilityKind.AGENT: "---\nname: reviewer\ndescription: Reviews code.\n---\n\nReview carefully.\n",
    CapabilityKind.MCP: json.dumps(
        {"mcpServers": {"ctx": {"type": "stdio", "command": "npx", "args": ["-y", "ctx"]}}}
    ),
}

# Where each adapter installs each kind (mirrors the registry conventions).
DEST = {
    "claude_code": {
        CapabilityKind.SKILL: ".claude/skills/sample-skill/SKILL.md",
        CapabilityKind.RULE: ".claude/rules/testing.md",
        CapabilityKind.INSTRUCTION: "CLAUDE.md",
        CapabilityKind.AGENT: ".claude/agents/reviewer.md",
        CapabilityKind.MCP: ".mcp.json",
    },
    "codex": {
        CapabilityKind.SKILL: ".agents/skills/sample-skill/SKILL.md",
        CapabilityKind.INSTRUCTION: "AGENTS.md",
    },
    "cursor": {
        CapabilityKind.RULE: ".cursor/rules/testing.mdc",
        CapabilityKind.INSTRUCTION: ".cursor/rules/agent-forge-principles.mdc",
        CapabilityKind.MCP: ".cursor/mcp.json",
    },
    "copilot": {
        CapabilityKind.SKILL: ".github/skills/sample-skill/SKILL.md",
        CapabilityKind.RULE: ".github/instructions/testing.instructions.md",
        CapabilityKind.INSTRUCTION: ".github/copilot-instructions.md",
    },
    "gemini": {
        CapabilityKind.SKILL: ".gemini/skills/sample-skill/SKILL.md",
        CapabilityKind.INSTRUCTION: "GEMINI.md",
        CapabilityKind.MCP: ".gemini/settings.json",
    },
}


def _digest(text: str) -> str:
    return hashlib.sha256(normalize_newlines(text).encode("utf-8")).hexdigest()


@pytest.mark.parametrize("adapter", ADAPTERS, ids=IDS)
def test_render_is_deterministic_and_valid_for_every_supported_kind(
    adapter: PlatformAdapter,
) -> None:
    dests = DEST[adapter.platform.value]
    for kind in adapter.info.supported_kinds:
        if kind in (CapabilityKind.HOOK, CapabilityKind.REFERENCE):
            continue
        assert kind in dests, f"{adapter.platform.value}: no destination for {kind.value}"
        rel = dests[kind]
        once = adapter.render(kind, rel, CANONICAL[kind])
        twice = adapter.render(kind, rel, CANONICAL[kind])
        assert once == twice and _digest(once) == _digest(twice)
        # CRLF input renders to the same bytes as LF input (same hash on every OS)
        crlf = adapter.render(kind, rel, CANONICAL[kind].replace("\n", "\r\n"))
        assert _digest(crlf) == _digest(once), f"{adapter.platform.value}/{kind.value}"
        assert adapter.validate_content(kind, rel, once) == [], (
            f"{adapter.platform.value}/{kind.value}: {adapter.validate_content(kind, rel, once)}"
        )


def test_cursor_rule_render_maps_paths_to_globs() -> None:
    out = get_adapter("cursor").render(
        CapabilityKind.RULE, ".cursor/rules/t.mdc", CANONICAL[CapabilityKind.RULE]
    )
    assert out.startswith("---\n")
    assert "globs: '**/*.test.ts, tests/**'" in out or 'globs: "**/*.test.ts, tests/**"' in out
    assert "alwaysApply: false" in out and "paths:" not in out
    inst = get_adapter("cursor").render(
        CapabilityKind.INSTRUCTION, ".cursor/rules/x.mdc", CANONICAL[CapabilityKind.INSTRUCTION]
    )
    assert "alwaysApply: true" in inst and "Working principles" in inst


def test_copilot_rule_render_sets_apply_to() -> None:
    out = get_adapter("copilot").render(
        CapabilityKind.RULE,
        ".github/instructions/t.instructions.md",
        CANONICAL[CapabilityKind.RULE],
    )
    assert "applyTo:" in out and "**/*.test.ts, tests/**" in out and "paths:" not in out
    plain = get_adapter("copilot").render(CapabilityKind.RULE, "x", "# Only a body\n\ntext\n")
    assert "applyTo: '**'" in plain or 'applyTo: "**"' in plain


def test_gemini_mcp_render_drops_type_and_maps_urls() -> None:
    frag = json.dumps(
        {
            "mcpServers": {
                "a": {"type": "stdio", "command": "npx", "args": ["x"]},
                "b": {"type": "http", "url": "https://h/mcp"},
                "c": {"type": "sse", "url": "https://s/sse"},
            }
        }
    )
    out = json.loads(
        get_adapter("gemini").render(CapabilityKind.MCP, ".gemini/settings.json", frag)
    )
    assert out == {
        "mcpServers": {
            "a": {"command": "npx", "args": ["x"]},
            "b": {"httpUrl": "https://h/mcp"},
            "c": {"url": "https://s/sse"},
        }
    }


def test_every_curated_destination_renders_cleanly() -> None:
    """The real registry: each destination's rendered primary files pass its adapter's rules."""
    reg = load_registry(REAL_REGISTRY)
    checked = 0
    for lc in reg.items.values():
        cap = lc.capability
        for dest in cap.destinations:
            adapter = get_adapter(dest.platform)
            for rel, content in _asset_files(lc, dest):
                if dest.merge == MergeStrategy.JSON_MERGE or (
                    rel.endswith((".md", ".mdc"))
                    and (cap.kind != CapabilityKind.SKILL or rel.endswith("SKILL.md"))
                ):
                    problems = adapter.validate_content(cap.kind, rel, content)
                    assert problems == [], f"{cap.id} -> {rel}: {problems}"
                    checked += 1
    assert checked >= 20
