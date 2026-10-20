"""Agent Forge hook (PreToolUse, Bash): refuse git commands that destroy work or history.

Reads the hook payload from stdin, inspects `tool_input.command`, and exits with code 2
(which blocks the tool call and feeds stderr back to the agent) when any git invocation in it
force-pushes, deletes remote refs, hard-resets, cleans untracked files, force-deletes a
branch, discards working-tree changes wholesale, or drops stashes. Everything else, including
a plain `git push`, passes. Standard library only.
"""

from __future__ import annotations

import json
import re
import shlex
import sys

_SEGMENT_SPLIT = re.compile(r"&&|\|\||[;|\n]")
_GIT_GLOBAL_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}


def _git_args(segment: str) -> list[str] | None:
    """Arguments after `git` (global options removed), or None if not a git command."""
    try:
        tokens = shlex.split(segment, posix=True)
    except ValueError:
        tokens = segment.split()
    while tokens and "=" in tokens[0] and not tokens[0].startswith("-"):
        tokens = tokens[1:]  # leading VAR=value assignments
    if not tokens or tokens[0].replace("\\", "/").rsplit("/", 1)[-1] not in ("git", "git.exe"):
        return None
    args = tokens[1:]
    while args and args[0].startswith("-"):
        args = args[2:] if args[0] in _GIT_GLOBAL_WITH_VALUE else args[1:]
    return args


def _short_flags(args: list[str]) -> str:
    return "".join(a[1:] for a in args if a.startswith("-") and not a.startswith("--"))


def _reason(args: list[str]) -> str | None:
    if not args:
        return None
    sub, rest = args[0], args[1:]
    shorts = _short_flags(rest)
    if sub == "push":
        if (
            "f" in shorts
            or "d" in shorts
            or any(a.startswith(("--force", "--mirror", "--delete", "--prune")) for a in rest)
            or any(a.startswith(("+", ":")) for a in rest if not a.startswith("-"))
        ):
            return "force-push or remote ref deletion rewrites shared history"
    elif sub == "reset" and ("--hard" in rest or "--keep" in rest or "--merge" in rest):
        return "hard reset discards uncommitted work"
    elif sub == "clean" and not ("n" in shorts or "--dry-run" in rest):
        if "f" in shorts or "--force" in rest:
            return "clean deletes untracked files permanently"
    elif sub == "branch" and ("D" in shorts or ("--delete" in rest and "--force" in rest)):
        return "force-deleting a branch can lose unmerged commits"
    elif sub == "checkout" and ("." in rest or "f" in shorts or "--force" in rest):
        return "checkout of `.` or --force discards working-tree changes"
    elif sub == "restore" and "." in rest and ("--staged" not in rest or "--worktree" in rest):
        return "restore of `.` discards working-tree changes"
    elif sub == "stash" and rest[:1] in (["drop"], ["clear"]):
        return "dropping stashes loses saved work"
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0  # malformed payload: never block on our own bug
    tool_input = payload.get("tool_input") if isinstance(payload, dict) else None
    command = str((tool_input or {}).get("command") or "")
    for segment in _SEGMENT_SPLIT.split(command):
        args = _git_args(segment.strip())
        why = _reason(args) if args is not None else None
        if why:
            sys.stderr.write(
                f"agent-forge guard: blocked `{segment.strip()}`: {why}. "
                "If it is really intended, ask the user to run it themselves.\n"
            )
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
