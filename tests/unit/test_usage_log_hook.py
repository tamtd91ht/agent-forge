"""The workspace-authored usage-log hook script, run exactly as Claude Code would run it."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.conftest import REAL_REGISTRY

SCRIPT = REAL_REGISTRY / "capabilities/forge.hook.usage-log/assets/claude_code/scripts/usage_log.py"


def _run(payload: object, project: Path) -> subprocess.CompletedProcess[str]:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT)],
        input=text,
        capture_output=True,
        text=True,
        env={"CLAUDE_PROJECT_DIR": str(project), "PATH": ""},
    )


def test_records_skills_and_agents_only_and_never_blocks(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    cases = [
        {
            "tool_name": "Skill",
            "tool_input": {"skill": "tdd", "args": "secret prompt"},
            "session_id": "0123456789abcdef",
        },
        {
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "code-reviewer", "prompt": "review"},
        },
        {"tool_name": "Task", "tool_input": {"subagent_type": "planner"}},
        {"tool_name": "Bash", "tool_input": {"command": "ls"}},  # not recorded
        {"tool_name": "Skill", "tool_input": {}},  # nothing to record
        "{not json",
        "[1, 2]",
    ]
    for payload in cases:
        r = _run(payload, project)
        assert r.returncode == 0, payload
        assert r.stderr == ""
    log = project / ".agent-forge" / "usage.jsonl"
    lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [(e["kind"], e["id"]) for e in lines] == [
        ("skill", "tdd"),
        ("agent", "code-reviewer"),
        ("agent", "planner"),
    ]
    assert lines[0]["session"] == "01234567" and lines[1]["session"] is None
    assert set(lines[0]) == {"at", "kind", "id", "session"}  # no prompt, no args, no paths
    assert "secret prompt" not in log.read_text(encoding="utf-8")
    assert (project / ".agent-forge" / ".gitignore").read_text(encoding="utf-8") == "usage.jsonl\n"


def test_unwritable_project_is_not_an_error(tmp_path: Path) -> None:
    r = _run({"tool_name": "Skill", "tool_input": {"skill": "x"}}, tmp_path / "missing" / "x.txt")
    assert r.returncode == 0
