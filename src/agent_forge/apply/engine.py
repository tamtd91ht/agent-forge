"""Apply an approved plan inside a transaction.

Pre-flight (all must pass before the first write):
  plan schema valid, status approved, approval digest == current digest
  approval recorded in this workspace for exactly this digest, plan not expired
  target exists, registry digest unchanged, effective policy unchanged
  every operation: safe path, adapter-managed root, current hash == before_sha256
  every shared-file operation explicitly approved
Then, under the target lock, per operation: re-check hash -> backup -> journal (record
saved with the intended hash) -> re-check path -> atomic write -> read-back -> record.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from agent_forge import __version__
from agent_forge.adapters import get_adapter
from agent_forge.apply.backup import BackupStore
from agent_forge.apply.filesystem_safety import (
    assert_regular_file_or_missing,
    resolve_in_root,
    safe_write_bytes,
)
from agent_forge.apply.jsonmerge import parse_fragment
from agent_forge.config import WorkspaceConfig
from agent_forge.errors import ApplyError, ApprovalError, SafetyViolation, StalePlanError
from agent_forge.models.plan import OperationKind, Plan, PlanStatus
from agent_forge.models.transaction import AppliedOperation, Transaction, TransactionStatus
from agent_forge.planner.builder import transaction_id_for
from agent_forge.planner.diff import projected_content
from agent_forge.policy.engine import load_policies
from agent_forge.registry.loader import Registry
from agent_forge.storage.locks import target_lock
from agent_forge.storage.transactions import Store
from agent_forge.util import (
    normalize_newlines,
    now_iso,
    sha256_bytes,
    sha256_text,
)


class ProblemCode(StrEnum):
    """Why an approved plan cannot be applied. The code, not the message, picks the exit code."""

    NOT_APPROVED = "not_approved"  # plan status is not `approved`
    APPROVAL_MISMATCH = "approval_mismatch"  # approval digest != plan content (plan edited)
    APPROVAL_NOT_RECORDED = "approval_not_recorded"  # workspace has no matching approval
    EXTRA_APPROVAL_REQUIRED = (
        "extra_approval_required"  # shared-file / hook / MCP class not granted
    )
    EXPIRED = "expired"
    POLICY_CHANGED = "policy_changed"
    REGISTRY_CHANGED = "registry_changed"
    FILE_CHANGED = "file_changed"  # destination differs from what the plan expected
    TARGET_MISSING = "target_missing"
    UNSAFE_PATH = "unsafe_path"
    PROJECTION_FAILED = "projection_failed"  # section / JSON merge cannot be computed
    OUTSIDE_MANAGED_ROOTS = "outside_managed_roots"
    CONTENT_HASH_MISMATCH = "content_hash_mismatch"  # plan file corrupted


# Which error (and exit code) a code maps to. Stale beats approval beats everything else, so a
# plan that is both outdated and unapproved tells the user to re-plan first.
STALE_CODES = frozenset(
    {
        ProblemCode.EXPIRED,
        ProblemCode.POLICY_CHANGED,
        ProblemCode.REGISTRY_CHANGED,
        ProblemCode.FILE_CHANGED,
    }
)
APPROVAL_CODES = frozenset(
    {
        ProblemCode.NOT_APPROVED,
        ProblemCode.APPROVAL_MISMATCH,
        ProblemCode.APPROVAL_NOT_RECORDED,
        ProblemCode.EXTRA_APPROVAL_REQUIRED,
    }
)


@dataclass(frozen=True)
class Problem:
    code: ProblemCode
    message: str
    op_id: str | None = None
    path: str | None = None

    def __str__(self) -> str:
        prefix = " ".join(x for x in (self.op_id, self.path) if x)
        return f"{prefix}: {self.message}" if prefix else self.message

    def to_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code.value,
            "op_id": self.op_id,
            "path": self.path,
            "message": self.message,
        }


def error_for(problems: list[Problem]) -> type[ApplyError]:
    """The exception class (hence exit code) for a failed pre-flight."""
    codes = {p.code for p in problems}
    if codes & STALE_CODES:
        return StalePlanError
    if codes & APPROVAL_CODES:
        return ApprovalError
    return ApplyError


@dataclass
class PreflightReport:
    ok: bool
    problems: list[Problem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: list[str] = field(default_factory=list)

    @property
    def messages(self) -> list[str]:
        return [str(p) for p in self.problems]

    def codes(self) -> list[str]:
        return sorted({p.code.value for p in self.problems})


def _current_bytes(root: Path, rel: str) -> bytes | None:
    p = resolve_in_root(root, rel)
    assert_regular_file_or_missing(p)
    return p.read_bytes() if p.exists() else None


def preflight(
    plan: Plan,
    reg: Registry,
    *,
    require_registry_match: bool = True,
    recorded_digest: str | None = None,
    policy_digest: str | None = None,
) -> PreflightReport:
    """Check everything an approved plan depends on, without writing anything.

    `recorded_digest` is the digest `approve` recorded in the workspace and `policy_digest`
    the digest of the policy in force now; `apply_plan` always supplies both.
    """
    rep = PreflightReport(ok=True)
    problem = rep.problems.append
    if plan.status != PlanStatus.APPROVED:
        problem(
            Problem(
                ProblemCode.NOT_APPROVED,
                f"plan status is {plan.status.value}; only approved plans can be applied",
            )
        )
    if not plan.is_approved:
        problem(
            Problem(
                ProblemCode.APPROVAL_MISMATCH,
                "approval digest does not match the plan content (plan edited after approval?)",
            )
        )
    elif recorded_digest != plan.content_digest():
        problem(
            Problem(
                ProblemCode.APPROVAL_NOT_RECORDED,
                "approval is not recorded in this workspace for this plan content "
                "(plan edited or copied in after approval?)",
            )
        )
    if plan.is_expired(datetime.now(UTC)):
        problem(
            Problem(
                ProblemCode.EXPIRED,
                f"plan expired at {plan.expires_at} (stale); create a new plan",
            )
        )
    if plan.policy_digest is not None and policy_digest != plan.policy_digest:
        problem(
            Problem(ProblemCode.POLICY_CHANGED, "policy changed since the plan was created (stale)")
        )
    root = Path(plan.target.canonical_path)
    if not root.is_dir():
        problem(Problem(ProblemCode.TARGET_MISSING, f"target no longer exists: {root}"))
        rep.ok = False
        return rep
    if plan.registry_digest != reg.digest:
        msg = "registry changed since the plan was created (stale)"
        if require_registry_match:
            problem(Problem(ProblemCode.REGISTRY_CHANGED, msg))
        else:
            rep.warnings.append(msg)
    extra_ok = set(plan.approval.extra_approvals)
    # Operations on the same path are applied in order, so each one is checked against the
    # *projected* content left by the previous one, not against the file on disk.
    running: dict[str, str | None] = {}
    for op in plan.operations:
        if op.path not in running:
            try:
                current = _current_bytes(root, op.path)
            except SafetyViolation as exc:
                problem(Problem(ProblemCode.UNSAFE_PATH, exc.message, op.op_id, op.path))
                continue
            running[op.path] = (
                normalize_newlines(current.decode("utf-8", errors="replace"))
                if current is not None
                else None
            )
        current_text = running[op.path]
        current_hash = sha256_text(current_text) if current_text is not None else None
        if current_hash != op.before_sha256:
            problem(
                Problem(
                    ProblemCode.FILE_CHANGED,
                    "file changed since planning (stale)",
                    op.op_id,
                    op.path,
                )
            )
        else:
            try:
                running[op.path] = projected_content(op, current_text)
            except (ApplyError, ValueError) as exc:
                problem(
                    Problem(
                        ProblemCode.PROJECTION_FAILED,
                        f"cannot project content: {exc}",
                        op.op_id,
                        op.path,
                    )
                )
        if op.platform is not None and not get_adapter(op.platform).path_allowed(op.path):
            problem(
                Problem(
                    ProblemCode.OUTSIDE_MANAGED_ROOTS,
                    f"outside managed roots for {op.platform.value}",
                    op.op_id,
                    op.path,
                )
            )
        if op.platform is None and not op.path.startswith(".agent-forge/"):
            problem(
                Problem(
                    ProblemCode.OUTSIDE_MANAGED_ROOTS,
                    "operation without platform may only touch .agent-forge/",
                    op.op_id,
                    op.path,
                )
            )
        if op.requires_extra_approval and op.op_id not in extra_ok:
            flag = "--" + op.approval_class.replace("_file", "-files").replace("_", "-")
            problem(
                Problem(
                    ProblemCode.EXTRA_APPROVAL_REQUIRED,
                    f"{op.approval_class} change needs explicit approval (`approve {flag}`)",
                    op.op_id,
                    op.path,
                )
            )
        if op.content is not None and op.content_sha256 != sha256_text(op.content):
            problem(
                Problem(
                    ProblemCode.CONTENT_HASH_MISMATCH,
                    "content hash mismatch (plan corrupted)",
                    op.op_id,
                    op.path,
                )
            )
        rep.summary.append(f"{op.kind.value:14} {op.path}")
    rep.ok = not rep.problems
    return rep


def apply_plan(
    ws: WorkspaceConfig,
    store: Store,
    reg: Registry,
    plan: Plan,
    *,
    confirm: Callable[[PreflightReport], bool] | None = None,
) -> Transaction:
    """Pre-flight, then write every operation inside a journaled transaction.

    Runs under the target's exclusive lock, so pre-flight checks and writes see the same
    project state and no other apply or rollback can interleave.
    """
    with target_lock(ws, plan.target.canonical_path, f"apply {plan.plan_id}"):
        return _apply_locked(ws, store, reg, plan, confirm)


def _apply_locked(
    ws: WorkspaceConfig,
    store: Store,
    reg: Registry,
    plan: Plan,
    confirm: Callable[[PreflightReport], bool] | None,
) -> Transaction:
    target = Path(plan.target.canonical_path)
    policies = load_policies(ws.registry_dir, ws.root, target if target.is_dir() else None)
    rep = preflight(
        plan,
        reg,
        recorded_digest=store.recorded_approval_digest(plan.plan_id),
        policy_digest=policies.digest,
    )
    if not rep.ok:
        raise error_for(rep.problems)(
            "pre-flight failed:\n  - " + "\n  - ".join(rep.messages),
            hint="Re-run `assign`/`upgrade` to create a fresh plan, then `approve` it.",
        )
    if confirm is not None and not confirm(rep):
        raise ApplyError("apply cancelled by user")

    root = target
    tx_id = transaction_id_for(plan.plan_id)
    if store.transaction_path(tx_id).exists():
        raise ApplyError(
            f"transaction {tx_id} already exists; this plan was applied (or attempted) before",
            hint="Create a new plan.",
        )
    backups = BackupStore(store.backup_dir(tx_id))
    tx = Transaction(
        transaction_id=tx_id,
        plan_id=plan.plan_id,
        plan_digest=plan.content_digest(),
        forge_version=__version__,
        registry_digest=plan.registry_digest,
        profile_fingerprint=plan.target.profile_fingerprint,
        target_canonical_path=plan.target.canonical_path,
        started_at=now_iso(),
        capabilities={s.capability_id: s.version for s in plan.selected},
    )
    store.save_transaction(tx)
    applied_at = now_iso()
    try:
        for op in plan.operations:
            rec = AppliedOperation(
                op_id=op.op_id,
                kind=op.kind,
                path=op.path,
                capability_id=op.capability_id,
                section_id=op.section_id,
                fragment=parse_fragment(op.content or "{}")
                if op.kind == OperationKind.MERGE_JSON
                else None,
            )
            tx.operations.append(rec)
            dest = resolve_in_root(root, op.path)
            assert_regular_file_or_missing(dest)
            current = dest.read_bytes() if dest.exists() else None
            current_norm = (
                normalize_newlines(current.decode("utf-8", errors="replace"))
                if current is not None
                else None
            )
            current_hash = sha256_text(current_norm) if current_norm is not None else None
            if current_hash != op.before_sha256:
                raise StalePlanError(f"{op.path} changed between pre-flight and write; aborting")
            rec.before_sha256 = current_hash
            if current is not None:
                rec.backup, rec.backup_sha256 = backups.save(op.path, current)
            new_text = projected_content(op, current_norm)
            if op.kind == OperationKind.MANIFEST and new_text is not None:
                new_text = _stamp_manifest(new_text, applied_at)
            # Journal before touching the file: a crash from here on leaves a record that
            # says what was about to change, with its backup, so rollback can recover it.
            rec.intended_after_sha256 = sha256_text(new_text) if new_text is not None else None
            rec.journaled = True
            store.save_transaction(tx)
            # Re-check right before the write: nothing may have been swapped for a link since.
            dest = resolve_in_root(root, op.path)
            assert_regular_file_or_missing(dest)
            if new_text is None:
                dest.unlink()
                rec.after_sha256 = None
                _prune_empty_dirs(root, dest.parent)
            else:
                data = new_text.encode("utf-8")
                safe_write_bytes(root, op.path, data)
                rec.after_sha256 = rec.intended_after_sha256
                if (
                    op.after_sha256
                    and op.kind != OperationKind.MANIFEST
                    and rec.after_sha256 != op.after_sha256
                ):
                    raise ApplyError(
                        f"{op.path}: written content hash differs from plan expectation"
                    )
                written = sha256_bytes(dest.read_bytes())
                if written != sha256_bytes(data):
                    raise ApplyError(f"{op.path}: read-back verification failed")
            rec.applied = True
            store.save_transaction(tx)
    except Exception as exc:
        tx.status = (
            TransactionStatus.PARTIAL
            if any(o.applied or o.journaled for o in tx.operations)
            else TransactionStatus.FAILED
        )
        tx.finished_at = now_iso()
        if tx.operations and not tx.operations[-1].applied:
            tx.operations[-1].error = str(exc)
        tx.notes.append(f"aborted: {exc}")
        record_error = None
        try:
            store.save_transaction(tx)
            plan.status = PlanStatus.FAILED
            plan.transaction_id = tx_id
            store.save_plan(plan)
        except Exception as save_exc:  # keep the original failure visible
            record_error = save_exc
        hint = f"Run `agent-forge rollback {tx_id}` to restore what was written."
        if record_error is not None:
            raise ApplyError(
                f"apply failed: {exc}; the transaction record could not be updated either "
                f"({record_error}), so it still reads in_progress",
                hint=hint + " The journal written before each write lets rollback recover it.",
            ) from exc
        if isinstance(exc, (ApplyError, StalePlanError, SafetyViolation)):
            if exc.hint is None:
                exc.hint = hint
            raise
        raise ApplyError(f"apply failed: {exc}", hint=hint) from exc
    tx.status = TransactionStatus.COMPLETED
    tx.finished_at = now_iso()
    store.save_transaction(tx)
    plan.status = PlanStatus.APPLIED
    plan.transaction_id = tx_id
    store.save_plan(plan)
    return tx


def _stamp_manifest(text: str, applied_at: str) -> str:
    """Replace the plan-time placeholder installed_at with the real timestamp."""
    try:
        data = json.loads(text)
    except ValueError:
        return text
    for rec in data.get("capabilities", []):
        if rec.get("installed_at") == "(set at apply time)":
            rec["installed_at"] = applied_at
    return json.dumps(data, indent=2, sort_keys=False) + "\n"


def _prune_empty_dirs(root: Path, directory: Path) -> None:
    """Remove now-empty directories up to (not including) the target root."""
    real_root = root.resolve()
    cur = directory
    while cur != real_root and real_root in cur.parents:
        try:
            if any(cur.iterdir()):
                return
            cur.rmdir()
        except OSError:
            return
        cur = cur.parent
