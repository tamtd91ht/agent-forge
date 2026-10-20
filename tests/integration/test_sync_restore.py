"""`sync` restores managed sections in shared files too (the content was already approved
when it was committed), through the ordinary journaled apply engine."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from agent_forge.cli import app
from tests.conftest import unwrap

runner = CliRunner()
BACKEND = {
    "pyproject.toml": "[project]\nname='api'\nversion='0'\ndependencies=['fastapi','pytest']\n",
}


def run_json(*args: str, expect: int = 0) -> dict:
    result = runner.invoke(app, list(args), catch_exceptions=False)
    assert result.exit_code == expect, f"{args}\n{result.output}"
    return unwrap(result.stdout)


@pytest.mark.parametrize("delete_file", [False, True])
def test_sync_restores_a_managed_section_in_claude_md(
    real_workspace, make_project, delete_file: bool
) -> None:
    ws = str(real_workspace.root)
    root = make_project("section-sync", kind="claude", files=BACKEND)
    run_json("forge", str(root), "--workspace", ws, "--yes", "--shared-files", "--json")
    claude_md = root / "CLAUDE.md"
    assert "agent-forge:begin" in claude_md.read_text(encoding="utf-8")
    if delete_file:
        claude_md.unlink()
    else:
        claude_md.write_text("# Project\n\nUser instructions.\n", encoding="utf-8")
    out = run_json("sync", str(root), "--workspace", ws, "--yes", "--json")
    assert out["status"] == "restored"
    restored = claude_md.read_text(encoding="utf-8")
    assert "agent-forge:begin" in restored
    if not delete_file:
        assert restored.startswith("# Project\n\nUser instructions.\n")  # user text kept
    assert run_json("check", str(root), "--workspace", ws, "--json")["ok"]
