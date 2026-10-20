"""The workspace-authored git guard hook script, run exactly as Claude Code would run it."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from tests.conftest import REAL_REGISTRY

SCRIPT = (
    REAL_REGISTRY
    / "capabilities/forge.hook.guard-dangerous-git/assets/claude_code/scripts/guard_git.py"
)


def _run(command: str) -> subprocess.CompletedProcess[str]:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT)], input=payload, capture_output=True, text=True
    )


@pytest.mark.parametrize(
    "command",
    [
        "git push --force origin main",
        "git push -f",
        "git push --force-with-lease",
        "git push origin +main",
        "git push origin :old-branch",
        "git push --delete origin topic",
        "git -C repo reset --hard HEAD~1",
        "git clean -fdx",
        "git branch -D topic",
        "git checkout -- .",
        "git restore .",
        "git stash clear",
        "npm test && git reset --hard",
        "GIT_TRACE=1 git push -f",
    ],
)
def test_destructive_git_is_blocked(command: str) -> None:
    r = _run(command)
    assert r.returncode == 2, command
    assert "agent-forge guard: blocked" in r.stderr


@pytest.mark.parametrize(
    "command",
    [
        "git push origin main",
        "git push -u origin feature",
        "git reset HEAD~1",
        "git clean -n",
        "git branch -d merged",
        "git checkout -b feature",
        "git restore --staged .",
        "git stash pop",
        "echo 'git push --force'",
        "ls -la",
    ],
)
def test_safe_commands_pass(command: str) -> None:
    assert _run(command).returncode == 0, command


def test_malformed_payload_fails_open() -> None:
    r = subprocess.run(
        [sys.executable, "-I", str(SCRIPT)], input="not json", capture_output=True, text=True
    )
    assert r.returncode == 0
