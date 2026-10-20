"""Hook and MCP capabilities: separate approval classes, JSON merge, drift-aware rollback."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_forge.apply.engine import apply_plan
from agent_forge.errors import ApprovalError, PlanError
from agent_forge.matching.rules import MatchContext
from agent_forge.models.capability import Platform
from agent_forge.models.plan import OperationKind, PlanStatus
from agent_forge.models.transaction import TransactionStatus
from agent_forge.planner.builder import build_assign_plan
from agent_forge.registry.loader import load_registry
from agent_forge.rollback.engine import execute_rollback, plan_rollback
from agent_forge.scanner.project_profile import scan_project
from agent_forge.storage.transactions import Store
from agent_forge.util import now_iso
from agent_forge.validation.engine import validate_target

ALL = frozenset({"standard", "shared_file", "hook", "mcp"})


def _approve(workspace, plan, classes: set[str]) -> None:
    missing = [
        o for o in plan.operations_needing_extra_approval() if o.approval_class not in classes
    ]
    if missing:
        raise PlanError("test: missing classes " + ", ".join(o.approval_class for o in missing))
    plan.approval.status = "approved"
    plan.approval.approved_at = now_iso()
    plan.approval.plan_digest = plan.content_digest()
    plan.approval.extra_approvals = [o.op_id for o in plan.operations_needing_extra_approval()]
    plan.status = PlanStatus.APPROVED
    Store(workspace).record_approval(plan)


def _plan(workspace, root: Path, allowed=ALL):
    reg = load_registry(workspace.registry_dir)
    profile = scan_project(root)
    plan, _ = build_assign_plan(
        reg, profile, MatchContext(platforms=(Platform.CLAUDE_CODE,), allowed_classes=allowed)
    )
    return reg, plan


def test_hook_and_mcp_ops_carry_their_approval_class(workspace, make_project) -> None:
    root = make_project("hm1", kind="claude")
    _reg, plan = _plan(workspace, root)
    classes = {
        o.path: o.approval_class for o in plan.operations if o.kind == OperationKind.MERGE_JSON
    }
    assert classes == {".claude/settings.json": "hook", ".mcp.json": "mcp"}
    assert all(
        o.requires_extra_approval for o in plan.operations if o.kind == OperationKind.MERGE_JSON
    )


def test_ungranted_classes_are_left_out_of_the_plan(workspace, make_project) -> None:
    root = make_project("hm2", kind="claude")
    _reg, plan = _plan(workspace, root, allowed=frozenset({"standard", "shared_file"}))
    assert not any(o.kind == OperationKind.MERGE_JSON for o in plan.operations)
    rejected = {r.capability_id: r.category for r in plan.rejected}
    assert rejected["t.hook"] == "needs_approval" and rejected["t.mcp"] == "needs_approval"
    assert "t.hook" not in {s.capability_id for s in plan.selected}
    manifest_op = plan.operations[-1]
    assert "t.hook" not in (manifest_op.content or "")  # manifest never lists un-planned caps


def test_apply_refuses_hook_without_class_approval(workspace, make_project) -> None:
    root = make_project("hm3", kind="claude")
    reg, plan = _plan(workspace, root)
    _approve(workspace, plan, ALL)
    hook_op = next(o for o in plan.operations if o.approval_class == "hook")
    plan.approval.extra_approvals.remove(hook_op.op_id)  # simulate approve without --hooks
    with pytest.raises(ApprovalError, match="hook change needs explicit approval"):
        apply_plan(workspace, Store(workspace), reg, plan)


def test_merge_preserves_user_settings_and_rollback_is_entry_aware(workspace, make_project) -> None:
    root = make_project("hm4", kind="claude")
    settings = root / ".claude" / "settings.json"
    original = json.loads(settings.read_text(encoding="utf-8"))
    reg, plan = _plan(workspace, root)
    _approve(workspace, plan, ALL)
    store = Store(workspace)
    tx = apply_plan(workspace, store, reg, plan)
    assert tx.status == TransactionStatus.COMPLETED
    merged = json.loads(settings.read_text(encoding="utf-8"))
    assert merged["hooks"]["PostToolUse"][0]["hooks"][0]["command"] == "echo hi"  # user's hook kept
    assert any(
        h["command"] == "echo t-hook" for g in merged["hooks"]["PostToolUse"] for h in g["hooks"]
    )
    mcp = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["t-server"]["command"] == "npx"
    manifest = json.loads((root / ".agent-forge" / "managed.json").read_text(encoding="utf-8"))
    rec = next(c for c in manifest["capabilities"] if c["capability_id"] == "t.hook")
    assert ".claude/settings.json" in rec["json_merges"]

    profile = scan_project(root)
    rep = validate_target(workspace, reg, store, profile)
    assert rep.ok, [f.message for f in rep.errors]

    # user adds their own MCP server and another hook after apply -> rollback keeps them
    mcp["mcpServers"]["mine"] = {"command": "mine"}
    (root / ".mcp.json").write_text(json.dumps(mcp, indent=2), encoding="utf-8")
    merged["hooks"]["Stop"] = [{"hooks": [{"type": "command", "command": "user-stop"}]}]
    settings.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    rp = plan_rollback(store, store.load_transaction(tx.transaction_id))
    actions = {c.op.path: c.action for c in rp.checks}
    assert (
        actions[".mcp.json"] == "remove_json" and actions[".claude/settings.json"] == "remove_json"
    )
    assert not rp.conflicts
    rb = execute_rollback(store, rp)
    assert rb.status == TransactionStatus.COMPLETED
    after_mcp = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))
    assert after_mcp == {"mcpServers": {"mine": {"command": "mine"}}}
    after_settings = json.loads(settings.read_text(encoding="utf-8"))
    assert after_settings["hooks"]["Stop"][0]["hooks"][0]["command"] == "user-stop"
    assert after_settings["hooks"]["PostToolUse"] == original["hooks"]["PostToolUse"]
    assert not any(
        h["command"] == "echo t-hook"
        for g in after_settings["hooks"]["PostToolUse"]
        for h in g["hooks"]
    )


def test_mcp_name_conflict_is_a_plan_error(workspace, make_project) -> None:
    root = make_project(
        "hm5",
        kind="claude",
        files={
            ".mcp.json": json.dumps({"mcpServers": {"t-server": {"command": "something-else"}}})
        },
    )
    with pytest.raises(PlanError, match="already defines MCP server"):
        _plan(workspace, root)


def test_dependant_of_unapproved_capability_is_left_out(workspace, make_project) -> None:
    from tests.conftest import base_manifest, skill_assets, write_capability

    # t.notice needs the shared_file class; t.needs-notice must not be installed without it
    write_capability(
        workspace.registry_dir,
        base_manifest("t.needs-notice", dependencies=["t.notice"]),
        skill_assets("needs-notice"),
    )
    root = make_project("dep-approval", kind="claude")
    _reg, plan = _plan(workspace, root, allowed=frozenset({"standard"}))
    rejected = {r.capability_id: r for r in plan.rejected}
    assert rejected["t.notice"].category == "needs_approval"
    assert rejected["t.needs-notice"].category == "needs_approval"
    assert "t.notice" in rejected["t.needs-notice"].reasons[0]
    assert "--shared-files" in rejected["t.needs-notice"].reasons[1]
    assert "t.needs-notice" not in {s.capability_id for s in plan.selected}
    assert not any("needs-notice" in o.path for o in plan.operations)

    _reg, plan = _plan(workspace, root)  # class granted: both come back
    assert {"t.notice", "t.needs-notice"} <= {s.capability_id for s in plan.selected}
