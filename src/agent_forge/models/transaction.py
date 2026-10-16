"""Transaction record written by `apply`; consumed by `status`, `validate` and `rollback`."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from agent_forge.models.plan import OperationKind


class TransactionStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"  # some operations applied, then a failure occurred
    ROLLED_BACK = "rolled_back"
    ROLLBACK_CONFLICT = "rollback_conflict"


class AppliedOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op_id: str
    kind: OperationKind
    path: str
    capability_id: str | None = None
    section_id: str | None = None
    before_sha256: str | None = Field(default=None, description="None = file did not exist")
    after_sha256: str | None = Field(default=None, description="None = file removed")
    backup: str | None = Field(
        default=None, description="Relative path inside the transaction backup dir"
    )
    applied: bool = False
    error: str | None = None
    fragment: dict | None = Field(
        default=None, description="For merge_json operations: the fragment that was merged"
    )


class Transaction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "1"
    transaction_id: str
    plan_id: str
    plan_digest: str
    forge_version: str
    target_canonical_path: str
    started_at: str
    finished_at: str | None = None
    status: TransactionStatus = TransactionStatus.IN_PROGRESS
    operations: list[AppliedOperation] = Field(default_factory=list)
    capabilities: dict[str, str] = Field(
        default_factory=dict, description="capability_id -> version"
    )
    notes: list[str] = Field(default_factory=list)
    rollback_of: str | None = Field(default=None, description="Transaction id this one reverses")
    record_sha256: str | None = Field(default=None, description="Integrity hash of this record")

    def compute_record_digest(self) -> str:
        data = self.model_dump(mode="json", exclude={"record_sha256"})
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()

    def seal(self) -> None:
        self.record_sha256 = self.compute_record_digest()

    def integrity_ok(self) -> bool:
        return self.record_sha256 is not None and self.record_sha256 == self.compute_record_digest()
