"""Agent platform adapters."""

from __future__ import annotations

from agent_forge.adapters.base import PlatformAdapter
from agent_forge.adapters.claude_code import ClaudeCodeAdapter
from agent_forge.adapters.codex import CodexAdapter
from agent_forge.adapters.copilot import CopilotAdapter
from agent_forge.adapters.cursor import CursorAdapter
from agent_forge.adapters.gemini import GeminiAdapter
from agent_forge.models.capability import Platform

_ADAPTERS: dict[Platform, PlatformAdapter] = {
    Platform.CLAUDE_CODE: ClaudeCodeAdapter(),
    Platform.CODEX: CodexAdapter(),
    Platform.CURSOR: CursorAdapter(),
    Platform.COPILOT: CopilotAdapter(),
    Platform.GEMINI: GeminiAdapter(),
}


def all_adapters() -> list[PlatformAdapter]:
    return list(_ADAPTERS.values())


def get_adapter(platform: Platform) -> PlatformAdapter:
    return _ADAPTERS[platform]


def platform_owning(rel_path: str) -> Platform | None:
    """The platform whose managed roots contain `rel_path` (None for shared/unknown paths)."""
    owners = [a.platform for a in _ADAPTERS.values() if a.owns(rel_path)]
    return owners[0] if len(owners) == 1 else None


__all__ = ["PlatformAdapter", "all_adapters", "get_adapter", "platform_owning"]
