"""`agent-forge setup`: what the one-line installer runs in a project root."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from agent_forge.cli import app
from tests.conftest import unwrap

pytestmark = pytest.mark.e2e
runner = CliRunner()


def run_json(*args: str) -> dict:
    result = runner.invoke(app, list(args), catch_exceptions=False)
    assert result.exit_code == 0, f"{args}\n{result.output}"
    return unwrap(result.stdout)


def test_setup_installs_only_the_entry_skill(real_workspace, make_project) -> None:
    ws = str(real_workspace.root)
    root = make_project("my app", kind="claude")
    before = sorted(
        p.relative_to(root).as_posix() for p in root.rglob("*") if ".git" not in p.parts
    )
    out = run_json("setup", str(root), "--workspace", ws, "--json")
    assert out["installed_version"] == "2.1.0" and len(out["steps"]) == 1
    skill = (root / ".claude/skills/agent-forge-upgrade/SKILL.md").read_text(encoding="utf-8")
    assert "disable-model-invocation: true" in skill
    after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if ".git" not in p.parts)
    added = sorted(set(after) - set(before))
    assert added == [
        ".agent-forge",
        ".agent-forge/managed.json",
        ".claude/skills/agent-forge-upgrade",
        ".claude/skills/agent-forge-upgrade/SKILL.md",
    ]
    managed = unwrap((root / ".agent-forge/managed.json").read_text(encoding="utf-8"))
    assert [c["capability_id"] for c in managed["capabilities"]] == [
        "forge.skill.agent-forge-upgrade"
    ]
    # re-running (a teammate, or an update with nothing new) changes nothing
    again = run_json("setup", str(root), "--workspace", ws, "--json")
    assert again["steps"] == []


def test_setup_leaves_other_managed_capabilities_alone(real_workspace, make_project) -> None:
    ws = str(real_workspace.root)
    root = make_project("managed", kind="claude")
    run_json("forge", str(root), "--workspace", ws, "--yes", "--json")
    before = (root / ".agent-forge/managed.json").read_text(encoding="utf-8")
    out = run_json("setup", str(root), "--workspace", ws, "--json")
    after = unwrap((root / ".agent-forge/managed.json").read_text(encoding="utf-8"))
    ids = {c["capability_id"] for c in after["capabilities"]}
    assert "forge.skill.agent-forge-upgrade" in ids
    assert ids - {"forge.skill.agent-forge-upgrade"} == {
        c["capability_id"] for c in unwrap(before)["capabilities"]
    }
    assert all(
        f.startswith((".claude/skills/agent-forge-upgrade", ".agent-forge"))
        for s in out["steps"]
        for f in s["files"]
    )


def test_setup_installs_codex_variant_when_codex_is_used(real_workspace, make_project) -> None:
    ws = str(real_workspace.root)
    root = make_project("both", kind="both")
    out = run_json("setup", str(root), "--workspace", ws, "--json")
    assert set(out["platforms"]) == {"claude_code", "codex"}
    codex = root / ".agents/skills/agent-forge-upgrade"
    assert (codex / "SKILL.md").is_file()
    assert "allow_implicit_invocation: false" in (codex / "agents/openai.yaml").read_text(
        encoding="utf-8"
    )
