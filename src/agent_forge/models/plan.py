"""Upgrade plan model. Plans are immutable once approved; approval is bound to the plan digest."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_forge.models.capability import Platform, RiskLevel

# An approved plan must be applied within this window; afterwards re-plan (vision §7.1).
PLAN_TTL = timedelta(days=7)


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
        "integrity_mismatch | "
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
    schema_version: Literal["1"] = "1"  # an unknown version is refused, never misread
    plan_id: str
    kind: str = Field(description="assign | upgrade")
    created_at: str
    forge_version: str
    target: TargetIdentity
    target_path: str
    registry_digest: str
    policy_digest: str | None = Field(
        default=None, description="Digest of the effective policy layers the plan was built under"
    )
    expires_at: str | None = Field(
        default=None, description="Approve/apply refuse the plan after this time (created_at + TTL)"
    )
    decisions_digest: str | None = Field(
        default=None,
        description="Digest of the verified decision record (`forge --decisions`) the plan "
        "was built from (ADR-0007); part of the content digest when present",
    )
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

    @model_validator(mode="after")
    def _default_expiry(self) -> Plan:
        if self.expires_at is None:
            created = datetime.fromisoformat(self.created_at)
            self.expires_at = (created + PLAN_TTL).isoformat()
        return self

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at is not None and now >= datetime.fromisoformat(self.expires_at)

    # ---- integrity -----------------------------------------------------------------------

    def content_digest(self) -> str:
        """Digest of everything an approval covers: target identity, registry, operations."""
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "kind": self.kind,
            "target": self.target.model_dump(mode="json"),
            "registry_digest": self.registry_digest,
            "policy_digest": self.policy_digest,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "selected": [s.model_dump(mode="json") for s in self.selected],
            "operations": [o.model_dump(mode="json") for o in self.operations],
        }
        if self.decisions_digest is not None:
            payload["decisions_digest"] = self.decisions_digest
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
