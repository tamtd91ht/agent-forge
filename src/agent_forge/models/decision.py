"""Decision records (ADR-0007): the agent's per-capability assessment as checkable data.

`/agent-forge-upgrade` assesses every capability on one fixed rubric (grounds to skip first,
then the gap it fills, then cost, risk and evidence copied from the catalog) and writes the
result to `<project>/.agent-forge/decisions/<plan-id>.json`. The engine never produces these
records; it only reads them: `decisions verify` checks every claim it can check (paths exist,
quotes are real, numbers match the catalog, grounds carry their evidence, policy is
respected) and downgrades an unprovable SKIP / REMOVE to ASK; `forge --decisions` turns
verified verdicts into the plan and binds the record's digest to it; `status` explains why a
capability is absent; `drift` reports when the basis of a decision disappeared.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DECISION_SCHEMA_VERSION = "1"


class Verdict(StrEnum):
    ADD = "ADD"
    SKIP = "SKIP"
    UPGRADE = "UPGRADE"
    REMOVE = "REMOVE"
    ASK = "ASK"


class Ground(StrEnum):
    """Why a capability should not be installed. Each ground needs its own evidence."""

    COVERED = "covered"  # an existing file does the same job: path + quote
    CONFLICTS = "conflicts"  # contradicts a project convention: path + quote
    SECURITY = "security"  # permissions / hooks / MCP the project forbids: manifest + rule
    CONTEXT_COST = "context_cost"  # always-loaded context above a budget: catalog number
    STACK_MISMATCH = "stack_mismatch"  # applicability vs the scanned profile
    EVIDENCE_WORSE = "evidence_worse"  # review.evidence says `worse` on this stack
    DUPLICATE_TOOL = "duplicate_tool"  # .mcp.json / settings / package.json already has it
    UNUSED = "unused"  # installed, zero invocations in the usage log window


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Scope(StrEnum):
    INSTALL = "install"
    UPGRADE = "upgrade"
    REMOVE = "remove"


EvidenceVerdict = Literal["improved", "no_evidence", "worse", "not_measured"]


class Citation(BaseModel):
    """A file in the project and, when a ground requires it, one line quoted from it."""

    model_config = ConfigDict(extra="forbid")
    path: str = Field(description="Relative to the project root, POSIX separators")
    quote: str | None = Field(
        default=None, description="A substring that must occur in the file (newline-insensitive)"
    )


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capability_id: str
    verdict: Verdict
    grounds: list[Ground] = Field(default_factory=list)
    scope: Scope = Scope.INSTALL
    confidence: Confidence
    covered_by: list[Citation] = Field(default_factory=list)
    contradicts: list[Citation] = Field(default_factory=list)
    gap: str | None = Field(default=None, description="What the project visibly lacks (ADD)")
    context_chars: int | None = Field(
        default=None, ge=0, description="Copied from the catalog; verify checks it"
    )
    always_on: bool | None = None
    risk: list[str] = Field(default_factory=list)
    evidence: EvidenceVerdict = "not_measured"
    reason: str = ""
    assessed_by: str | None = None
    assessed_at: str | None = None

    @field_validator("covered_by", "contradicts", mode="before")
    @classmethod
    def _paths_as_citations(cls, value: Any) -> Any:
        # The rubric allows a bare path; a bare path is a citation without a quote.
        if isinstance(value, list):
            return [{"path": v} if isinstance(v, str) else v for v in value]
        return value

    @property
    def citations(self) -> list[Citation]:
        return [*self.covered_by, *self.contradicts]


class DecisionRecord(BaseModel):
    """One file per assessment: `<project>/.agent-forge/decisions/<plan-id>.json`."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1"] = DECISION_SCHEMA_VERSION
    plan_id: str = Field(description="The dry-run plan the assessment was made against")
    target: str | None = Field(default=None, description="Project path as the agent saw it")
    platform: str | None = Field(default=None, description="Platform the assessment is for")
    assessed_by: str = Field(description="Model name / version that produced the record")
    assessed_at: str = Field(description="ISO-8601 date or timestamp")
    focus: str | None = Field(default=None, description="The user's focus argument, if any")
    decisions: list[Decision] = Field(default_factory=list)

    def digest(self) -> str:
        payload = self.model_dump(mode="json")
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def by_id(self) -> dict[str, Decision]:
        return {d.capability_id: d for d in self.decisions}
