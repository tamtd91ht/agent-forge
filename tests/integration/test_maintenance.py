"""remove / drift / repair plans and the audit log."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_forge.apply.engine import apply_plan
from agent_forge.errors import PlanError
from agent_forge.matching.rules import MatchContext
from agent_forge.models.capability import Platform
from agent_forge.models.plan import OperationKind, PlanStatus
from agent_forge.models.transaction import TransactionStatus
from agent_forge.planner.builder import build_assign_plan
from agent_forge.planner.maintenance import build_remove_plan, build_repair_plan, drift_report
from agent_forge.registry.loader import load_registry
from agent_forge.scanner.project_profile import scan_project
from agent_forge.storage.transactions import Store
from agent_forge.util import now_iso


def _approve(workspace, plan) -> None:
    plan.approval.status = "approved"
    plan.approval.approved_at = now_iso()
    plan.approval.plan_digest = plan.content_digest()
    plan.approval.extra_approvals = [o.op_id for o in plan.operations_needing_extra_approval()]
    plan.status = PlanStatus.APPROVED
    Store(workspace).record_approval(plan)


def _install(workspace, root: Path):
    reg = load_registry(workspace.registry_dir)
    profile = scan_project(root)
    plan, _ = build_assign_plan(reg, profile, MatchContext(platforms=(Platform.CLAUDE_CODE,)))
    _approve(workspace, plan)
    store = Store(workspace)
    tx = apply_plan(workspace, store, reg, plan)
    assert tx.status == TransactionStatus.COMPLETED
    assert tx.registry_digest == reg.digest and tx.profile_fingerprint
    return reg, store, tx


def test_drift_report_states(workspace, make_project) -> None:
    root = make_project("d1", kind="claude")
    _reg, _store, _tx = _install(workspace, root)
    rep = drift_report(scan_project(root))
    assert rep.items and not rep.drifted
    (root / ".claude/skills/always/SKILL.md").write_text("changed\n", encoding="utf-8")
    (root / ".claude/skills/needs-always/SKILL.md").unlink()
    claude_md = root / "CLAUDE.md"
    claude_md.write_text("# Project\n\nUser instructions.\n", encoding="utf-8")  # section removed
    rep = drift_report(scan_project(root))
    states = {(i.capability_id, i.path): i.state for i in rep.drifted}
    assert states[("t.always", ".claude/skills/always/SKILL.md")] == "modified"
    assert states[("t.needs-always", ".claude/skills/needs-always/SKILL.md")] == "missing"
    assert states[("t.notice", "CLAUDE.md")] == "section_missing"
    assert any(i.kind == "json" and i.state == "ok" for i in rep.items)


def test_remove_plan_deletes_files_sections_and_entries(workspace, make_project) -> None:
    root = make_project("r1", kind="claude")
    reg, store, _tx = _install(workspace, root)
    profile = scan_project(root)
    with pytest.raises(PlanError, match="depend on"):
        build_remove_plan(reg, profile, ["t.always"])  # t.needs-always depends on it
    plan = build_remove_plan(reg, profile, ["t.needs-always", "t.notice", "t.hook", "t.mcp"])
    kinds = {(o.kind, o.path) for o in plan.operations}
    assert (OperationKind.REMOVE, ".claude/skills/needs-always/SKILL.md") in kinds
    assert (OperationKind.REMOVE_SECTION, "CLAUDE.md") in kinds
    assert (OperationKind.REMOVE_JSON, ".claude/settings.json") in kinds
    assert (OperationKind.REMOVE_JSON, ".mcp.json") in kinds
    assert {o.approval_class for o in plan.operations_needing_extra_approval()} == {
        "shared_file",
        "hook",
        "mcp",
    }
    _approve(workspace, plan)
    tx = apply_plan(workspace, store, reg, plan)
    assert tx.status == TransactionStatus.COMPLETED
    assert not (root / ".claude/skills/needs-always").exists()
    assert "agent-forge:begin" not in (root / "CLAUDE.md").read_text(encoding="utf-8")
    settings = json.loads((root / ".claude/settings.json").read_text(encoding="utf-8"))
    assert all(
        h["command"] != "echo t-hook" for g in settings["hooks"]["PostToolUse"] for h in g["hooks"]
    )
    assert settings["hooks"]["PostToolUse"][0]["hooks"][0]["command"] == "echo hi"  # user hook kept
    assert not (root / ".mcp.json").exists()  # only our server was in it
    manifest = json.loads((root / ".agent-forge/managed.json").read_text(encoding="utf-8"))
    assert {c["capability_id"] for c in manifest["capabilities"]} == {"t.always", "t.python-only"}


def test_remove_refuses_modified_unless_keep_modified(workspace, make_project) -> None:
    root = make_project("r2", kind="claude")
    reg, _store, _tx = _install(workspace, root)
    skill = root / ".claude/skills/needs-always/SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\nmine\n", encoding="utf-8")
    profile = scan_project(root)
    with pytest.raises(PlanError, match="modified after install"):
        build_remove_plan(reg, profile, ["t.needs-always"])
    plan = build_remove_plan(reg, profile, ["t.needs-always"], keep_modified=True)
    assert not any(o.kind == OperationKind.REMOVE for o in plan.operations)
    assert plan.user_decisions


def test_repair_restore_and_unmanage(workspace, make_project) -> None:
    root = make_project("p1", kind="claude")
    reg, store, _tx = _install(workspace, root)
    skill = root / ".claude/skills/always/SKILL.md"
    original = skill.read_text(encoding="utf-8")
    skill.write_text("broken\n", encoding="utf-8")
    (root / ".claude/skills/needs-always/SKILL.md").unlink()
    profile = scan_project(root)
    plan = build_repair_plan(reg, profile, "restore")
    paths = {o.path: o.kind for o in plan.operations}
    assert paths[".claude/skills/always/SKILL.md"] == OperationKind.REPLACE
    assert paths[".claude/skills/needs-always/SKILL.md"] == OperationKind.CREATE
    assert plan.user_decisions
    _approve(workspace, plan)
    tx = apply_plan(workspace, store, reg, plan)
    assert tx.status == TransactionStatus.COMPLETED
    assert skill.read_text(encoding="utf-8") == original
    assert not drift_report(scan_project(root)).drifted
    # unmanage: drop a drifted capability from the manifest, keep the file
    skill.write_text("mine now\n", encoding="utf-8")
    plan2 = build_repair_plan(reg, scan_project(root), "unmanage", ["t.always"])
    assert [o.path for o in plan2.operations] == [".agent-forge/managed.json"]
    _approve(workspace, plan2)
    apply_plan(workspace, store, reg, plan2)
    after = scan_project(root)
    assert "t.always" not in {m.capability_id for m in after.managed}
    assert skill.read_text(encoding="utf-8") == "mine now\n"
    with pytest.raises(PlanError, match="unknown repair strategy"):
        build_repair_plan(reg, after, "reapply")


def test_audit_log_records_transactions(workspace, make_project) -> None:
    root = make_project("a1", kind="claude")
    _reg, store, tx = _install(workspace, root)
    store.audit.emit("TransactionCompleted", transaction_id=tx.transaction_id, plan_id=tx.plan_id)
    rows = store.audit.read()
    assert (
        rows[-1]["event"] == "TransactionCompleted"
        and rows[-1]["transaction_id"] == tx.transaction_id
    )
    with pytest.raises(ValueError):
        store.audit.emit("NotAnEvent")
    assert store.audit.read(event="PlanCreated") == []
