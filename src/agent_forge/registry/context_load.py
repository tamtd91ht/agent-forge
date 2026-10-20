"""Always-loaded context cost of a capability (ADR-0003).

Some installed material sits in the agent's context window on every turn whether or not it is
used: the name and description of every model-invoked skill and subagent, rules without a
`paths:` scope, and sections merged into CLAUDE.md / AGENTS.md. Everything else (skill bodies,
reference files, hooks, MCP configs) is loaded on demand or not at all.

The measure is characters, not tokens: deterministic, model-agnostic, computed from registry
assets only, and good enough to compare capabilities and to set a policy budget.
"""

from __future__ import annotations

from pathlib import Path

from agent_forge.models.capability import MergeStrategy, Platform
from agent_forge.registry.loader import LoadedCapability
from agent_forge.util import normalize_newlines, parse_frontmatter


def context_chars(lc: LoadedCapability, platform: Platform) -> int:
    """Characters this capability adds to every turn's context on `platform`."""
    total = 0
    for dest in lc.capability.destinations_for(platform):
        src = lc.assets_dir / dest.source
        if dest.merge == MergeStrategy.APPEND_SECTION:
            total += len(_read(src)) if src.is_file() else 0
            continue
        if src.is_file():
            total += _always_loaded(dest.dest, _read(src))
        elif src.is_dir():
            base = dest.dest.rstrip("/")
            for p in sorted(src.rglob("*.md")):
                if p.is_file() and not p.is_symlink():
                    total += _always_loaded(f"{base}/{p.relative_to(src).as_posix()}", _read(p))
    return total


def _always_loaded(dest_rel: str, text: str) -> int:
    fm, body = parse_frontmatter(text)
    if dest_rel.endswith("/SKILL.md"):
        if fm.get("disable-model-invocation") is True:
            return 0  # user-invoked: reachable only by typing its name
        return len(str(fm.get("name") or "")) + len(str(fm.get("description") or ""))
    if dest_rel.startswith(".claude/agents/") and dest_rel.endswith(".md"):
        return len(str(fm.get("name") or "")) + len(str(fm.get("description") or ""))
    if dest_rel.startswith(".claude/rules/") and dest_rel.endswith(".md"):
        return 0 if fm.get("paths") else len(body.strip())
    return 0


def _read(path: Path) -> str:
    return normalize_newlines(path.read_text(encoding="utf-8", errors="replace"))
