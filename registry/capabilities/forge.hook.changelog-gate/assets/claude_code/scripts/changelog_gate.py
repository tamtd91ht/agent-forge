"""Agent Forge hook (PreToolUse, Bash): a feat/fix commit must stage a CHANGELOG entry.

Reads the hook payload from stdin. When `tool_input.command` is a `git commit` whose message
starts with `feat` or `fix` (Conventional Commits, any scope, `!` allowed) and no staged
file is named `CHANGELOG.md` (at any depth), exits with code 2, which blocks the call and
tells the agent to add the changelog line first. `[skip-changelog]` in the message bypasses
the gate for a change with no user-visible effect. Honours `git -C <path>`; otherwise runs
`git diff --cached` in the payload's `cwd`. Reads git state only, writes nothing, standard
library only; anything it cannot parse passes.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys

_SEGMENT_SPLIT = re.compile(r"&&|\|\||[;|\n]")
_TYPE_RE = re.compile(r"^(feat|fix)(\([^)]*\))?!?:", re.IGNORECASE)
_BYPASS = "[skip-changelog]"


def _tokens(segment: str) -> list[str]:
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


def _git_commit(segment: str) -> tuple[str | None, str] | None:
    """(repo path or None, message) when the segment is a git commit with an inline message."""
    tokens = _tokens(segment)
    while tokens and "=" in tokens[0] and not tokens[0].startswith("-"):
        tokens = tokens[1:]
    if not tokens or tokens[0].replace("\\", "/").rsplit("/", 1)[-1] not in ("git", "git.exe"):
        return None
    repo: str | None = None
    args = tokens[1:]
    while args and args[0].startswith("-"):
        if args[0] == "-C" and len(args) > 1:
            repo = args[1]
            args = args[2:]
        elif args[0] in ("-c", "--git-dir", "--work-tree", "--namespace"):
            args = args[2:]
        else:
            args = args[1:]
    if not args or args[0] != "commit":
        return None
    message: list[str] = []
    rest = args[1:]
    i = 0
    while i < len(rest):
        a = rest[i]
        if a in ("-m", "--message") and i + 1 < len(rest):
            message.append(rest[i + 1])
            i += 2
            continue
        if a.startswith("--message="):
            message.append(a[len("--message=") :])
        elif a.startswith("-m") and len(a) > 2:
            message.append(a[2:])
        i += 1
    heredoc = re.search(r"<<-?\s*'?(\w+)'?\s*\n(.*?)\n\1", segment, re.DOTALL)
    if heredoc:
        message.append(heredoc.group(2))
    return repo, "\n".join(message)


def _staged(repo: str | None, cwd: str | None) -> list[str] | None:
    cmd = ["git"]
    if repo:
        cmd += ["-C", repo]
    cmd += ["diff", "--cached", "--name-only"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10, cwd=cwd or None)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0
    command = str(tool_input.get("command") or "")
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else None
    for segment in _SEGMENT_SPLIT.split(command) if "<<" not in command else [command]:
        found = _git_commit(segment)
        if found is None:
            continue
        repo, message = found
        first = message.strip().splitlines()[0].strip() if message.strip() else ""
        if not _TYPE_RE.match(first) or _BYPASS in message.lower():
            continue
        staged = _staged(repo, cwd)
        if staged is None:
            return 0  # not a repository we can inspect: never block on our own limits
        if any(p.replace("\\", "/").rsplit("/", 1)[-1] == "CHANGELOG.md" for p in staged):
            continue
        sys.stderr.write(
            "agent-forge guard: blocked a feat/fix commit with no CHANGELOG.md staged. "
            "Add a line under the Unreleased section (synthesised from the diff, not the "
            "commit subject) and stage it; use [skip-changelog] in the message only when "
            "nothing user-visible changed.\n"
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
