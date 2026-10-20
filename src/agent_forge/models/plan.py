"""Upgrade plan model. Plans are immutable once approved; approval is bound to the plan digest."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent_forge.models.capability import Platform, RiskLevel


class PlanStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    APPLIED = "applied"
    STALE = "stale"
    FAILED = "failed"
    REVOKED = "revoked"


class OperationKind(StrEnum):
    CREATE = "create"  # new file; must not exist (or must be identical managed file)
    REPLACE = "replace"  # overwrite a managed, unmodified file
    MERGE_SECTION = "merge_section"  # insert/replace a marker-delimited block in a shared file
    REMOVE = "remove"  # delete a managed file (upgrade/removal only)
    REMOVE_SECTION = "remove_section"
    MERGE_JSON = "merge_json"  # merge a hooks/mcpServers fragment into a JSON settings file
    REMOVE_JSON = "remove_json"  # remove a previously merged fragment
    MANIFEST = "manifest"  # write .agent-forge/managed.json


class FileOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op_id: str
    kind: OperationKind
    path: str = Field(description="Relative to target root, POSIX separators")
    capability_id: str | None = None
    capability_version: str | None = None
    platform: Platform | None = None
    section_id: str | None = None
    content: str | None = Field(default=None, description="Full new file content or section body")
    content_sha256: str | None = Field(default=None, description="sha256 of `content`")
    before_sha256: str | None = Field(
        default=None, description="Expected current file hash; None = absent"
    )
    after_sha256: str | None = Field(
        default=None, description="Expected hash after apply when computable"
    )
    shared_file: bool = Field(default=False, description="True for CLAUDE.md/AGENTS.md style files")
    requires_extra_approval: bool = False
    approval_class: str = Field(
        default="standard",
        description="standard | shared_file | hook | mcp — which explicit approval flag covers it",
    )
    previous_content: str | None = Field(
        default=None, description="For MERGE_JSON upgrades: the fragment being replaced"
    )
    reason: str = ""


class SelectedCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capability_id: str
    version: str
    platform: Platform
    score: float
    risk: RiskLevel
    reasons: list[str] = Field(default_factory=list)
    solves: str = ""
    existing: list[str] = Field(
        default_factory=list, description="What already exists in the target"
    )
    adds: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    validation: list[str] = Field(default_factory=list)
    rollback: str = ""
    optional: bool = False
    context_chars: int = Field(
        default=0, description="Always-loaded context this capability adds (registry.context_load)"
    )


class RejectedCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capability_id: str
    version: str
    reasons: list[str]
    category: str = Field(
        default="not_applicable",
        description="not_applicable | equivalent_exists | conflict | unsupported_platform | "
        "needs_runtime | reference_only | dependency_missing | already_installed | user_excluded",
    )


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    required: bool = True
    status: str = Field(default="pending", description="pending | approved | revoked")
    approved_at: str | None = None
    approved_by: str | None = None
    plan_digest: str | None = Field(default=None, description="Digest the approval is bound to")
    extra_approvals: list[str] = Field(
        default_factory=list, description="op_ids explicitly approved for shared-file changes"
    )


class TargetIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    canonical_path: str
    git_root: str | None = None
    git_head: str | None = None
    git_dirty: bool | None = None
    profile_fingerprint: str


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "1"
    plan_id: str
    kind: str = Field(description="assign | upgrade")
    created_at: str
    forge_version: str
    target: TargetIdentity
    target_path: str
    registry_digest: str
    selected: list[SelectedCapability] = Field(default_factory=list)
    rejected: list[RejectedCapability] = Field(default_factory=list)
    dependency_order: list[str] = Field(default_factory=list)
    operations: list[FileOperation] = Field(default_factory=list)
    risk: RiskLevel = RiskLevel.LOW
    validation_plan: list[str] = Field(default_factory=list)
    rollback_strategy: str = ""
    user_decisions: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    approval: Approval = Field(default_factory=Approval)
    status: PlanStatus = PlanStatus.DRAFT
    transaction_id: str | None = None

    # ---- integrity -----------------------------------------------------------------------

    def content_digest(self) -> str:
        """Digest of everything an approval covers: target identity, registry, operations."""
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "kind": self.kind,
            "target": self.target.model_dump(mode="json"),
            "registry_digest": self.registry_digest,
            "selected": [s.model_dump(mode="json") for s in self.selected],
            "operations": [o.model_dump(mode="json") for o in self.operations],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    @property
    def is_approved(self) -> bool:
        return (
            self.status == PlanStatus.APPROVED
            and self.approval.status == "approved"
            and self.approval.plan_digest == self.content_digest()
        )

    def operations_needing_extra_approval(self) -> list[FileOperation]:
        return [o for o in self.operations if o.requires_extra_approval]
