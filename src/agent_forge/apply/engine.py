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


@dataclass
class PreflightReport:
    ok: bool
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: list[str] = field(default_factory=list)


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
    if plan.status != PlanStatus.APPROVED:
        rep.problems.append(
            f"plan status is {plan.status.value}; only approved plans can be applied"
        )
    if not plan.is_approved:
        rep.problems.append(
            "approval digest does not match the plan content (plan edited after approval?)"
        )
    elif recorded_digest != plan.content_digest():
        rep.problems.append(
            "approval is not recorded in this workspace for this plan content "
            "(plan edited or copied in after approval?)"
        )
    if plan.is_expired(datetime.now(UTC)):
        rep.problems.append(f"plan expired at {plan.expires_at} (stale); create a new plan")
    if plan.policy_digest is not None and policy_digest != plan.policy_digest:
        rep.problems.append("policy changed since the plan was created (stale)")
    root = Path(plan.target.canonical_path)
    if not root.is_dir():
        rep.problems.append(f"target no longer exists: {root}")
        rep.ok = False
        return rep
    if plan.registry_digest != reg.digest:
        msg = "registry changed since the plan was created"
        (rep.problems if require_registry_match else rep.warnings).append(msg)
    extra_ok = set(plan.approval.extra_approvals)
    # Operations on the same path are applied in order, so each one is checked against the
    # *projected* content left by the previous one, not against the file on disk.
    running: dict[str, str | None] = {}
    for op in plan.operations:
        if op.path not in running:
            try:
                current = _current_bytes(root, op.path)
            except SafetyViolation as exc:
                rep.problems.append(f"{op.op_id} {op.path}: {exc.message}")
                continue
            running[op.path] = (
                normalize_newlines(current.decode("utf-8", errors="replace"))
                if current is not None
                else None
            )
        current_text = running[op.path]
        current_hash = sha256_text(current_text) if current_text is not None else None
        if current_hash != op.before_sha256:
            rep.problems.append(f"{op.op_id} {op.path}: file changed since planning (stale)")
        else:
            try:
                running[op.path] = projected_content(op, current_text)
            except (ApplyError, ValueError) as exc:
                rep.problems.append(f"{op.op_id} {op.path}: cannot project content: {exc}")
        if op.platform is not None and not get_adapter(op.platform).path_allowed(op.path):
            rep.problems.append(
                f"{op.op_id} {op.path}: outside managed roots for {op.platform.value}"
            )
        if op.platform is None and not op.path.startswith(".agent-forge/"):
            rep.problems.append(
                f"{op.op_id} {op.path}: operation without platform may only touch .agent-forge/"
            )
        if op.requires_extra_approval and op.op_id not in extra_ok:
            rep.problems.append(
                f"{op.op_id} {op.path}: {op.approval_class} change needs explicit approval "
                f"(`approve --{op.approval_class.replace('_file', '-files').replace('_', '-')}`)"
            )
        if op.content is not None and op.content_sha256 != sha256_text(op.content):
            rep.problems.append(f"{op.op_id}: content hash mismatch (plan corrupted)")
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
        stale = any("stale" in p or "registry changed" in p for p in rep.problems)
        approval = any("approval" in p for p in rep.problems)
        exc_cls = StalePlanError if stale else ApprovalError if approval else ApplyError
        raise exc_cls(
            "pre-flight failed:\n  - " + "\n  - ".join(rep.problems),
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
