"""Render a plan as unified diffs against the *current* state of the target."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path

from agent_forge.apply.filesystem_safety import resolve_in_root
from agent_forge.apply.sections import remove_section, upsert_section
from agent_forge.errors import SafetyViolation
from agent_forge.models.plan import FileOperation, OperationKind, Plan
from agent_forge.util import normalize_newlines, sha256_text


@dataclass
class OpDiff:
    op: FileOperation
    current_sha256: str | None
    stale: bool
    unified: str
    summary: str
    warnings: list[str] = field(default_factory=list)


def _read_current(root: Path, rel: str) -> tuple[str | None, list[str]]:
    warnings: list[str] = []
    try:
        p = resolve_in_root(root, rel)
    except SafetyViolation as exc:
        return None, [f"unsafe path: {exc.message}"]
    if not p.exists():
        return None, warnings
    if p.is_symlink() or not p.is_file():
        return None, ["destination exists but is not a regular file"]
    try:
        return normalize_newlines(p.read_text(encoding="utf-8")), warnings
    except (OSError, UnicodeDecodeError) as exc:
        return None, [f"cannot read destination: {exc}"]


def projected_content(op: FileOperation, current: str | None) -> str | None:
    """What the file will contain after the operation (None = removed)."""
    if op.kind in (OperationKind.CREATE, OperationKind.REPLACE, OperationKind.MANIFEST):
        return op.content or ""
    if op.kind == OperationKind.MERGE_SECTION:
        assert op.section_id and op.capability_id and op.capability_version
        return upsert_section(
            current, op.section_id, op.capability_id, op.capability_version, op.content or ""
        )
    if op.kind == OperationKind.REMOVE_SECTION:
        assert op.section_id
        return remove_section(current or "", op.section_id)
    if op.kind == OperationKind.REMOVE:
        return None
    raise ValueError(f"unknown operation kind {op.kind}")


def diff_operation(root: Path, op: FileOperation, *, context: int = 3) -> OpDiff:
    current, warnings = _read_current(root, op.path)
    current_sha = sha256_text(current) if current is not None else None
    stale = current_sha != op.before_sha256
    new = projected_content(op, current)
    a = (current or "").splitlines(keepends=True)
    b = (new or "").splitlines(keepends=True)
    from_name = f"a/{op.path}" if current is not None else "/dev/null"
    to_name = f"b/{op.path}" if new is not None else "/dev/null"
    unified = "".join(difflib.unified_diff(a, b, fromfile=from_name, tofile=to_name, n=context))
    if current is None and new is not None:
        summary = f"create {op.path} ({len(b)} lines)"
    elif new is None:
        summary = f"remove {op.path}"
    elif op.kind in (OperationKind.MERGE_SECTION, OperationKind.REMOVE_SECTION):
        summary = f"{op.kind.value} {op.path} [section {op.section_id}]"
    else:
        summary = f"{op.kind.value} {op.path}"
    if stale:
        warnings.append(
            "current file differs from what the plan expected (plan is stale for this file)"
        )
    return OpDiff(
        op=op,
        current_sha256=current_sha,
        stale=stale,
        unified=unified,
        summary=summary,
        warnings=warnings,
    )


def render_plan_diff(plan: Plan, root: Path) -> list[OpDiff]:
    return [diff_operation(root, op) for op in plan.operations]
