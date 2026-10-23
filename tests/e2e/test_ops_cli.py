"""CLI: doctor, policy, drift, remove, repair, audit."""

from __future__ import annotations

import pytest
import yaml
from typer.testing import CliRunner

from agent_forge.cli import app
from tests.conftest import unwrap

pytestmark = pytest.mark.e2e
runner = CliRunner()


def run(*args: str, expect: int = 0):
    result = runner.invoke(app, list(args), catch_exceptions=False)
    assert result.exit_code == expect, f"{args}\nexit={result.exit_code}\n{result.output}"
    return result


def run_json(*args: str, expect: int = 0):
    return unwrap(run(*args, expect=expect).stdout)


BACKEND = {
    "pyproject.toml": "[project]\nname='api'\nversion='0'\ndependencies=['fastapi','pytest']\n",
    "app/main.py": "x = 1\n",
}


def test_doctor_reports_environment(real_workspace) -> None:
    checks = run_json("doctor", "--workspace", str(real_workspace.root), "--json")
    names = {c["name"] for c in checks}
    assert {"python", "git", "workspace", "registry", "policy layers", "integrity pins"} <= names
    reg = next(c for c in checks if c["name"] == "registry")
    assert reg["ok"]
    by_name = {c["name"]: c for c in checks}
    assert by_name["orphaned locks"]["ok"] and by_name["orphaned locks"]["detail"] == "none"
    assert "not installed by" in by_name["installed release"]["detail"]


def test_doctor_reads_the_installer_version_file_and_orphaned_locks(real_workspace) -> None:
    ws = real_workspace.root
    (ws / "VERSION").write_text(
        "ref=v0.3.0\nverified=sha256\ninstalled_at=2026-10-21T00:00:00Z\nversion=0.3.0\n",
        encoding="utf-8",
    )
    real_workspace.ensure_state_dirs()
    lock_dir = real_workspace.state_dir / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    (lock_dir / "deadbeef.lock").write_text(
        '{"pid": 999999999, "purpose": "apply"}', encoding="utf-8"
    )
    checks = {c["name"]: c for c in run_json("doctor", "--workspace", str(ws), "--json")}
    assert checks["installed release"]["ok"]
    assert "v0.3.0" in checks["installed release"]["detail"]
    assert "sha256" in checks["installed release"]["detail"]
    assert (
        not checks["orphaned locks"]["ok"] and "deadbeef.lock" in checks["orphaned locks"]["detail"]
    )
    # an unverified development install is a warning, not an error
    (ws / "VERSION").write_text("ref=main\nverified=none\n", encoding="utf-8")
    checks = {c["name"]: c for c in run_json("doctor", "--workspace", str(ws), "--json")}
    assert (
        not checks["installed release"]["ok"] and checks["installed release"]["level"] == "warning"
    )


def test_policy_command_and_project_layer(real_workspace, make_project) -> None:
    ws = str(real_workspace.root)
    root = make_project("polproj", kind="claude", files=BACKEND)
    out = run_json("policy", "--workspace", ws, "--json")
    assert [layer["layer"] for layer in out["layers"]] == ["default"]
    assert out["verdicts"]["ecc.tdd-workflow"]["claude_code"]["decision"] == "allow"
    assert (
        out["verdicts"]["rea.reverse-engineer-anything"]["claude_code"]["decision"]
        == "require_request"
    )
    (root / ".agent-forge").mkdir()
    (root / ".agent-forge" / "policy.yaml").write_text(
        yaml.safe_dump(
            {"name": "team", "classes": {"hook": "deny"}, "capabilities": {"deny": ["ecc.agent.*"]}}
        ),
        encoding="utf-8",
    )
    out = run_json("policy", str(root), "--workspace", ws, "--json")
    assert [layer["layer"] for layer in out["layers"]] == ["default", "project"]
    assert out["verdicts"]["forge.hook.guard-secrets-python"]["claude_code"]["decision"] == "deny"
    # the project policy shapes forge: no hooks, no ecc agents, even with --hooks granted
    report = run_json("forge", str(root), "--workspace", ws, "--yes", "--hooks", "--json")
    add = {s["label"]: s for s in report["steps"]}["add recommended capabilities"]
    assert add["rejected"]["forge.hook.guard-secrets-python"] == "policy_denied"
    assert add["rejected"]["ecc.agent.planner"] == "policy_denied"
    assert "ecc.security-review" in add["selected"]


def test_drift_remove_repair_audit_cycle(real_workspace, make_project) -> None:
    ws = str(real_workspace.root)
    root = make_project("ops", kind="claude", files=BACKEND)
    run_json("forge", str(root), "--workspace", ws, "--yes", "--shared-files", "--json")
    drift = run_json("drift", str(root), "--workspace", ws, "--json")
    assert drift["drifted"] == 0 and drift["items"]
    skill = root / ".claude" / "skills" / "tdd-workflow" / "SKILL.md"
    skill.write_text("edited\n", encoding="utf-8")
    drift = run_json("drift", str(root), "--workspace", ws, "--json")
    assert drift["drifted"] == 1
    # repair (restore) is a plan: approve + apply
    plan = run_json("repair", str(root), "--workspace", ws, "--strategy", "restore", "--json")
    assert plan["kind"] == "repair:restore" and plan["operations"]
    run("approve", plan["plan_id"], "--workspace", ws)
    run("apply", plan["plan_id"], "--workspace", ws, "--yes")
    assert skill.read_text(encoding="utf-8") != "edited\n"
    assert run_json("drift", str(root), "--workspace", ws, "--json")["drifted"] == 0
    # remove one capability (needs --shared-files only when a section is involved)
    plan = run_json("remove", str(root), "ecc.security-review", "--workspace", ws, "--json")
    assert plan["kind"] == "remove"
    run("approve", plan["plan_id"], "--workspace", ws)
    run("apply", plan["plan_id"], "--workspace", ws, "--yes")
    assert not (root / ".claude" / "skills" / "security-review").exists()
    st = run_json("status", str(root), "--workspace", ws, "--json")
    assert "ecc.security-review" not in {c["capability"] for c in st["capabilities"]}
    assert run_json("validate", str(root), "--workspace", ws, "--json")["ok"]
    events = [r["event"] for r in run_json("audit", "--workspace", ws, "--json")]
    assert "PlanCreated" in events and "PlanApproved" in events and "TransactionCompleted" in events
    run("remove", str(root), "not.managed", "--workspace", ws, expect=6)


def test_self_update_check_and_upgrade_gate(real_workspace, make_project, monkeypatch) -> None:
    from agent_forge import selfupdate

    ws = real_workspace.root
    monkeypatch.setenv(selfupdate.ENV_LAUNCHER, selfupdate.LAUNCHER_PROTOCOL)
    # not an installer install: the check says so and nothing is requested
    out = run_json("self-update", "--check", "--workspace", str(ws), "--json")
    assert out["available"] is False and "no VERSION file" in out["note"]
    (ws / "VERSION").write_text("ref=v0.4.0\nverified=sha256\n", encoding="utf-8")
    monkeypatch.setattr(selfupdate, "latest_release_tag", lambda timeout=5.0: "v0.4.0")
    out = run_json("self-update", "--check", "--workspace", str(ws), "--json")
    assert out == {
        "installed": "v0.4.0",
        "latest": "v0.4.0",
        "available": False,
        "note": "Agent Forge is current",
    }
    # current: self-update requests nothing; upgrade plans with the installed version
    run("self-update", "--workspace", str(ws))
    root = make_project("gate", kind="claude", files=BACKEND)
    plan = run_json("upgrade", str(root), "--workspace", str(ws), "--json")
    assert "Agent Forge is current" in plan["notes"]
    assert not (ws / selfupdate.UPDATE_FILE).exists()
    # newer: upgrade leaves the compared tag for the launcher and exits 16
    monkeypatch.setattr(selfupdate, "latest_release_tag", lambda timeout=5.0: "v0.5.0")
    run("upgrade", str(root), "--workspace", str(ws), expect=16)
    assert (ws / selfupdate.UPDATE_FILE).read_text(encoding="utf-8") == "v0.5.0"
    (ws / selfupdate.UPDATE_FILE).unlink()
    plan = run_json("upgrade", str(root), "--workspace", str(ws), "--no-self-update", "--json")
    assert "self-update check skipped (--no-self-update)" in plan["notes"]
    assert not (ws / selfupdate.UPDATE_FILE).exists()
    # self-update itself: an explicit release is requested even when current
    run("self-update", "--workspace", str(ws), "--release", "v0.4.0", expect=16)
    assert (ws / selfupdate.UPDATE_FILE).read_text(encoding="utf-8") == "v0.4.0"
    (ws / selfupdate.UPDATE_FILE).unlink()
    # without the launcher the engine refuses to pretend
    monkeypatch.delenv(selfupdate.ENV_LAUNCHER)
    result = run("self-update", "--workspace", str(ws), expect=13)
    assert "cannot update itself" in " ".join(result.output.split())
    # the launcher's re-run only reports what is installed now
    out = run_json("self-update", "--workspace", str(ws), "--no-self-update", "--json")
    assert out == {"installed": "v0.4.0"}
