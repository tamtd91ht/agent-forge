"""`lint` check 9: a hook script that only writes to stdout never reaches the model."""

from __future__ import annotations

import json
from pathlib import Path

from agent_forge.lint import lint_project

STDOUT_ONLY = 'import json, sys\npayload = json.load(sys.stdin)\nprint("tests may be needed")\n'
STDERR = 'import sys\nsys.stderr.write("run the tests\\n")\nsys.exit(2)\n'
JSON_DOC = 'import json\nprint(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": "x"}}))\n'
SHELL_STDOUT = '#!/bin/sh\necho "remember the changelog"\n'


def _project(root: Path, scripts: dict[str, str], commands: dict[str, str]) -> Path:
    (root / "pyproject.toml").parent.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text("[project]\nname='x'\nversion='0'\n", encoding="utf-8")
    (root / "CLAUDE.md").write_text("# p\n", encoding="utf-8")
    for rel, text in scripts.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    groups = [
        {"matcher": "Edit", "hooks": [{"type": "command", "command": cmd}]}
        for cmd in commands.values()
    ]
    (root / ".claude").mkdir(exist_ok=True)
    (root / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {"PostToolUse": groups}}), encoding="utf-8"
    )
    return root


def test_stdout_only_hook_scripts_are_flagged_and_the_rest_pass(tmp_path: Path) -> None:
    root = _project(
        tmp_path / "p",
        {
            ".claude/hooks/notify.py": STDOUT_ONLY,
            ".claude/hooks/guard.py": STDERR,
            ".claude/hooks/stop.py": JSON_DOC,
            ".claude/hooks/remind.sh": SHELL_STDOUT,
        },
        {
            "a": 'python "$CLAUDE_PROJECT_DIR/.claude/hooks/notify.py"',
            "b": "python .claude/hooks/guard.py",
            "c": "python .claude/hooks/stop.py",
            "d": "sh .claude/hooks/remind.sh",
            "e": "ruff format .",  # no script named: nothing to read
        },
    )
    rep = lint_project(root)
    flagged = sorted(f.path for f in rep.findings if f.check == "hook_output")
    assert flagged == [".claude/hooks/notify.py", ".claude/hooks/remind.sh"]
    assert all(f.level == "warning" for f in rep.findings if f.check == "hook_output")
    assert rep.counts["hooks"] == 5
