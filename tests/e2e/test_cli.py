"""End-to-end through the CLI (Typer runner) against the real curated registry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent_forge.cli import app

pytestmark = pytest.mark.e2e
runner = CliRunner()


def run(*args: str, expect: int = 0, input: str | None = None):
    result = runner.invoke(app, list(args), input=input, catch_exceptions=False)
    assert result.exit_code == expect, f"{args}\nexit={result.exit_code}\n{result.output}"
    return result


def plan_id_from(output: str) -> str:
    return json.loads(output)["plan_id"]


def test_help_and_version() -> None:
    out = run("--help").stdout
    for cmd in (
        "init",
        "scan",
        "assign",
        "upgrade",
        "diff",
        "approve",
        "apply",
        "validate",
        "status",
        "rollback",
    ):
        assert cmd in out
    assert "agent-forge 0." in run("--version").stdout


def test_init_is_idempotent(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    first = run("init", "--workspace", str(ws)).stdout
    assert "created" in first
    second = run("init", "--workspace", str(ws)).stdout
    assert (
        "created" not in second.split("registry:")[0]
        or "agent-forge.yaml" not in second.split("exists")[0]
    )
    assert (ws / "agent-forge.yaml").is_file()
    assert (ws / "registry" / "capabilities").is_dir()
    assert (ws / "sources" / "sources.yaml").is_file()


def test_full_cli_lifecycle(real_workspace, make_project) -> None:
    ws = str(real_workspace.root)
    root = make_project(
        "next app",
        kind="claude",
        files={
            "package.json": json.dumps(
                {
                    "name": "demo",
                    "dependencies": {"next": "15", "react": "19"},
                    "devDependencies": {"vitest": "2"},
                    "scripts": {"test": "vitest"},
                }
            ),
            "tsconfig.json": "{}",
        },
    )
    # scan: read-only, report outside target
    out = run("scan", str(root), "--workspace", ws, "--json").stdout
    profile = json.loads(out)
    assert "claude_code" in [p["platform"] for p in profile["platforms"]]
    assert not (root / ".agent-forge").exists()
    # catalog works
    ids = {c["id"] for c in json.loads(run("catalog", "--workspace", ws, "--json").stdout)}
    assert "ecc.tdd-workflow" in ids
    assert (
        "ecc.tdd-workflow" in run("catalog", "show", "ecc.tdd-workflow", "--workspace", ws).stdout
    )
    only_codex = json.loads(
        run("catalog", "--workspace", ws, "--platform", "codex", "--json").stdout
    )
    assert all("codex" in c["platforms"] for c in only_codex) and only_codex
    # assign
    out = run("assign", str(root), "--workspace", ws, "--want", "security", "--json").stdout
    plan = json.loads(out)
    pid = plan["plan_id"]
    selected = {s["capability_id"] for s in plan["selected"]}
    assert "ecc.security-review" in selected and "uiux.guidelines" in selected
    rejected = {r["capability_id"]: r["category"] for r in plan["rejected"]}
    assert rejected["rea.reverse-engineer-anything"] == "not_applicable"  # tag-only
    assert rejected["uiux.full-toolkit"] == "needs_runtime"  # frontend: hinted, not installed
    assert "ecc.coding-standards" in rejected and "ecc.rules.common" in selected
    # diff
    out = run("diff", pid, "--workspace", ws, "--json").stdout
    diffs = json.loads(out)
    assert any(d["path"] == "CLAUDE.md" and d["extra_approval"] for d in diffs)
    assert not any(d["stale"] for d in diffs)
    # approve requires --shared-files because CLAUDE.md changes
    run("approve", pid, "--workspace", ws, expect=6)
    # hooks and MCP servers are separate approval classes
    assert "forge.hook.guard-secrets-node" in selected and "mcp.context7" in selected
    run("approve", pid, "--workspace", ws, "--shared-files", expect=6)
    run("approve", pid, "--workspace", ws, "--shared-files", "--hooks", "--mcp")
    # apply without tty and without --yes is refused
    run("apply", pid, "--workspace", ws, expect=6)
    out = run("apply", pid, "--workspace", ws, "--yes", "--json").stdout
    tx = json.loads(out)
    assert tx["status"] == "completed"
    assert (root / ".claude" / "skills" / "security-review" / "SKILL.md").is_file()
    assert (root / ".claude" / "skills" / "security-review" / "LICENSE-ECC.txt").is_file()
    claude_md = (root / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude_md.startswith("# Project\n\nUser instructions.\n")
    # validate + status
    out = run("validate", str(root), "--workspace", ws, "--json").stdout
    assert json.loads(out)["ok"]
    out = run("status", str(root), "--workspace", ws, "--json").stdout
    st = json.loads(out)
    assert {c["capability"] for c in st["capabilities"]} >= {
        "ecc.security-review",
        "forge.managed-notice",
    }
    # applying twice is refused (stale: files now exist)
    run("apply", pid, "--workspace", ws, "--yes", expect=7)
    # user modification then rollback
    skill = root / ".claude" / "skills" / "tdd-workflow" / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\nmine\n", encoding="utf-8")
    run("rollback", tx["transaction_id"], "--workspace", ws, "--yes", expect=11)
    out = run(
        "rollback", tx["transaction_id"], "--workspace", ws, "--yes", "--partial", "--json"
    ).stdout
    assert json.loads(out)["status"] == "completed"
    assert skill.read_text(encoding="utf-8").endswith("mine\n")
    assert not (root / ".claude" / "skills" / "security-review").exists()
    assert "agent-forge:begin" not in (root / "CLAUDE.md").read_text(encoding="utf-8")
    assert (
        (root / "CLAUDE.md")
        .read_text(encoding="utf-8")
        .startswith("# Project\n\nUser instructions.\n")
    )


def test_upgrade_without_managed_state(real_workspace, make_project) -> None:
    root = make_project("plain2")
    out = run("upgrade", str(root), "--workspace", str(real_workspace.root), "--json").stdout
    plan = json.loads(out)
    assert plan["operations"] == []


def test_unknown_plan_and_bad_target_exit_codes(real_workspace, tmp_path: Path) -> None:
    ws = str(real_workspace.root)
    run("diff", "plan-does-not-exist", "--workspace", ws, expect=6)
    run("scan", str(tmp_path / "missing"), "--workspace", ws, expect=5)
    run("scan", str(tmp_path), "--workspace", str(tmp_path / "no-ws"), expect=3)


def test_init_refresh_registry_recopies_seed_and_keeps_own_capabilities(tmp_path: Path) -> None:
    from tests.conftest import base_manifest, skill_assets, write_capability

    ws = tmp_path / "ws"
    run("init", "--workspace", str(ws))
    tdd = ws / "registry" / "capabilities" / "ecc.tdd-workflow" / "assets" / "claude_code"
    skill = tdd / "tdd-workflow" / "SKILL.md"
    fresh = skill.read_text(encoding="utf-8")
    skill.write_text("stale copy\n", encoding="utf-8")
    stray = tdd / "tdd-workflow" / "removed-upstream.md"
    stray.write_text("x\n", encoding="utf-8")
    write_capability(ws / "registry", base_manifest("mine.local"), skill_assets("local"))

    run("init", "--workspace", str(ws))  # plain init never touches an existing registry
    assert skill.read_text(encoding="utf-8") == "stale copy\n"

    out = run("init", "--workspace", str(ws), "--refresh-registry").stdout
    assert "refreshed" in out
    assert skill.read_text(encoding="utf-8") == fresh
    assert not stray.exists()
    assert (ws / "registry" / "capabilities" / "mine.local" / "capability.yaml").is_file()
