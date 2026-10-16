"""Agent platform adapters."""

from __future__ import annotations

from agent_forge.adapters.base import PlatformAdapter
from agent_forge.adapters.claude_code import ClaudeCodeAdapter
from agent_forge.adapters.codex import CodexAdapter
from agent_forge.models.capability import Platform

_ADAPTERS: dict[Platform, PlatformAdapter] = {
    Platform.CLAUDE_CODE: ClaudeCodeAdapter(),
    Platform.CODEX: CodexAdapter(),
}


def all_adapters() -> list[PlatformAdapter]:
    return list(_ADAPTERS.values())


def get_adapter(platform: Platform) -> PlatformAdapter:
    return _ADAPTERS[platform]


__all__ = ["PlatformAdapter", "all_adapters", "get_adapter"]
