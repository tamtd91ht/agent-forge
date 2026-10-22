"""`agent-forge import` (ADR-0011): hand-written assets are adopted in place, through the
ordinary plan / approve / apply / rollback path, and the rest of the engine treats the
resulting local.* records honestly (no upgrade, no restore, no drift gate, removable)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_forge.apply.engine import apply_plan
from agent_forge.errors import PlanError, RollbackConflict
from agent_forge.matching.rules import MatchContext
from agent_forge.models.capability import Platform
from agent_forge.models.plan import OperationKind, PlanStatus
from agent_forge.models.project import LOCAL_VERSION
from agent_forge.planner.adopt import adoptable_assets, build_import_plan, local_id
from agent_forge.planner.builder import build_assign_plan, build_upgrade_plan
from agent_forge.planner.maintenance import build_remove_plan, build_repair_plan, drift_report
from agent_forge.registry.loader import load_registry
from agent_forge.rollback.engine import execute_rollback, plan_rollback
from agent_forge.scanner.project_profile import scan_project
from agent_forge.storage.transactions import Store
from agent_forge.util import now_iso
from agent_forge.validation.engine import validate_target

SKILL = "---\nname: {n}\ndescription: {n} written by the team\n---\n# {n}\n\nDo it our way.\n"
AGENT = "---\nname: reviewer\ndescription: reviews our code\n---\n# r\n"
FILES = {
    ".claude/skills/our-tdd/SKILL.md": SKILL.format(n="our-tdd"),
    ".agents/skills/our-tdd/SKILL.md": SKILL.format(n="our-tdd"),  # same skill, Codex copy
    ".claude/skills/_template/SKILL.md": SKILL.format(n="_template"),  # underscore: not adopted
    ".claude/agents/reviewer.md": AGENT,
    ".claude/rules/style.md": "# Style\n\nTabs, never spaces.\n",
    ".claude/commands/ship.md": "Ship it.\n",
    ".claude/rules/crlf.md": "# CRLF\r\n\r\nWritten on Windows.\r\n",
}


def _approve(workspace, plan) -> None:
    plan.approval.status = "approved"
    plan.approval.approved_at = now_iso()
    plan.approval.plan_digest = plan.content_digest()
    plan.status = PlanStatus.APPROVED
    Store(workspace).record_approval(plan)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and ".git" not in p.parts and ".agent-forge" not in p.parts
    }


@pytest.fixture
def project(make_project) -> Path:
    root = make_project("adopt", kind="both", files=FILES)
    # the CRLF rule must keep its bytes; make_project writes LF, so rewrite it raw
    (root / ".claude" / "rules" / "crlf.md").write_bytes(FILES[".claude/rules/crlf.md"].encode())
    return root


def test_import_plan_records_only_the_manifest_and_groups_platform_copies(
    workspace, project: Path
) -> None:
    reg = load_registry(workspace.registry_dir)
    profile = scan_project(project)
    plan = build_import_plan(reg, profile)
    assert plan.kind == "import" and len(plan.operations) == 1
    op = plan.operations[0]
    assert op.kind == OperationKind.MANIFEST and op.path == ".agent-forge/managed.json"
    ids = {s.capability_id for s in plan.selected}
    assert ids >= {
        local_id("skill", "our-tdd"),
        local_id("agent", "reviewer"),
        local_id("rule", "style"),
        local_id("rule", "crlf"),
        local_id("command", "ship"),
    }
    assert local_id("skill", "_template") not in ids
    manifest = json.loads(op.content or "{}")
    tdd = next(r for r in manifest["capabilities"] if r["capability_id"] == "local.skill.our-tdd")
    assert set(tdd["files"]) == {
        ".claude/skills/our-tdd/SKILL.md",
        ".agents/skills/our-tdd/SKILL.md",
    }
    assert tdd["version"] == LOCAL_VERSION
    # kinds and paths narrow the selection; an unknown kind is refused
    only_rules = build_import_plan(reg, profile, kinds=("rule",))
    assert {s.capability_id for s in only_rules.selected} == {
        local_id("rule", "style"),
        local_id("rule", "crlf"),
    }
    only_dir = build_import_plan(reg, profile, paths=(".claude/agents",))
    assert {s.capability_id for s in only_dir.selected} == {local_id("agent", "reviewer")}
    with pytest.raises(PlanError):
        build_import_plan(reg, profile, kinds=("hook",))


def test_apply_import_touches_no_adopted_file_and_the_engine_treats_local_honestly(
    workspace, project: Path
) -> None:
    reg = load_registry(workspace.registry_dir)
    store = Store(workspace)
    before = _snapshot(project)
    plan = build_import_plan(reg, scan_project(project))
    store.save_plan(plan)
    _approve(workspace, plan)
    tx = apply_plan(workspace, store, reg, plan)
    assert _snapshot(project) == before  # nothing but the manifest was written
    assert [o.path for o in tx.operations] == [".agent-forge/managed.json"]

    profile = scan_project(project)
    assert profile.managed_manifest_valid is True
    by_id = {m.capability_id: m for m in profile.managed}
    assert by_id["local.rule.crlf"].drift == []  # normalised hashes: CRLF is not drift
    skill = next(a for a in profile.assets if a.path == ".claude/skills/our-tdd/SKILL.md")
    assert skill.managed_by == "local.skill.our-tdd"

    # nothing to upgrade or restore, nothing to import twice
    assert (
        build_upgrade_plan(reg, profile, MatchContext(platforms=(Platform.CLAUDE_CODE,))).operations
        == []
    )
    assert build_import_plan(reg, profile).operations == []
    assert {a.path for a in adoptable_assets(profile)} == {
        a for m in profile.managed if m.is_local for a in m.files
    }
    with pytest.raises(PlanError):
        build_repair_plan(reg, profile, "restore", ["local.rule.style"])

    # the team edits its file: visible, never a drift failure, never an error
    (project / ".claude" / "rules" / "style.md").write_text(
        "# Style\n\nSpaces.\n", encoding="utf-8", newline="\n"
    )
    profile = scan_project(project)
    assert next(m for m in profile.managed if m.capability_id == "local.rule.style").drift
    assert drift_report(profile).drifted == []
    rep = validate_target(workspace, reg, store, profile)
    local_findings = [f for f in rep.findings if "local.rule.style" in f.message]
    assert local_findings and all(f.level == "info" for f in local_findings)
    assert not any(f.level == "error" for f in rep.findings), [f.message for f in rep.findings]

    # a catalog capability still cannot overwrite an adopted file
    assign, _match = build_assign_plan(
        reg, profile, MatchContext(platforms=(Platform.CLAUDE_CODE,))
    )
    assert not any(o.path.startswith(".claude/skills/our-tdd/") for o in assign.operations)

    # re-import after an edit refreshes the recorded hash through the same manifest write
    again = build_import_plan(reg, profile)
    assert [s.capability_id for s in again.selected] == ["local.rule.style"]
    assert "refreshed" in again.selected[0].reasons[0]
    store.save_plan(again)
    _approve(workspace, again)
    apply_plan(workspace, store, reg, again)
    profile = scan_project(project)
    assert next(m for m in profile.managed if m.capability_id == "local.rule.style").drift == []
    assert build_import_plan(reg, profile).operations == []
    # unmanage stops tracking an adopted asset without touching it
    unmanage = build_repair_plan(reg, profile, "unmanage", ["local.rule.crlf"])
    store.save_plan(unmanage)
    _approve(workspace, unmanage)
    apply_plan(workspace, store, reg, unmanage)
    profile = scan_project(project)
    assert "local.rule.crlf" not in {m.capability_id for m in profile.managed}
    assert (project / ".claude" / "rules" / "crlf.md").read_bytes() == before[
        ".claude/rules/crlf.md"
    ]
    assert [s.capability_id for s in build_import_plan(reg, profile).selected] == [
        "local.rule.crlf"
    ]

    # remove deletes the adopted file through the normal plan, and rollback brings it back
    profile = scan_project(project)
    rm = build_remove_plan(reg, profile, ["local.command.ship"])
    store.save_plan(rm)
    _approve(workspace, rm)
    rm_tx = apply_plan(workspace, store, reg, rm)
    assert not (project / ".claude" / "commands" / "ship.md").exists()
    execute_rollback(store, plan_rollback(store, rm_tx))
    assert (project / ".claude" / "commands" / "ship.md").read_text(
        encoding="utf-8"
    ) == "Ship it.\n"

    # the original import cannot be rolled back any more: later transactions rewrote the
    # manifest, and rollback never overwrites a file that changed independently
    with pytest.raises(RollbackConflict):
        execute_rollback(store, plan_rollback(store, tx))
    assert _snapshot(project) == {**before, ".claude/rules/style.md": b"# Style\n\nSpaces.\n"}


def test_rolling_back_an_import_removes_the_manifest_and_leaves_the_files(
    workspace, project: Path
) -> None:
    reg = load_registry(workspace.registry_dir)
    store = Store(workspace)
    before = _snapshot(project)
    plan = build_import_plan(reg, scan_project(project))
    store.save_plan(plan)
    _approve(workspace, plan)
    tx = apply_plan(workspace, store, reg, plan)
    assert (project / ".agent-forge" / "managed.json").is_file()
    rb = execute_rollback(store, plan_rollback(store, tx))
    assert rb.status.value == "completed"
    assert not (project / ".agent-forge" / "managed.json").exists()
    assert _snapshot(project) == before
    assert scan_project(project).managed == []


def test_import_refuses_an_invalid_manifest(workspace, make_project) -> None:
    root = make_project(
        "bad",
        kind="claude",
        files={".agent-forge/managed.json": '{"version": "1", "capabilities": 1}'},
    )
    reg = load_registry(workspace.registry_dir)
    with pytest.raises(PlanError):
        build_import_plan(reg, scan_project(root))
