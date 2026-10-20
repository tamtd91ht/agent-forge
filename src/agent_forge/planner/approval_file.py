"""Approval files: a reviewed, committed statement of what may be applied without a person.

A plan is bound to one machine (canonical path, file hashes), so an approval recorded on a
developer's workstation cannot travel to CI. What can travel is the *content* decision: these
capability ids at these versions, with these approval classes, optionally only for this
registry digest. A team reviews that once, commits it next to the project
(`.agent-forge/approval.yaml`), and `approve --approval-file` / `forge --approval-file`
accept a plan only when it stays inside it. Anything outside (a new capability, a newer
version, a hook the file never mentioned) is refused with exit 14, which is the CI gate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from agent_forge.errors import ApprovalFileMismatch, UsageError
from agent_forge.models.capability import SEMVER_RE
from agent_forge.models.plan import Plan

APPROVAL_CLASSES = ("shared_file", "hook", "mcp")
ANY_VERSION = "*"


class ApprovalFile(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    version: Literal[1] = 1
    approved_by: str
    approved_at: str = Field(description="ISO-8601 date or timestamp")
    note: str | None = None
    registry_digest: str | None = Field(
        default=None, description="If set, the plan must have been built from this registry"
    )
    classes: list[str] = Field(
        default_factory=list, description="Approval classes granted: shared_file, hook, mcp"
    )
    capabilities: dict[str, str] = Field(
        default_factory=dict, description="capability id -> exact version or '*'"
    )

    @field_validator("classes")
    @classmethod
    def _known_classes(cls, v: list[str]) -> list[str]:
        unknown = sorted(set(v) - set(APPROVAL_CLASSES))
        if unknown:
            raise ValueError(f"unknown approval classes: {', '.join(unknown)}")
        return sorted(set(v))

    @field_validator("capabilities")
    @classmethod
    def _versions(cls, v: dict[str, str]) -> dict[str, str]:
        for cid, ver in v.items():
            if ver != ANY_VERSION and not SEMVER_RE.match(str(ver)):
                raise ValueError(f"{cid}: version must be MAJOR.MINOR.PATCH or '*', got {ver!r}")
        return {k: str(val) for k, val in v.items()}

    def granted(self, klass: str) -> bool:
        return klass in self.classes


def load_approval_file(path: Path) -> ApprovalFile:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UsageError(f"cannot read approval file {path}: {exc}") from exc
    try:
        raw = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    except (ValueError, yaml.YAMLError) as exc:
        raise UsageError(f"approval file {path} is not valid YAML/JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise UsageError(f"approval file {path} must contain a mapping")
    try:
        return ApprovalFile.model_validate(raw)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        raise UsageError(f"approval file {path} is invalid: {details}") from exc


def check_plan_against_approval(plan: Plan, approval: ApprovalFile) -> list[str]:
    """Return every way the plan exceeds the approval (empty = the plan is covered)."""
    problems: list[str] = []
    if approval.registry_digest and approval.registry_digest != plan.registry_digest:
        problems.append(
            f"registry digest {plan.registry_digest[:16]} differs from the approved "
            f"{approval.registry_digest[:16]}"
        )
    for sel in plan.selected:
        want = approval.capabilities.get(sel.capability_id)
        if want is None:
            problems.append(f"{sel.capability_id} {sel.version} is not in the approval file")
        elif want != ANY_VERSION and want != sel.version:
            problems.append(f"{sel.capability_id}: plan has {sel.version}, approved {want}")
    needed: dict[str, set[str]] = {}
    for op in plan.operations_needing_extra_approval():
        if not approval.granted(op.approval_class):
            needed.setdefault(op.approval_class, set()).add(op.path)
    for klass, paths in sorted(needed.items()):
        problems.append(f"class {klass} not granted (needed for {', '.join(sorted(paths))})")
    return problems


def require_plan_covered(plan: Plan, approval: ApprovalFile, source: str) -> None:
    problems = check_plan_against_approval(plan, approval)
    if problems:
        raise ApprovalFileMismatch(
            f"plan {plan.plan_id} is not covered by {source}: " + "; ".join(problems),
            hint="Review the plan, then update the approval file (a reviewed commit) or "
            "exclude the capability.",
        )


def approval_from_plan(plan: Plan, *, by: str, classes: list[str], note: str | None) -> dict:
    """Approval-file content covering exactly this plan (versions pinned)."""
    caps = {s.capability_id: s.version for s in plan.selected}
    for op in plan.operations:
        if op.capability_id and op.capability_version and op.capability_id not in caps:
            caps[op.capability_id] = op.capability_version
    return {
        "version": 1,
        "approved_by": by,
        "approved_at": plan.approval.approved_at or plan.created_at,
        "note": note or f"exported from plan {plan.plan_id}",
        "registry_digest": None,
        "classes": sorted({c for c in classes if c in APPROVAL_CLASSES}),
        "capabilities": dict(sorted(caps.items())),
    }
