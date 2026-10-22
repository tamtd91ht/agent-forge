"""Agent Forge hook (PreToolUse, Edit|Write|MultiEdit): refuse to write a credential literal.

Reads the hook payload from stdin and inspects the text that is about to be written
(`content` for Write, `new_string` for Edit, every `edits[].new_string` for MultiEdit). Exits
with code 2 (which blocks the tool call and feeds stderr back to the agent) when that text
contains an obvious secret literal: a password or API-key assignment with an inline value, a
cloud access-key id, a PEM private-key block, a JWT, a database or broker URL with a password
in it, a known token prefix. Indirection (`${VAR}`, `os.environ[...]`, `@Value`) is never
flagged; placeholders (`changeme`, `<your-key>`, `xxx`) are allowed. Test, fixture, mock,
example and documentation paths are skipped. Never reads the file itself. Standard library
only; a malformed payload never blocks.

Companion of guard_secrets.py (which refuses edits to secret *files* by name): this one
looks at secret *values* in any file.
"""

from __future__ import annotations

import json
import re
import sys

PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"""(?i)\b(password|passwd|pwd)\s*[:=]\s*["'][^"'$\{<][^"']{5,}["']"""),
        "password literal",
    ),
    (
        re.compile(
            r"""(?i)\b(api[_\-]?key|access[_\-]?key|secret[_\-]?key|client[_\-]?secret|auth[_\-]?token)"""
            r"""\s*[:=]\s*["'][^"'$\{<][^"']{11,}["']"""
        ),
        "API key / secret literal",
    ),
    (re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"), "AWS access key id"),
    (
        re.compile(r"-{5}BEGIN[ ]+(?:RSA|EC|DSA|OPENSSH|PGP)?[ ]*PRIVATE[ ]+KEY(?: BLOCK)?-{5}"),
        "private-key block",
    ),
    (
        re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),
        "JWT literal",
    ),
    (
        re.compile(
            r"(?i)\b(mongodb(?:\+srv)?|postgres(?:ql)?|mysql|redis|rediss|amqps?|mssql)"
            r"://[^\s:@/]+:[^\s@/]{3,}@"
        ),
        "connection string with an inline password",
    ),
    (
        re.compile(
            r"\b(gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,}|xox[baprs]-[A-Za-z0-9-]{10,}"
            r"|sk_live_[A-Za-z0-9]{16,}|sk-[A-Za-z0-9]{32,})\b"
        ),
        "known token format",
    ),
)

PLACEHOLDER = re.compile(
    r"(?i)(changeme|change-me|placeholder|example|dummy|sample|your[_\-]|xxx+|\*{3,}|<[^>]+>|\$\{)"
)

SKIP_PATH_PARTS = (
    "/test/",
    "/tests/",
    "/__tests__/",
    "/spec/",
    "/fixtures/",
    "/mocks/",
    "/__mocks__/",
    "/testdata/",
    "/examples/",
    "/docs/",
    "/.claude/",
    "/.agents/",
)
SKIP_SUFFIXES = (
    ".md",
    ".mdx",
    ".rst",
    ".txt",
    ".csv",
    ".lock",
    ".log",
    ".example",
    ".sample",
    ".template",
    ".dist",
)


def should_skip(path: str) -> bool:
    norm = "/" + path.replace("\\", "/").lower().lstrip("/")
    return any(part in norm for part in SKIP_PATH_PARTS) or norm.endswith(SKIP_SUFFIXES)


def pending_text(tool_input: dict) -> str:
    parts: list[str] = []
    if isinstance(tool_input.get("content"), str):
        parts.append(tool_input["content"])
    if isinstance(tool_input.get("new_string"), str):
        parts.append(tool_input["new_string"])
    for edit in tool_input.get("edits") or []:
        if isinstance(edit, dict) and isinstance(edit.get("new_string"), str):
            parts.append(edit["new_string"])
    return "\n".join(parts)


def findings(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for pattern, label in PATTERNS:
        for m in pattern.finditer(text):
            snippet = m.group(0)
            if PLACEHOLDER.search(snippet):
                continue
            out.append((label, snippet[:60] + ("…" if len(snippet) > 60 else "")))
    return out


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0  # malformed payload: never block on our own bug
    if not isinstance(payload, dict):
        return 0
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0
    path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
    if not path or should_skip(path):
        return 0
    hits = findings(pending_text(tool_input))
    if not hits:
        return 0
    lines = [f"agent-forge guard: blocked a credential literal in {path}:"]
    lines += [f"  - {label}: {snippet}" for label, snippet in hits[:5]]
    if len(hits) > 5:
        lines.append(f"  … and {len(hits) - 5} more")
    lines.append(
        "Read the value from the environment or a secret store (${VAR}, os.environ, @Value) "
        "instead; keep test fixtures under a test/ or fixtures/ path."
    )
    sys.stderr.write("\n".join(lines) + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
