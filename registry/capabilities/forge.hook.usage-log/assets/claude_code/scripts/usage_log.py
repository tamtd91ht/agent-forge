"""Agent Forge hook (PostToolUse, Skill | Agent | Task): record that a skill or subagent ran.

Appends one JSON line to `<project>/.agent-forge/usage.jsonl`:

    {"at": "2026-10-21T02:00:00Z", "kind": "skill", "id": "tdd", "session": "a1b2c3d4"}

Only the tool kind, the skill / subagent name, a UTC timestamp and the first 8 characters of
the session id are written: no prompt, no file content, no path. The file stays local
(`.agent-forge/.gitignore` is created once to keep it out of git). `agent-forge usage` reads
it. The hook never blocks anything: every failure exits 0. Standard library only.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

LOG_REL = Path(".agent-forge") / "usage.jsonl"
GITIGNORE_REL = Path(".agent-forge") / ".gitignore"
MAX_LOG_BYTES = 8_000_000  # stop appending past this size rather than grow without bound


def _entry(payload: dict) -> dict | None:
    tool = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    if tool == "Skill":
        ident = tool_input.get("skill") or tool_input.get("name")
        kind = "skill"
    elif tool in ("Agent", "Task"):
        ident = tool_input.get("subagent_type")
        kind = "agent"
    else:
        return None
    if not isinstance(ident, str) or not ident.strip():
        return None
    session = payload.get("session_id")
    return {
        "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "kind": kind,
        "id": ident.strip()[:120],
        "session": session[:8] if isinstance(session, str) else None,
    }


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0
    entry = _entry(payload)
    if entry is None:
        return 0
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    try:
        base = Path(root)
        log = base / LOG_REL
        log.parent.mkdir(parents=True, exist_ok=True)
        gitignore = base / GITIGNORE_REL
        if not gitignore.exists():
            gitignore.write_text("usage.jsonl\n", encoding="utf-8")
        if log.exists() and log.stat().st_size > MAX_LOG_BYTES:
            return 0
        with log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
