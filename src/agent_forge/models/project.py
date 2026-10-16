"""Project profile produced by `agent-forge scan`. Read-only evidence, never secrets."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent_forge.models.capability import Platform


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(description="Relative path of the indicator")
    detail: str = ""


class Detection(BaseModel):
    """A detected language/framework/project-type with confidence and evidence."""

    model_config = ConfigDict(extra="forbid")
    name: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[Evidence] = Field(default_factory=list)


class GitState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_repo: bool = False
    root: str | None = None
    head: str | None = None
    branch: str | None = None
    dirty: bool | None = None
    dirty_count: int = 0
    remote: str | None = None


class AgentAsset(BaseModel):
    """An existing skill / agent / rule / instruction file found in the target."""

    model_config = ConfigDict(extra="forbid")
    platform: Platform | None
    kind: str = Field(
        description="instruction | skill | agent | rule | hook | mcp | settings | command"
    )
    name: str
    path: str
    managed_by: str | None = Field(
        default=None, description="Capability id if Agent Forge installed it"
    )
    sha256: str | None = None
    lines: int | None = None
    frontmatter: dict[str, Any] = Field(default_factory=dict)
    headings: list[str] = Field(default_factory=list)


class PlatformDetection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: Platform
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[Evidence] = Field(default_factory=list)


class ManagedCapabilityRecord(BaseModel):
    """A capability recorded in the target's `.agent-forge/managed.json`."""

    model_config = ConfigDict(extra="forbid")
    capability_id: str
    version: str
    transaction_id: str
    installed_at: str
    files: dict[str, str] = Field(
        default_factory=dict, description="relative path -> sha256 after install"
    )
    sections: dict[str, str] = Field(
        default_factory=dict, description="relative path -> section_id for merged sections"
    )
    json_merges: dict[str, dict] = Field(
        default_factory=dict,
        description="relative path -> JSON fragment merged into that file (hooks / mcpServers)",
    )
    drift: list[str] = Field(
        default_factory=list, description="Files whose current hash differs (set by scan)"
    )


class ScanStats(BaseModel):
    model_config = ConfigDict(extra="forbid")
    files_seen: int = 0
    dirs_seen: int = 0
    files_read: int = 0
    excluded_dirs: list[str] = Field(default_factory=list)
    skipped_large: int = 0
    skipped_symlinks: int = 0
    truncated: bool = False
    limits: dict[str, int] = Field(default_factory=dict)


class ProjectProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "1"
    scanned_at: str
    forge_version: str
    target_path: str = Field(description="Path as given by the user")
    canonical_path: str = Field(description="Resolved absolute path")
    git: GitState = Field(default_factory=GitState)
    languages: list[Detection] = Field(default_factory=list)
    frameworks: list[Detection] = Field(default_factory=list)
    project_types: list[Detection] = Field(default_factory=list)
    platforms: list[PlatformDetection] = Field(default_factory=list)
    assets: list[AgentAsset] = Field(default_factory=list)
    managed: list[ManagedCapabilityRecord] = Field(default_factory=list)
    managed_manifest_valid: bool | None = Field(
        default=None, description="None = no manifest; False = present but rejected"
    )
    test_commands: list[str] = Field(default_factory=list)
    sensitive_files: list[str] = Field(
        default_factory=list, description="Paths that look like secrets (never read)"
    )
    warnings: list[str] = Field(default_factory=list)
    stats: ScanStats = Field(default_factory=ScanStats)

    # ---- helpers -------------------------------------------------------------------------

    def detected_names(self, items: list[Detection], min_confidence: float = 0.5) -> set[str]:
        return {d.name for d in items if d.confidence >= min_confidence}

    @property
    def language_names(self) -> set[str]:
        return self.detected_names(self.languages)

    @property
    def framework_names(self) -> set[str]:
        return self.detected_names(self.frameworks)

    @property
    def project_type_names(self) -> set[str]:
        return self.detected_names(self.project_types)

    @property
    def platform_names(self) -> set[Platform]:
        return {p.platform for p in self.platforms if p.confidence >= 0.5}

    def assets_of(self, kind: str, platform: Platform | None = None) -> list[AgentAsset]:
        return [
            a
            for a in self.assets
            if a.kind == kind and (platform is None or a.platform == platform)
        ]

    def fingerprint(self) -> str:
        """Stable digest of the facts a plan depends on (not timestamps or stats)."""
        payload = {
            "canonical_path": self.canonical_path,
            "git_head": self.git.head,
            "languages": sorted(self.language_names),
            "frameworks": sorted(self.framework_names),
            "project_types": sorted(self.project_type_names),
            "platforms": sorted(p.value for p in self.platform_names),
            "assets": sorted((a.kind, a.path, a.sha256 or "") for a in self.assets),
            "managed": sorted((m.capability_id, m.version) for m in self.managed),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
