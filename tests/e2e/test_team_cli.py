"""Team commands (6-month plan, phase 1): `check` as a CI gate, `sync` for a fresh clone,
approval files for non-interactive approve/forge, and local `stats`."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from agent_forge.cli import app
from tests.conftest import unwrap

pytestmark = pytest.mark.e2e
runner = CliRunner()

BACKEND = {
    "pyproject.toml": "[project]\nname='api'\nversion='0'\ndependencies=['fastapi','pytest']\n",
    "app/main.py": "x = 1\n",
}


def run(*args: str, expect: int = 0, input: str | None = None):
    result = runner.invoke(app, list(args), input=input, catch_exceptions=False)
    assert result.exit_code == expect, f"{args}\nexit={result.exit_code}\n{result.output}"
    return result


def run_json(*args: str, expect: int = 0):
    return unwrap(run(*args, expect=expect).stdout)


def _flat(text: str) -> str:
    return " ".join(text.split())  # Rich wraps long error lines


def _forge(ws: str, root: Path) -> dict:
    return run_json("forge", str(root), "--workspace", ws, "--yes", "--shared-files", "--json")


def _managed_skill(root: Path) -> Path:
    manifest = unwrap((root / ".agent-forge" / "managed.json").read_text(encoding="utf-8"))
    for rec in manifest["capabilities"]:
        for rel in rec["files"]:
            if rel.endswith("SKILL.md"):
                return root / rel
    raise AssertionError("no managed skill")


# ---- check ---------------------------------------------------------------------------------


def test_check_is_a_ci_gate(real_workspace, make_project) -> None:
    ws = str(real_workspace.root)
    root = make_project("gate", kind="claude", files=BACKEND)
    assert run_json("check", str(root), "--workspace", ws, "--json")["managed"] == []
    _forge(ws, root)
    out = run_json("check", str(root), "--workspace", ws, "--json")
    assert out["ok"] and out["failures"] == [] and out["drifted"] == 0 and out["managed"]

    skill = _managed_skill(root)
    skill.write_text("edited by hand\n", encoding="utf-8")
    out = run_json("check", str(root), "--workspace", ws, "--json", expect=12)
    assert not out["ok"] and out["drifted"] == 1
    assert any(f.startswith("drift:") and "modified" in f for f in out["failures"])

    skill.unlink()
    out = run_json("check", str(root), "--workspace", ws, "--json", expect=12)
    assert any("missing" in f for f in out["failures"])

    (root / ".agent-forge" / "managed.json").write_text("{not json", encoding="utf-8")
    out = run_json("check", str(root), "--workspace", ws, "--json", expect=12)
    assert any("invalid" in f for f in out["failures"])


# ---- sync ----------------------------------------------------------------------------------


def test_sync_restores_a_fresh_clone_to_the_committed_state(real_workspace, make_project) -> None:
    ws = str(real_workspace.root)
    root = make_project("clone", kind="claude", files=BACKEND)
    _forge(ws, root)
    out = run_json("sync", str(root), "--workspace", ws, "--json")
    assert out["status"] == "in_sync"

    skill = _managed_skill(root)
    original = skill.read_text(encoding="utf-8")
    skill.unlink()
    manifest = unwrap((root / ".agent-forge" / "managed.json").read_text(encoding="utf-8"))
    rule = next(
        root / rel
        for rec in manifest["capabilities"]
        for rel in rec["files"]
        if rel.endswith(".md") and root / rel != skill
    )
    rule.write_text("local edit\n", encoding="utf-8")

    dry = run_json("sync", str(root), "--workspace", ws, "--dry-run", "--json")
    assert dry["status"] == "planned" and len(dry["drifted"]) == 2
    assert not skill.exists()  # dry run wrote nothing

    # no TTY and no --yes: refused before any write
    run("sync", str(root), "--workspace", ws, expect=6)
    assert not skill.exists()

    out = run_json("sync", str(root), "--workspace", ws, "--yes", "--json")
    assert out["status"] == "restored" and out["transaction_id"].startswith("tx-")
    assert skill.read_text(encoding="utf-8") == original
    assert rule.read_text(encoding="utf-8") != "local edit\n"
    assert run_json("check", str(root), "--workspace", ws, "--json")["ok"]
    # the restore is an ordinary transaction: it can be rolled back
    run("rollback", out["transaction_id"], "--workspace", ws, "--yes")


def test_sync_without_manifest_does_nothing(real_workspace, make_project) -> None:
    ws = str(real_workspace.root)
    root = make_project("plain", kind="claude", files=BACKEND)
    out = run_json("sync", str(root), "--workspace", ws, "--yes", "--json")
    assert out["status"] == "nothing_managed"
    assert not (root / ".agent-forge").exists()


# ---- approval files ------------------------------------------------------------------------


def test_approval_file_gates_approve_and_forge(
    real_workspace, make_project, tmp_path: Path
) -> None:
    ws = str(real_workspace.root)
    root = make_project("ci", kind="claude", files=BACKEND)
    plan = run_json("assign", str(root), "--workspace", ws, "--json")
    selected = {s["capability_id"]: s["version"] for s in plan["selected"]}
    assert selected

    # a file that covers only part of the plan: refused, nothing approved
    partial = tmp_path / "partial.yaml"
    first = sorted(selected)[0]
    partial.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "approved_by": "tech-lead",
                "approved_at": "2026-10-20",
                "classes": ["shared_file"],
                "capabilities": {first: selected[first]},
            }
        ),
        encoding="utf-8",
    )
    res = run(
        "approve", plan["plan_id"], "--workspace", ws, "--approval-file", str(partial), expect=14
    )
    assert "not in the approval file" in _flat(res.output)
    assert all(
        p["status"] != "approved"
        for p in run_json("plans", "--workspace", ws, "--json")
        if p["plan_id"] == plan["plan_id"]
    )

    # a complete file, but without the shared_file class the plan needs
    full = tmp_path / "full.yaml"
    doc = {
        "version": 1,
        "approved_by": "tech-lead",
        "approved_at": "2026-10-20",
        "classes": [],
        "capabilities": dict(selected),
    }
    full.write_text(yaml.safe_dump(doc), encoding="utf-8")
    if any(o["requires_extra_approval"] for o in plan["operations"]):
        res = run(
            "approve", plan["plan_id"], "--workspace", ws, "--approval-file", str(full), expect=14
        )
        assert "class shared_file not granted" in _flat(res.output)
    doc["classes"] = ["shared_file", "hook", "mcp"]
    full.write_text(yaml.safe_dump(doc), encoding="utf-8")

    # version pin mismatch is refused too
    pinned_wrong = tmp_path / "wrong-version.yaml"
    wrong = dict(doc, capabilities={**doc["capabilities"], first: "0.0.1"})
    pinned_wrong.write_text(yaml.safe_dump(wrong), encoding="utf-8")
    run(
        "approve",
        plan["plan_id"],
        "--workspace",
        ws,
        "--approval-file",
        str(pinned_wrong),
        expect=14,
    )

    # covered: approved non-interactively, approver recorded from the file
    exported = tmp_path / "exported.yaml"
    run(
        "approve",
        plan["plan_id"],
        "--workspace",
        ws,
        "--approval-file",
        str(full),
        "--export-approval",
        str(exported),
    )
    saved = run_json("plans", "--workspace", ws, "--json")
    assert any(p["plan_id"] == plan["plan_id"] and p["status"] == "approved" for p in saved)
    exp = yaml.safe_load(exported.read_text(encoding="utf-8"))
    assert exp["approved_by"] == "approval-file:tech-lead"
    assert set(exp["capabilities"]) >= set(selected)
    assert exp["classes"] == ["hook", "mcp", "shared_file"]

    # CI: forge with the exported file applies, and a second run is a no-op
    report = run_json(
        "forge", str(root), "--workspace", ws, "--approval-file", str(exported), "--json"
    )
    assert report["approval_file"] == str(exported)
    assert {s["status"] for s in report["steps"]} <= {"applied", "nothing_to_do"}
    assert any(s["status"] == "applied" for s in report["steps"])
    again = run_json(
        "forge", str(root), "--workspace", ws, "--approval-file", str(exported), "--json"
    )
    assert all(s["status"] == "nothing_to_do" for s in again["steps"])

    # a project whose plan would add something the file never approved: exit 14, no write
    other = make_project(
        "ci-other", kind="claude", files={**BACKEND, "package.json": '{"name":"x"}'}
    )
    before = sorted(p.as_posix() for p in other.rglob("*") if p.is_file())
    res = run("forge", str(other), "--workspace", ws, "--approval-file", str(partial), expect=14)
    assert "not covered by" in _flat(res.output)
    assert sorted(p.as_posix() for p in other.rglob("*") if p.is_file()) == before

    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 2\napproved_by: x\n", encoding="utf-8")
    run("forge", str(other), "--workspace", ws, "--approval-file", str(bad), expect=2)
    (tmp_path / "unknown-class.yaml").write_text(
        yaml.safe_dump({**doc, "classes": ["root"]}), encoding="utf-8"
    )
    run(
        "forge",
        str(other),
        "--workspace",
        ws,
        "--approval-file",
        str(tmp_path / "unknown-class.yaml"),
        expect=2,
    )


# ---- stats ---------------------------------------------------------------------------------


def test_stats_summarise_the_local_audit_log(real_workspace, make_project) -> None:
    ws = str(real_workspace.root)
    assert run_json("stats", "--workspace", ws, "--json")["records"] == 0
    root = make_project("stats", kind="claude", files=BACKEND)
    report = _forge(ws, root)
    tx_id = next(s["transaction_id"] for s in report["steps"] if s.get("transaction_id"))
    run("rollback", tx_id, "--workspace", ws, "--yes")
    data = run_json("stats", "--workspace", ws, "--json")
    assert data["projects"] == 1 and data["events"]["RollbackCompleted"] == 1
    rows = {r["capability"]: r for r in data["by_capability"]}
    assert rows and all(r["installs"] >= 1 for r in rows.values())
    assert sum(r["rollbacks"] for r in rows.values()) >= 1
    assert (
        run_json("stats", "--workspace", ws, "--since", "1", "--json")["records"] == data["records"]
    )
    assert "capabilities" in run("stats", "--workspace", ws).output
