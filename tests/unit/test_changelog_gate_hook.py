"""The workspace-authored changelog gate, run exactly as Claude Code would run it, against a
disposable git repository with a real staged set."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import REAL_REGISTRY

SCRIPT = (
    REAL_REGISTRY
    / "capabilities/forge.hook.changelog-gate/assets/claude_code/scripts/changelog_gate.py"
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "svc"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "t")
    (r / "app.py").write_text("x = 1\n", encoding="utf-8")
    (r / "CHANGELOG.md").write_text("# Changelog\n\n## Unreleased\n", encoding="utf-8")
    _git(r, "add", ".")
    _git(r, "commit", "-q", "-m", "chore: init")
    (r / "app.py").write_text("x = 2\n", encoding="utf-8")
    _git(r, "add", "app.py")
    return r


def _run(command: str, cwd: Path | None) -> subprocess.CompletedProcess[str]:
    payload: dict = {"tool_name": "Bash", "tool_input": {"command": command}}
    if cwd is not None:
        payload["cwd"] = str(cwd)
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "command",
    [
        'git commit -m "feat: add thing"',
        "git commit -m 'fix(api): null check'",
        'git commit -q -m "feat!: breaking"',
        'git add -A && git commit -m "feat: chained"',
        "git commit -F - <<'EOF'\nfeat: heredoc subject\n\nbody\nEOF",
    ],
)
def test_feat_fix_without_changelog_is_blocked(repo: Path, command: str) -> None:
    r = _run(command, repo)
    assert r.returncode == 2, command
    assert "CHANGELOG.md" in r.stderr


def test_staged_changelog_lets_the_commit_through(repo: Path) -> None:
    (repo / "CHANGELOG.md").write_text("# Changelog\n\n## Unreleased\n- thing\n", encoding="utf-8")
    _git(repo, "add", "CHANGELOG.md")
    assert _run('git commit -m "feat: add thing"', repo).returncode == 0


def test_git_dash_c_points_at_the_repository(repo: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    r = _run(f'git -C "{repo}" commit -m "fix: from elsewhere"', elsewhere)
    assert r.returncode == 2


@pytest.mark.parametrize(
    "command",
    [
        'git commit -m "chore: tidy"',
        'git commit -m "docs: readme"',
        'git commit -m "feat: internal only [skip-changelog]"',
        "git status",
        'echo "git commit -m feat: not a commit"',
    ],
)
def test_other_commands_pass(repo: Path, command: str) -> None:
    assert _run(command, repo).returncode == 0, command


def test_outside_a_repository_fails_open(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert _run('git commit -m "feat: nowhere"', plain).returncode == 0


def test_malformed_payload_fails_open() -> None:
    r = subprocess.run(
        [sys.executable, "-I", str(SCRIPT)], input="not json", capture_output=True, text=True
    )
    assert r.returncode == 0
