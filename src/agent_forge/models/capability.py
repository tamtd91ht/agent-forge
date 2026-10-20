"""Capability manifest model (`capability.yaml`).

A capability is a reviewed, versioned unit of agent infrastructure (a skill, a rule set, an
instruction section, an agent definition, a reference to a native plugin...). The manifest
separates *metadata* (this model) from *content* (`assets/` next to it).
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CAPABILITY_ID_RE = re.compile(
    r"^[a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?)*$"
)
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CapabilityStatus(StrEnum):
    DISCOVERED = "discovered"
    UNDER_REVIEW = "under_review"
    CURATED = "curated"
    DEPRECATED = "deprecated"  # no new installs; installed copies keep working, `replaced_by`
    REVOKED = "revoked"  # withdrawn for cause: installed copies are reported as errors
    REJECTED = "rejected"


class Provenance(StrEnum):
    UPSTREAM = "upstream"  # verbatim upstream content
    ADAPTED = "adapted"  # upstream content modified in the workspace
    WORKSPACE = "workspace"  # authored in this workspace
    GENERATED = "generated"  # produced per target project at plan time
    USER_MODIFIED = (
        "user_modified"  # installed content changed by the user (detected, not authored)
    )


class Platform(StrEnum):
    CLAUDE_CODE = "claude_code"
    CODEX = "codex"
    CURSOR = "cursor"
    COPILOT = "copilot"
    GEMINI = "gemini"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class InstallStrategy(StrEnum):
    FILE_COPY = "file_copy"  # copy assets into the target under managed paths
    SECTION_MERGE = "section_merge"  # add a marker-delimited section to a shared file
    NATIVE_PLUGIN = (
        "native_plugin"  # requires a runtime/plugin install Agent Forge will not perform
    )
    REFERENCE_ONLY = "reference_only"  # informs recommendations; never installed


class MergeStrategy(StrEnum):
    CREATE_ONLY = "create_only"  # fail/skip if the destination exists and is not managed
    REPLACE_MANAGED = (
        "replace_managed"  # overwrite only if the existing file is managed and unmodified
    )
    APPEND_SECTION = "append_section"  # add/replace a marker-delimited block inside a shared file
    JSON_MERGE = "json_merge"  # merge a JSON fragment (hooks / mcpServers) into a settings file


class NetworkRequirement(StrEnum):
    NONE = "none"
    OPTIONAL = "optional"
    REQUIRED = "required"


class CapabilityKind(StrEnum):
    SKILL = "skill"
    RULE = "rule"
    AGENT = "agent"
    INSTRUCTION = "instruction"
    HOOK = "hook"
    MCP = "mcp"
    REFERENCE = "reference"


class SourceRef(StrictModel):
    source_id: str = Field(description="ID from sources.yaml, or 'workspace'")
    repository: str | None = Field(default=None, description="Git remote URL")
    revision: str | None = Field(
        default=None, description="Full commit SHA verified at curation time"
    )
    paths: list[str] = Field(
        default_factory=list, description="Upstream paths this capability derives from"
    )

    @field_validator("revision")
    @classmethod
    def _immutable_revision(cls, v: str | None) -> str | None:
        # a branch or tag name can move; only a full commit SHA pins content
        if v is not None and not re.fullmatch(r"[0-9a-f]{40}", v):
            raise ValueError(f"source.revision must be a full 40-hex commit SHA, got {v!r}")
        return v


class LicenseInfo(StrictModel):
    spdx: str = Field(description="SPDX identifier, e.g. MIT")
    attribution: str = Field(description="Attribution line that must be preserved")
    notice_file: str | None = Field(
        default=None, description="Relative path (in assets/) of a preserved notice"
    )
    redistribution_ok: bool = Field(description="Reviewer confirmed redistribution is permitted")


class Applicability(StrictModel):
    """Hard applicability conditions. Empty lists mean 'no constraint'."""

    project_types: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    any_of_files: list[str] = Field(
        default_factory=list, description="Glob-free relative paths; applies if at least one exists"
    )
    tags: list[str] = Field(
        default_factory=list, description="Matches user-requested tags (--want)"
    )
    always: bool = Field(
        default=False, description="Applies to every project (still subject to conflicts)"
    )


class EquivalentSignal(StrictModel):
    """Evidence that a project already has an equivalent capability."""

    platform: Platform | None = None
    kind: CapabilityKind
    name_patterns: list[str] = Field(
        default_factory=list, description="Regexes against skill/agent/rule names"
    )
    content_patterns: list[str] = Field(
        default_factory=list,
        description="Regexes against instruction file content (case-insensitive)",
    )
    description: str


class Destination(StrictModel):
    platform: Platform
    source: str = Field(
        description="Path relative to the capability's assets/ directory (file or dir)"
    )
    dest: str = Field(description="Path relative to the target project root")
    merge: MergeStrategy = MergeStrategy.CREATE_ONLY
    section_id: str | None = Field(default=None, description="Marker id for APPEND_SECTION")

    @field_validator("source", "dest")
    @classmethod
    def _relative_safe(cls, v: str) -> str:
        if v.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", v):
            raise ValueError(f"path must be relative: {v!r}")
        if any(part == ".." for part in re.split(r"[\\/]", v)):
            raise ValueError(f"path must not contain '..': {v!r}")
        return v.replace("\\", "/")

    @model_validator(mode="after")
    def _section_requires_id(self) -> Destination:
        if (
            self.merge in (MergeStrategy.APPEND_SECTION, MergeStrategy.JSON_MERGE)
            and not self.section_id
        ):
            raise ValueError(f"{self.merge.value} destinations require section_id")
        return self


class ValidationCheck(StrictModel):
    type: str = Field(
        description="file_exists | frontmatter | yaml | json | section_present | max_lines"
    )
    path: str
    params: dict[str, Any] = Field(default_factory=dict)


class AcknowledgedFinding(StrictModel):
    """A content-safety finding a reviewer read and accepted (registry/content_safety.py)."""

    rule: str
    path: str = Field(description="Asset path relative to assets/; fnmatch globs allowed")
    reason: str


class EvaluationEvidence(StrictModel):
    """One baseline-vs-candidate evaluation (tools/agent-forge-eval), summarised by a human.

    Numbers are copied from the harness report; `report` points at the committed report so
    anyone can check them. A capability without evidence is an opinion, and `catalog show`
    says so.
    """

    date: str = Field(description="ISO-8601 date of the run")
    fixture: str = Field(description="examples/<fixture> the task set came from")
    tool: str = Field(description="coding tool and version, e.g. 'claude 2.1.304'")
    runs: Annotated[int, Field(ge=1)] = Field(description="runs per task and arm")
    tasks: Annotated[int, Field(ge=1)] = Field(description="number of tasks")
    baseline_pass_rate: Annotated[float, Field(ge=0, le=1)]
    candidate_pass_rate: Annotated[float, Field(ge=0, le=1)]
    candidate_ci95: tuple[float, float] = Field(description="Wilson 95% interval, candidate arm")
    verdict: Literal["improved", "no_evidence", "worse"]
    report: str = Field(description="Repository path of the report (docs/evaluation/results/...)")
    decided_by: str = Field(description="Human who read the report and recorded this entry")

    @model_validator(mode="after")
    def _ci_ordered(self) -> EvaluationEvidence:
        lo, hi = self.candidate_ci95
        if not 0 <= lo <= hi <= 1:
            raise ValueError("candidate_ci95 must be [low, high] within 0..1")
        return self


class ReviewInfo(StrictModel):
    reviewed_at: str = Field(description="ISO-8601 date")
    reviewer: str
    rationale: str
    risk_rationale: str | None = Field(
        default=None, description="Why the risk level is what it is (required above low)"
    )
    acknowledged_findings: list[AcknowledgedFinding] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    signed_off_by: str | None = Field(
        default=None, description="Human who signed off the curation (None = pending)"
    )
    signed_off_at: str | None = None
    evidence: list[EvaluationEvidence] = Field(
        default_factory=list,
        description="Evaluation results (baseline vs candidate); empty = value not measured",
    )


class RuntimeRequirement(StrictModel):
    name: str
    description: str
    install_hint: str | None = None


class Grants(StrictModel):
    """What the installed content can do once the agent uses it. Input to the policy engine.

    Defaults are derived from `kind` when a manifest does not spell them out: hooks execute
    processes, MCP servers execute processes and (usually) access the network.
    """

    process_execute: bool = Field(default=False, description="Runs commands / launches processes")
    network_access: bool = Field(default=False, description="Talks to the network at runtime")
    secrets_read: bool = Field(default=False, description="May read credential material")
    filesystem_write: list[str] = Field(
        default_factory=list,
        description="Project-relative prefixes the content may write to at runtime (not install time)",
    )


class Integrity(StrictModel):
    assets_sha256: str = Field(
        description="sha256 over assets/ (relative paths + file hashes); pinned by scripts/pin_integrity.py"
    )
    pinned_at: str | None = None


class Capability(StrictModel):
    schema_version: Literal["1"] = "1"  # an unknown version is refused, never misread
    id: str
    name: str
    description: str
    version: str
    kind: CapabilityKind
    category: str
    purpose: str
    status: CapabilityStatus
    replaced_by: str | None = Field(
        default=None, description="Capability id to use instead (deprecated / revoked entries)"
    )
    provenance: Provenance
    source: SourceRef
    license: LicenseInfo
    review: ReviewInfo
    applicability: Applicability = Field(default_factory=Applicability)
    platforms: list[Platform]
    install_strategy: InstallStrategy
    destinations: list[Destination] = Field(default_factory=list)
    dependencies: list[str] = Field(
        default_factory=list, description="Capability IDs required first"
    )
    conflicts: list[str] = Field(
        default_factory=list, description="Capability IDs that must not coexist"
    )
    equivalents: list[EquivalentSignal] = Field(default_factory=list)
    permissions: list[str] = Field(
        default_factory=list,
        description="Free-form permission tags shown in reports (e.g. 'runs_shell'); see `grants`",
    )
    grants: Grants | None = Field(
        default=None, description="Structured runtime permissions; derived from kind when omitted"
    )
    integrity: Integrity | None = Field(
        default=None, description="Pinned digest of assets/; verified by `validate`"
    )
    network: NetworkRequirement = NetworkRequirement.NONE
    runtime_requirements: list[RuntimeRequirement] = Field(default_factory=list)
    risk: RiskLevel = RiskLevel.LOW
    validation: list[ValidationCheck] = Field(default_factory=list)
    removal: str = Field(
        default="delete_managed_files", description="delete_managed_files | remove_section"
    )
    benefit_score: Annotated[int, Field(ge=0, le=10)] = 5
    maintenance_cost: Annotated[int, Field(ge=0, le=10)] = 2

    @field_validator("id")
    @classmethod
    def _id_format(cls, v: str) -> str:
        if not CAPABILITY_ID_RE.match(v):
            raise ValueError(
                f"invalid capability id {v!r}: use lowercase, digits, '-' and '.' segments"
            )
        return v

    @field_validator("version")
    @classmethod
    def _semver(cls, v: str) -> str:
        if not SEMVER_RE.match(v):
            raise ValueError(f"version must be MAJOR.MINOR.PATCH, got {v!r}")
        return v

    @model_validator(mode="after")
    def _consistency(self) -> Capability:
        if self.install_strategy in (InstallStrategy.FILE_COPY, InstallStrategy.SECTION_MERGE):
            if not self.destinations:
                raise ValueError(
                    f"{self.id}: {self.install_strategy} requires at least one destination"
                )
            for d in self.destinations:
                if d.platform not in self.platforms:
                    raise ValueError(
                        f"{self.id}: destination platform {d.platform} not in platforms"
                    )
        if self.install_strategy == InstallStrategy.REFERENCE_ONLY and self.destinations:
            raise ValueError(f"{self.id}: reference_only capabilities cannot declare destinations")
        if self.install_strategy == InstallStrategy.NATIVE_PLUGIN and not self.runtime_requirements:
            raise ValueError(
                f"{self.id}: native_plugin capabilities must declare runtime_requirements"
            )
        if self.id in self.dependencies or self.id in self.conflicts:
            raise ValueError(f"{self.id}: capability cannot depend on or conflict with itself")
        if self.status == CapabilityStatus.CURATED and not self.license.redistribution_ok:
            raise ValueError(
                f"{self.id}: curated capabilities require license.redistribution_ok=true"
            )
        return self

    @property
    def effective_grants(self) -> Grants:
        """Declared grants, or conservative defaults derived from the capability kind."""
        if self.grants is not None:
            return self.grants
        if self.kind == CapabilityKind.HOOK:
            return Grants(process_execute=True, filesystem_write=["."])
        if self.kind == CapabilityKind.MCP:
            return Grants(
                process_execute=True, network_access=self.network != NetworkRequirement.NONE
            )
        if self.install_strategy == InstallStrategy.NATIVE_PLUGIN:
            return Grants(
                process_execute=True, network_access=self.network != NetworkRequirement.NONE
            )
        return Grants(network_access=self.network == NetworkRequirement.REQUIRED)

    @property
    def installable(self) -> bool:
        return self.status == CapabilityStatus.CURATED and self.install_strategy in (
            InstallStrategy.FILE_COPY,
            InstallStrategy.SECTION_MERGE,
        )

    def destinations_for(self, platform: Platform) -> list[Destination]:
        return [d for d in self.destinations if d.platform == platform]
