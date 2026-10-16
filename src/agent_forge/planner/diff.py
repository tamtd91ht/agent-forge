"""Render a plan as unified diffs against the *current* state of the target."""

from __future__ import annotations

import contextlib
import difflib
import json
from dataclasses import dataclass, field
from pathlib import Path

from agent_forge.apply.filesystem_safety import resolve_in_root
from agent_forge.apply.jsonmerge import parse_fragment, remove_fragment, replace_fragment
from agent_forge.apply.sections import remove_section, upsert_section
from agent_forge.errors import ApplyError, SafetyViolation
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
    if op.kind == OperationKind.MERGE_JSON:
        new = parse_fragment(op.content or "{}")
        old = json.loads(op.previous_content) if op.previous_content else None
        return replace_fragment(current, old, new, path_hint=op.path)
    if op.kind == OperationKind.REMOVE_JSON:
        return remove_fragment(current, parse_fragment(op.content or "{}"), path_hint=op.path)
    if op.kind == OperationKind.REMOVE:
        return None
    raise ValueError(f"unknown operation kind {op.kind}")


def diff_operation(
    root: Path,
    op: FileOperation,
    *,
    context: int = 3,
    current_override: tuple[str | None] | None = None,
) -> OpDiff:
    if current_override is not None:
        current, warnings = current_override[0], []
    else:
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
    """Diff every operation; operations on the same path are chained in plan order."""
    out: list[OpDiff] = []
    running: dict[str, str | None] = {}
    for op in plan.operations:
        if op.path in running:
            d = diff_operation(root, op, current_override=(running[op.path],))
        else:
            d = diff_operation(root, op)
            cur, _ = _read_current(root, op.path)
            running[op.path] = cur
        if not d.stale:
            with contextlib.suppress(ApplyError, ValueError):
                running[op.path] = projected_content(op, running[op.path])
        out.append(d)
    return out
