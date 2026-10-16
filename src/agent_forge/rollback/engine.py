"""Reverse a completed (or partial) transaction.

For each applied operation, newest first:
  current hash == after_sha256  -> safe: restore backup (or delete the file we created)
  current hash != after_sha256  -> conflict: the user changed it after apply; never overwritten
  file missing where we created -> already gone: nothing to do (noted)
By default any conflict aborts the whole rollback. `partial=True` rolls back the safe files
and reports the rest with a recovery recommendation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agent_forge import __version__
from agent_forge.apply.backup import BackupStore
from agent_forge.apply.filesystem_safety import assert_regular_file_or_missing, resolve_in_root
from agent_forge.apply.jsonmerge import contains_fragment, remove_fragment
from agent_forge.apply.sections import find_section, remove_section
from agent_forge.errors import ApplyError, PlanError, RollbackConflict, SafetyViolation
from agent_forge.models.plan import OperationKind
from agent_forge.models.transaction import AppliedOperation, Transaction, TransactionStatus
from agent_forge.storage.transactions import Store
from agent_forge.util import (
    atomic_write_bytes,
    new_id,
    normalize_newlines,
    now_iso,
    sha256_bytes,
    sha256_text,
)


@dataclass
class RollbackCheck:
    op: AppliedOperation
    action: str  # restore | delete | skip | conflict
    detail: str = ""


@dataclass
class RollbackPlan:
    transaction: Transaction
    checks: list[RollbackCheck] = field(default_factory=list)

    @property
    def conflicts(self) -> list[RollbackCheck]:
        return [c for c in self.checks if c.action == "conflict"]

    @property
    def actionable(self) -> list[RollbackCheck]:
        return [
            c
            for c in self.checks
            if c.action in ("restore", "delete", "remove_section", "remove_json")
        ]


def _current(root: Path, rel: str) -> tuple[bytes | None, str | None]:
    p = resolve_in_root(root, rel)
    assert_regular_file_or_missing(p)
    if not p.exists():
        return None, None
    data = p.read_bytes()
    return data, sha256_text(normalize_newlines(data.decode("utf-8", errors="replace")))


def plan_rollback(store: Store, tx: Transaction) -> RollbackPlan:
    if not tx.integrity_ok():
        raise PlanError(
            f"transaction {tx.transaction_id} record integrity check failed; refusing to roll back"
        )
    if tx.status in (TransactionStatus.ROLLED_BACK,):
        raise PlanError(f"transaction {tx.transaction_id} was already rolled back")
    if tx.status not in (
        TransactionStatus.COMPLETED,
        TransactionStatus.PARTIAL,
        TransactionStatus.ROLLBACK_CONFLICT,
    ):
        raise PlanError(
            f"transaction {tx.transaction_id} is {tx.status.value}; nothing to roll back"
        )
    root = Path(tx.target_canonical_path)
    if not root.is_dir():
        raise PlanError(f"target no longer exists: {root}")
    backups = BackupStore(store.backup_dir(tx.transaction_id))
    rp = RollbackPlan(transaction=tx)
    for op in reversed(tx.operations):
        if not op.applied:
            continue
        try:
            _, cur_hash = _current(root, op.path)
        except SafetyViolation as exc:
            rp.checks.append(RollbackCheck(op, "conflict", f"unsafe path now: {exc.message}"))
            continue
        if op.after_sha256 is None:
            # we removed the file
            if cur_hash is not None:
                rp.checks.append(RollbackCheck(op, "conflict", "file was re-created after removal"))
            elif op.backup and backups.exists(op.backup):
                rp.checks.append(RollbackCheck(op, "restore", "restore removed file from backup"))
            else:
                rp.checks.append(
                    RollbackCheck(op, "conflict", "no backup available for removed file")
                )
            continue
        if cur_hash is None:
            rp.checks.append(RollbackCheck(op, "skip", "file already removed by the user"))
            continue
        if cur_hash != op.after_sha256:
            if op.kind == OperationKind.MERGE_SECTION and op.section_id:
                # Shared file changed outside our markers: remove only the managed section.
                data, _ = _current(root, op.path)
                text = normalize_newlines((data or b"").decode("utf-8", errors="replace"))
                try:
                    info = find_section(text, op.section_id)
                except ApplyError as exc:
                    rp.checks.append(RollbackCheck(op, "conflict", exc.message))
                    continue
                if info is None:
                    rp.checks.append(
                        RollbackCheck(op, "skip", "managed section already removed by the user")
                    )
                else:
                    rp.checks.append(
                        RollbackCheck(
                            op,
                            "remove_section",
                            "file edited outside the managed section; removing only the section",
                        )
                    )
                continue
            if op.kind == OperationKind.MERGE_JSON and op.fragment:
                data, _ = _current(root, op.path)
                text = normalize_newlines((data or b"").decode("utf-8", errors="replace"))
                try:
                    present = contains_fragment(text, op.fragment)
                except ApplyError as exc:
                    rp.checks.append(RollbackCheck(op, "conflict", exc.message))
                    continue
                if not present:
                    rp.checks.append(
                        RollbackCheck(op, "skip", "merged entries already removed by the user")
                    )
                else:
                    rp.checks.append(
                        RollbackCheck(
                            op,
                            "remove_json",
                            "settings edited outside our entries; removing only our entries",
                        )
                    )
                continue
            rp.checks.append(
                RollbackCheck(op, "conflict", "modified after apply; keeping your version")
            )
            continue
        if op.before_sha256 is None:
            rp.checks.append(RollbackCheck(op, "delete", "created by this transaction"))
        elif op.backup and backups.exists(op.backup):
            rp.checks.append(RollbackCheck(op, "restore", "restore pre-apply content from backup"))
        else:
            rp.checks.append(RollbackCheck(op, "conflict", "backup missing; cannot restore safely"))
    return rp


def execute_rollback(store: Store, rp: RollbackPlan, *, partial: bool = False) -> Transaction:
    tx = rp.transaction
    if rp.conflicts and not partial:
        lines = [f"{c.op.path}: {c.detail}" for c in rp.conflicts]
        raise RollbackConflict(
            "rollback refused; files changed independently after apply:\n  - "
            + "\n  - ".join(lines),
            hint="Review those files manually, then re-run with --partial to roll back the untouched ones.",
        )
    root = Path(tx.target_canonical_path)
    backups = BackupStore(store.backup_dir(tx.transaction_id))
    rb = Transaction(
        transaction_id=new_id("rb"),
        plan_id=tx.plan_id,
        plan_digest=tx.plan_digest,
        forge_version=__version__,
        target_canonical_path=tx.target_canonical_path,
        started_at=now_iso(),
        rollback_of=tx.transaction_id,
        capabilities=dict(tx.capabilities),
    )
    store.save_transaction(rb)
    try:
        for check in rp.checks:
            rec = AppliedOperation(
                op_id=check.op.op_id,
                kind=check.op.kind,
                path=check.op.path,
                capability_id=check.op.capability_id,
                section_id=check.op.section_id,
            )
            rb.operations.append(rec)
            if check.action in ("skip", "conflict"):
                rec.error = check.detail
                continue
            dest = resolve_in_root(root, check.op.path)
            assert_regular_file_or_missing(dest)
            data_now, cur_hash = _current(root, check.op.path)
            if check.action in ("remove_section", "remove_json"):
                text = normalize_newlines((data_now or b"").decode("utf-8", errors="replace"))
                if check.action == "remove_section":
                    assert check.op.section_id
                    new_text = remove_section(text, check.op.section_id)
                else:
                    assert check.op.fragment is not None
                    new_text = remove_fragment(text, check.op.fragment, path_hint=check.op.path)
                rec.before_sha256 = cur_hash
                if new_text == "":
                    dest.unlink()
                    rec.after_sha256 = None
                else:
                    atomic_write_bytes(dest, new_text.encode("utf-8"))
                    rec.after_sha256 = sha256_text(new_text)
                rec.applied = True
                store.save_transaction(rb)
                continue
            if cur_hash != check.op.after_sha256:
                raise RollbackConflict(f"{check.op.path} changed during rollback; aborting")
            rec.before_sha256 = cur_hash
            if check.action == "delete":
                dest.unlink()
                rec.after_sha256 = None
                _prune(root, dest.parent)
            else:
                assert check.op.backup
                data = backups.load(check.op.backup)
                if (
                    sha256_text(normalize_newlines(data.decode("utf-8", errors="replace")))
                    != check.op.before_sha256
                ):
                    raise RollbackConflict(
                        f"backup for {check.op.path} does not match its recorded hash; refusing"
                    )
                atomic_write_bytes(dest, data)
                if sha256_bytes(dest.read_bytes()) != sha256_bytes(data):
                    raise RollbackConflict(f"{check.op.path}: read-back verification failed")
                rec.after_sha256 = check.op.before_sha256
            rec.applied = True
            store.save_transaction(rb)
    except Exception as exc:
        rb.status = (
            TransactionStatus.PARTIAL
            if any(o.applied for o in rb.operations)
            else TransactionStatus.FAILED
        )
        rb.finished_at = now_iso()
        rb.notes.append(f"aborted: {exc}")
        store.save_transaction(rb)
        raise
    rb.status = TransactionStatus.COMPLETED
    rb.finished_at = now_iso()
    if rp.conflicts:
        rb.notes.append(
            "partial rollback: " + "; ".join(f"{c.op.path} kept ({c.detail})" for c in rp.conflicts)
        )
    store.save_transaction(rb)
    tx.status = (
        TransactionStatus.ROLLBACK_CONFLICT if rp.conflicts else TransactionStatus.ROLLED_BACK
    )
    tx.notes.append(f"rolled back by {rb.transaction_id}" + (" (partial)" if rp.conflicts else ""))
    store.save_transaction(tx)
    return rb


def _prune(root: Path, directory: Path) -> None:
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
