"""Crash, failure and concurrency behaviour of apply/rollback (roadmap B1-B6, C1, C3).

Each test snapshots the target, breaks apply at one boundary, and checks that the failure is
recorded, detected, and that rollback brings the project back byte for byte.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import agent_forge.apply.engine as engine
import agent_forge.rollback.engine as rollback_engine
from agent_forge.apply.backup import BackupStore
from agent_forge.apply.engine import apply_plan
from agent_forge.errors import ApplyError, RollbackConflict, StalePlanError
from agent_forge.matching.rules import MatchContext
from agent_forge.models.capability import Platform
from agent_forge.models.plan import PlanStatus
from agent_forge.models.transaction import TransactionStatus
from agent_forge.planner.builder import build_assign_plan, transaction_id_for
from agent_forge.registry.loader import load_registry
from agent_forge.rollback.engine import execute_rollback, plan_rollback
from agent_forge.scanner.project_profile import scan_project
from agent_forge.storage.locks import lock_path, target_lock
from agent_forge.storage.transactions import Store
from agent_forge.util import now_iso
from agent_forge.validation.engine import validate_target


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".git" not in p.relative_to(root).parts
    }


def _approved_plan(workspace, root: Path):
    reg = load_registry(workspace.registry_dir)
    plan, _ = build_assign_plan(
        reg, scan_project(root), MatchContext(platforms=(Platform.CLAUDE_CODE,))
    )
    store = Store(workspace)
    plan.approval.status = "approved"
    plan.approval.approved_at = now_iso()
    plan.approval.plan_digest = plan.content_digest()
    plan.approval.extra_approvals = [o.op_id for o in plan.operations_needing_extra_approval()]
    plan.status = PlanStatus.APPROVED
    store.save_plan(plan)
    store.record_approval(plan)
    return reg, store, plan


def _recover(workspace, store: Store, plan) -> None:
    tx = store.load_transaction(transaction_id_for(plan.plan_id))
    execute_rollback(store, plan_rollback(store, tx))


def test_crash_mid_apply_is_journaled_and_recoverable(workspace, make_project, monkeypatch):
    root = make_project("crash", kind="claude")
    before = _snapshot(root)
    reg, store, plan = _approved_plan(workspace, root)
    real = engine.safe_write_bytes
    calls = {"n": 0}

    def write_then_die(r, rel, data):
        calls["n"] += 1
        out = real(r, rel, data)
        if calls["n"] == 2:
            raise KeyboardInterrupt  # the process stops right after the write landed
        return out

    monkeypatch.setattr(engine, "safe_write_bytes", write_then_die)
    with pytest.raises(KeyboardInterrupt):
        apply_plan(workspace, store, reg, plan)
    monkeypatch.undo()

    tx = store.load_transaction(transaction_id_for(plan.plan_id))
    assert tx.status == TransactionStatus.IN_PROGRESS
    in_flight = [o for o in tx.operations if o.journaled and not o.applied]
    assert len(in_flight) == 1 and in_flight[0].intended_after_sha256
    # detected everywhere a user would look
    assert store.recovery_reason(tx) == "interrupted while applying (process stopped)"
    rep = validate_target(workspace, reg, store, scan_project(root))
    assert any("interrupted" in f.message for f in rep.errors)
    # and recoverable: the journaled-but-unrecorded write is reversed too
    _recover(workspace, store, plan)
    assert _snapshot(root) == before
    assert store.recovery_reason(store.load_transaction(tx.transaction_id)) is None


def test_stale_lock_of_a_dead_process_is_taken_over(workspace, make_project):
    root = make_project("stale-lock", kind="claude")
    reg, store, plan = _approved_plan(workspace, root)
    path = lock_path(workspace, plan.target.canonical_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"pid": 999999999, "purpose": "apply (killed)"}', encoding="utf-8")
    tx = apply_plan(workspace, store, reg, plan)
    assert tx.status == TransactionStatus.COMPLETED
    assert not path.exists()


def test_concurrent_apply_is_refused(workspace, make_project):
    root = make_project("concurrent", kind="claude")
    before = _snapshot(root)
    reg, store, plan = _approved_plan(workspace, root)
    with target_lock(workspace, plan.target.canonical_path, "another apply"):
        with pytest.raises(ApplyError, match="another Agent Forge process"):
            apply_plan(workspace, store, reg, plan)
        assert _snapshot(root) == before
    assert apply_plan(workspace, store, reg, plan).status == TransactionStatus.COMPLETED


def test_original_error_survives_record_save_failure(workspace, make_project, monkeypatch):
    root = make_project("double-fault", kind="claude")
    before = _snapshot(root)
    reg, store, plan = _approved_plan(workspace, root)
    real_write = engine.safe_write_bytes
    calls = {"n": 0}

    def write(r, rel, data):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        return real_write(r, rel, data)

    real_save = Store.save_transaction

    def save(self, tx):
        if tx.status in (TransactionStatus.FAILED, TransactionStatus.PARTIAL):
            raise OSError("cannot write record")
        return real_save(self, tx)

    monkeypatch.setattr(engine, "safe_write_bytes", write)
    monkeypatch.setattr(Store, "save_transaction", save)
    with pytest.raises(ApplyError, match="disk full") as exc:
        apply_plan(workspace, store, reg, plan)
    assert "could not be updated" in exc.value.message
    monkeypatch.undo()
    tx = store.load_transaction(transaction_id_for(plan.plan_id))
    assert tx.status == TransactionStatus.IN_PROGRESS  # what the disk says; journal covers it
    _recover(workspace, store, plan)
    assert _snapshot(root) == before


def _corrupt_first_backup(store: Store, tx) -> None:
    backups = store.backup_dir(tx.transaction_id)
    op = next(o for o in tx.operations if o.backup and b"\n" in (backups / o.backup).read_bytes())
    path = backups / op.backup
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))


def test_tampered_backup_is_not_restored(workspace, make_project):
    root = make_project("tampered-backup", kind="claude")
    reg, store, plan = _approved_plan(workspace, root)
    tx = apply_plan(workspace, store, reg, plan)
    assert any(o.backup_sha256 for o in tx.operations)
    _corrupt_first_backup(store, tx)  # same text after newline normalisation, other bytes
    with pytest.raises(RollbackConflict, match="does not match its recorded hash"):
        execute_rollback(store, plan_rollback(store, tx))
    assert store.load_transaction(tx.transaction_id).status == (TransactionStatus.RECOVERY_REQUIRED)


def test_failed_rollback_marks_recovery_required_and_can_resume(
    workspace, make_project, monkeypatch
):
    root = make_project("rollback-fails", kind="claude")
    before = _snapshot(root)
    reg, store, plan = _approved_plan(workspace, root)
    tx = apply_plan(workspace, store, reg, plan)
    real = rollback_engine.atomic_write_bytes
    calls = {"n": 0}

    def flaky(path, data):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk full")
        return real(path, data)

    monkeypatch.setattr(rollback_engine, "atomic_write_bytes", flaky)
    with pytest.raises(OSError, match="disk full"):
        execute_rollback(store, plan_rollback(store, tx))
    tx = store.load_transaction(tx.transaction_id)
    assert tx.status == TransactionStatus.RECOVERY_REQUIRED
    assert store.recovery_reason(tx) == "a rollback of it failed midway"
    execute_rollback(store, plan_rollback(store, tx))  # resumes: done ops are skipped
    assert _snapshot(root) == before


def test_file_changed_between_preflight_and_write(workspace, make_project, monkeypatch):
    root = make_project("toctou", kind="claude")
    reg, store, plan = _approved_plan(workspace, root)
    real = engine.preflight

    def preflight_then_user_edits(*args, **kwargs):
        rep = real(*args, **kwargs)
        (root / "CLAUDE.md").write_text("# edited meanwhile\n", encoding="utf-8")
        return rep

    monkeypatch.setattr(engine, "preflight", preflight_then_user_edits)
    with pytest.raises(StalePlanError, match="changed between pre-flight and write"):
        apply_plan(workspace, store, reg, plan)
    assert (root / "CLAUDE.md").read_text(encoding="utf-8") == "# edited meanwhile\n"


BOUNDARIES = ["backup", "write", "readback", "manifest", "record"]


@pytest.mark.parametrize("boundary", BOUNDARIES)
def test_fault_at_every_boundary_is_recoverable(workspace, make_project, monkeypatch, boundary):
    root = make_project(f"fault-{boundary}", kind="claude")
    before = _snapshot(root)
    reg, store, plan = _approved_plan(workspace, root)
    boom = OSError(f"injected at {boundary}")
    if boundary == "backup":
        monkeypatch.setattr(
            BackupStore, "save", lambda self, rel, data: (_ for _ in ()).throw(boom)
        )
    elif boundary in ("write", "manifest"):
        real = engine.safe_write_bytes
        calls = {"n": 0}

        def write(r, rel, data):
            calls["n"] += 1
            hit = rel.endswith("managed.json") if boundary == "manifest" else calls["n"] == 2
            if hit:
                raise boom
            return real(r, rel, data)

        monkeypatch.setattr(engine, "safe_write_bytes", write)
    elif boundary == "readback":
        monkeypatch.setattr(engine, "sha256_bytes", lambda data: str(id(data)))
    else:  # the record save right after the second write
        real_save = Store.save_transaction
        calls = {"n": 0}

        def save(self, tx):
            calls["n"] += 1
            if calls["n"] == 5:
                raise boom
            return real_save(self, tx)

        monkeypatch.setattr(Store, "save_transaction", save)
    with pytest.raises(ApplyError):
        apply_plan(workspace, store, reg, plan)
    monkeypatch.undo()
    tx = store.load_transaction(transaction_id_for(plan.plan_id))
    assert tx.status != TransactionStatus.COMPLETED
    _recover(workspace, store, plan)
    assert _snapshot(root) == before
    assert store.transactions_needing_recovery(plan.target.canonical_path) == []
