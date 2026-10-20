"""Library-level lifecycle: assign -> approve -> apply -> validate -> drift -> rollback / upgrade."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_forge.apply.engine import apply_plan, preflight
from agent_forge.errors import (
    ApplyError,
    ApprovalError,
    PlanError,
    RollbackConflict,
    StalePlanError,
)
from agent_forge.matching.rules import MatchContext
from agent_forge.models.capability import Platform
from agent_forge.models.plan import PlanStatus
from agent_forge.models.transaction import TransactionStatus
from agent_forge.planner.builder import build_assign_plan, build_upgrade_plan
from agent_forge.planner.diff import render_plan_diff
from agent_forge.registry.loader import load_registry
from agent_forge.rollback.engine import execute_rollback, plan_rollback
from agent_forge.scanner.project_profile import scan_project
from agent_forge.storage.transactions import Store
from agent_forge.util import now_iso
from agent_forge.validation.engine import validate_target
from tests.conftest import base_manifest, skill_assets, write_capability


def _approve(plan, shared: bool = True) -> None:
    plan.approval.status = "approved"
    plan.approval.approved_at = now_iso()
    plan.approval.plan_digest = plan.content_digest()
    plan.approval.extra_approvals = (
        [o.op_id for o in plan.operations_needing_extra_approval()] if shared else []
    )
    plan.status = PlanStatus.APPROVED


def _plan_for(workspace, root: Path, platforms=(Platform.CLAUDE_CODE,), **ctx):
    reg = load_registry(workspace.registry_dir)
    profile = scan_project(root)
    plan, _ = build_assign_plan(reg, profile, MatchContext(platforms=platforms, **ctx))
    return reg, profile, plan


def test_assign_plan_does_not_touch_target(workspace, make_project) -> None:
    root = make_project("t1", kind="claude")
    before = sorted(
        p.relative_to(root).as_posix() for p in root.rglob("*") if ".git" not in p.parts
    )
    _reg, _profile, plan = _plan_for(workspace, root)
    after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if ".git" not in p.parts)
    assert before == after
    assert plan.status == PlanStatus.DRAFT and plan.operations
    assert any(o.requires_extra_approval and o.path == "CLAUDE.md" for o in plan.operations)
    assert plan.operations[-1].path == ".agent-forge/managed.json"


def test_diff_matches_projected_content(workspace, make_project) -> None:
    root = make_project("t2", kind="claude")
    _reg, _profile, plan = _plan_for(workspace, root)
    diffs = render_plan_diff(plan, root)
    assert not any(d.stale for d in diffs)
    section = next(d for d in diffs if d.op.path == "CLAUDE.md")
    assert "+<!-- agent-forge:begin id=t-notice" in section.unified
    assert "-# Project" not in section.unified  # nothing removed from user content


def test_apply_requires_valid_approval(workspace, make_project) -> None:
    root = make_project("t3", kind="claude")
    reg, _profile, plan = _plan_for(workspace, root)
    store = Store(workspace)
    with pytest.raises(ApprovalError):
        apply_plan(workspace, store, reg, plan)
    _approve(plan, shared=False)  # shared-file op not approved
    rep = preflight(plan, reg)
    assert not rep.ok and any("shared-file" in p for p in rep.problems)
    _approve(plan, shared=True)
    plan.operations[0].content = "tampered"
    plan.operations[0].content_sha256 = "0" * 64
    with pytest.raises(ApprovalError):
        apply_plan(workspace, store, reg, plan)


def test_full_lifecycle_with_drift_and_rollback(workspace, make_project) -> None:
    root = make_project("t4", kind="claude")
    reg, _profile, plan = _plan_for(workspace, root)
    store = Store(workspace)
    _approve(plan)
    store.save_plan(plan)
    tx = apply_plan(workspace, store, reg, plan)
    assert tx.status == TransactionStatus.COMPLETED
    assert all(o.applied for o in tx.operations)
    assert (root / ".claude" / "skills" / "always" / "SKILL.md").is_file()
    claude_md = (root / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude_md.startswith("# Project\n\nUser instructions.\n")
    assert "agent-forge:begin id=t-notice" in claude_md
    manifest = json.loads((root / ".agent-forge" / "managed.json").read_text(encoding="utf-8"))
    ids = {c["capability_id"] for c in manifest["capabilities"]}
    assert {"t.always", "t.needs-always", "t.notice"} <= ids
    assert all(c["installed_at"] != "(set at apply time)" for c in manifest["capabilities"])

    # validate: clean
    profile2 = scan_project(root)
    rep = validate_target(workspace, reg, store, profile2)
    assert rep.ok, [f.message for f in rep.errors]
    assert {m.capability_id for m in profile2.managed} == ids
    assert not any(m.drift for m in profile2.managed)

    # independent user modification -> drift detected, rollback refuses that file
    skill = root / ".claude" / "skills" / "always" / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\nuser tweak\n", encoding="utf-8")
    (root / "CLAUDE.md").write_text(claude_md + "\nuser line after apply\n", encoding="utf-8")
    profile3 = scan_project(root)
    assert any(".claude/skills/always/SKILL.md" in m.drift for m in profile3.managed)

    rp = plan_rollback(store, store.load_transaction(tx.transaction_id))
    conflict_paths = {c.op.path for c in rp.conflicts}
    assert conflict_paths == {".claude/skills/always/SKILL.md"}
    section_actions = {c.op.path: c.action for c in rp.checks if c.op.path == "CLAUDE.md"}
    assert section_actions == {"CLAUDE.md": "remove_section"}
    with pytest.raises(RollbackConflict):
        execute_rollback(store, rp, partial=False)
    rb = execute_rollback(store, rp, partial=True)
    assert rb.status == TransactionStatus.COMPLETED
    assert skill.read_text(encoding="utf-8").endswith("user tweak\n")  # preserved
    assert not (root / ".claude" / "skills" / "needs-always").exists()
    final = (root / "CLAUDE.md").read_text(encoding="utf-8")
    assert "agent-forge:begin" not in final
    assert (
        final.startswith("# Project\n\nUser instructions.\n") and "user line after apply" in final
    )
    assert store.load_transaction(tx.transaction_id).status == TransactionStatus.ROLLBACK_CONFLICT


def test_stale_plan_rejected_when_target_changes(workspace, make_project) -> None:
    root = make_project("t5", kind="claude")
    reg, _profile, plan = _plan_for(workspace, root)
    _approve(plan)
    (root / "CLAUDE.md").write_text("# changed after planning\n", encoding="utf-8")
    assert any(d.stale for d in render_plan_diff(plan, root))
    with pytest.raises(StalePlanError):
        apply_plan(workspace, Store(workspace), reg, plan)


def test_stale_plan_rejected_when_registry_changes(workspace, make_project) -> None:
    root = make_project("t6", kind="claude")
    _reg, _profile, plan = _plan_for(workspace, root)
    _approve(plan)
    p = (
        workspace.registry_dir
        / "capabilities"
        / "t.always"
        / "assets"
        / "claude_code"
        / "always"
        / "SKILL.md"
    )
    p.write_text(p.read_text(encoding="utf-8") + "\nv2\n", encoding="utf-8")
    reg2 = load_registry(workspace.registry_dir)
    with pytest.raises(StalePlanError):
        apply_plan(workspace, Store(workspace), reg2, plan)


def test_apply_is_transactional_on_failure(workspace, make_project, monkeypatch) -> None:
    root = make_project("t7", kind="claude")
    reg, _profile, plan = _plan_for(workspace, root)
    _approve(plan)
    store = Store(workspace)
    import agent_forge.apply.engine as engine

    real = engine.atomic_write_bytes
    calls = {"n": 0}

    def flaky(path, data):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("disk full")
        real(path, data)

    monkeypatch.setattr(engine, "atomic_write_bytes", flaky)
    with pytest.raises(ApplyError):
        apply_plan(workspace, store, reg, plan)
    tx = store.load_transaction("tx-" + plan.plan_id.removeprefix("plan-"))
    assert tx.status == TransactionStatus.PARTIAL
    assert sum(1 for o in tx.operations if o.applied) == 2
    assert store.load_plan(plan.plan_id).status == PlanStatus.FAILED
    # partial transaction can be rolled back cleanly
    rb = execute_rollback(store, plan_rollback(store, tx))
    assert rb.status == TransactionStatus.COMPLETED
    assert not (root / ".claude" / "skills" / "always").exists()


def test_upgrade_plan_replaces_only_unmodified_managed_files(workspace, make_project) -> None:
    root = make_project("t8", kind="claude")
    reg, _profile, plan = _plan_for(workspace, root)
    _approve(plan)
    store = Store(workspace)
    apply_plan(workspace, store, reg, plan)
    # bump t.always to 1.1.0 with new content; user modifies t.needs-always
    cap_dir = workspace.registry_dir / "capabilities" / "t.always"
    manifest = base_manifest("t.always", version="1.1.0")
    write_capability(workspace.registry_dir, manifest, skill_assets("always", body="New body."))
    assert cap_dir.exists()
    na = root / ".claude" / "skills" / "needs-always" / "SKILL.md"
    na.write_text(na.read_text(encoding="utf-8") + "\nlocal\n", encoding="utf-8")
    manifest2 = base_manifest("t.needs-always", version="2.0.0", dependencies=["t.always"])
    write_capability(workspace.registry_dir, manifest2, skill_assets("needs-always", body="v2"))
    reg2 = load_registry(workspace.registry_dir)
    profile2 = scan_project(root)
    up = build_upgrade_plan(reg2, profile2, MatchContext(platforms=(Platform.CLAUDE_CODE,)))
    sel = {s.capability_id for s in up.selected}
    assert sel == {"t.always"}
    assert any(
        r.capability_id == "t.needs-always" and r.category == "conflict" for r in up.rejected
    )
    assert up.user_decisions
    _approve(up)
    tx = apply_plan(workspace, store, reg2, up)
    assert tx.status == TransactionStatus.COMPLETED
    assert "New body." in (root / ".claude/skills/always/SKILL.md").read_text(encoding="utf-8")
    assert na.read_text(encoding="utf-8").endswith("local\n")
    profile3 = scan_project(root)
    versions = {m.capability_id: m.version for m in profile3.managed}
    assert versions["t.always"] == "1.1.0" and versions["t.needs-always"] == "1.0.0"
    # an excluded capability is never upgraded
    write_capability(workspace.registry_dir, base_manifest("t.always", version="1.2.0"))
    up2 = build_upgrade_plan(
        load_registry(workspace.registry_dir),
        profile3,
        MatchContext(platforms=(Platform.CLAUDE_CODE,), excluded_ids=frozenset({"t.always"})),
    )
    assert not up2.selected and not up2.operations


def test_codex_and_claude_both(workspace, make_project) -> None:
    root = make_project("t9", kind="both")
    reg, _profile, plan = _plan_for(
        workspace, root, platforms=(Platform.CLAUDE_CODE, Platform.CODEX)
    )
    paths = {o.path for o in plan.operations}
    assert ".agents/skills/always/SKILL.md" in paths and ".claude/skills/always/SKILL.md" in paths
    assert "AGENTS.md" in paths and "CLAUDE.md" in paths
    _approve(plan)
    store = Store(workspace)
    apply_plan(workspace, store, reg, plan)
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith("# Agents\n\nCodex instructions.\n") and "agent-forge:begin" in agents
    profile2 = scan_project(root)
    rep = validate_target(workspace, reg, store, profile2)
    assert rep.ok, [f.message for f in rep.errors]


def test_corrupted_transaction_record_is_refused(workspace, make_project) -> None:
    root = make_project("t10", kind="claude")
    reg, _profile, plan = _plan_for(workspace, root)
    _approve(plan)
    store = Store(workspace)
    tx = apply_plan(workspace, store, reg, plan)
    path = store.transaction_path(tx.transaction_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["operations"][0]["before_sha256"] = "f" * 64
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(PlanError, match="integrity"):
        plan_rollback(store, store.load_transaction(tx.transaction_id))
