"""Platform adapter interface.

An adapter knows how one agent platform lays out project-scoped configuration. It is used by
the scanner (detect + inventory), the planner (where may a capability be written, what counts
as a shared file), and the validator (native format rules). Adapters never write files.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from agent_forge.models.capability import CapabilityKind, Platform
from agent_forge.models.project import AgentAsset, PlatformDetection
from agent_forge.scanner.filesystem import Walker


@dataclass(frozen=True)
class AdapterInfo:
    platform: Platform
    display_name: str
    docs_url: str
    verified_on: str
    instruction_files: tuple[str, ...]
    shared_files: tuple[str, ...]
    managed_roots: tuple[str, ...]
    supported_kinds: tuple[CapabilityKind, ...]
    unsupported_notes: tuple[str, ...]


class PlatformAdapter(ABC):
    info: AdapterInfo

    @property
    def platform(self) -> Platform:
        return self.info.platform

    @abstractmethod
    def detect(self, walker: Walker) -> PlatformDetection | None:
        """Evidence that the target already uses this platform (None = no evidence)."""

    @abstractmethod
    def collect_assets(self, walker: Walker) -> list[AgentAsset]:
        """Inventory existing instructions, skills, agents, rules, hooks, MCP declarations."""

    @abstractmethod
    def validate_content(self, kind: CapabilityKind, rel_path: str, content: str) -> list[str]:
        """Return problems with a piece of content destined for `rel_path` (empty = ok)."""

    def supports(self, kind: CapabilityKind) -> bool:
        return kind in self.info.supported_kinds

    def is_shared_file(self, rel_path: str) -> bool:
        return rel_path in self.info.shared_files

    def path_allowed(self, rel_path: str) -> bool:
        """Is `rel_path` inside a root this adapter is allowed to manage?"""
        rel = rel_path.replace("\\", "/")
        for root in self.info.managed_roots:
            if root.endswith("/"):
                if rel.startswith(root):
                    return True
            elif rel == root:
                return True
        return False
