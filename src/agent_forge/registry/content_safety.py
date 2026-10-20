"""Static content-safety scan of curated assets (roadmap D1).

Curated skills, rules and hooks are text an agent will follow. A reviewer must see, before an
entry is installable, every place where that text pipes a download into a shell, deletes
broadly, escalates privileges, writes global configuration, embeds a credential, or tries to
override the agent's instructions. Each finding is an error until the capability's manifest
acknowledges it (`review.acknowledged_findings`: rule, asset path, reason): a teaching
example in a security skill is legitimate, an unexplained one is not.

Patterns are deliberately simple and explainable; this is a review aid, not a malware
detector, and passing it does not make content safe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

RULES: dict[str, tuple[re.Pattern[str], str]] = {
    "pipe-to-shell": (
        re.compile(
            r"\b(curl|wget|iwr|irm|Invoke-WebRequest|Invoke-RestMethod)\b[^\n|]*\|\s*"
            r"(sudo\s+)?(ba|z|da)?sh\b|\b(irm|iwr)\b[^\n|]*\|\s*iex\b",
            re.IGNORECASE,
        ),
        "downloads code and runs it in a shell",
    ),
    "destructive-delete": (
        re.compile(
            r"\brm\s+-[a-z]*r[a-z]*f?\b[^\n]*?\s(/|~|\$HOME|\*)(\s|$)|Remove-Item\b[^\n]*-Recurse[^\n]*\s[A-Z]:\\\s",
            re.IGNORECASE,
        ),
        "recursive delete of a root, home or wildcard path",
    ),
    "privilege-escalation": (
        re.compile(r"(^|[\s`;&|(])sudo\s+\S|\bchmod\s+(-R\s+)?777\b"),
        "runs with elevated privileges or opens permissions to everyone",
    ),
    "global-config-write": (
        re.compile(
            r"\bgit\s+config\s+--global\b|\bnpm\s+(i|install)\s+(-g|--global)\b"
            r"|\bpip\s+install\b[^\n]*--user\b|~/\.claude/(settings|CLAUDE)|~/\.codex/",
            re.IGNORECASE,
        ),
        "changes user-global configuration outside the project",
    ),
    "embedded-secret": (
        re.compile(
            r"\bAKIA[0-9A-Z]{16}\b|\bgh[pousr]_[A-Za-z0-9]{36,}\b|\bsk-[A-Za-z0-9]{32,}\b"
            r"|\bxox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
        ),
        "looks like a real credential",
    ),
    "instruction-override": (
        re.compile(
            r"\b(ignore|disregard|forget)\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier|"
            r"system|user'?s?)\s+(instructions|rules|prompts?|messages)\b"
            r"|\byou\s+are\s+no\s+longer\b|\bdo\s+not\s+(tell|inform)\s+the\s+user\b",
            re.IGNORECASE,
        ),
        "tries to override the agent's or the user's instructions",
    ),
}

TEXT_SUFFIXES = (
    ".md",
    ".txt",
    ".sh",
    ".py",
    ".js",
    ".mjs",
    ".cjs",
    ".ps1",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
)


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str  # relative to the capability's assets/ directory
    line: int
    excerpt: str

    @property
    def message(self) -> str:
        return (
            f"{self.rule} in assets/{self.path}:{self.line}: {RULES[self.rule][1]} ({self.excerpt})"
        )


def scan_assets(assets_dir: Path) -> list[Finding]:
    findings: list[Finding] = []
    if not assets_dir.is_dir():
        return findings
    for path in sorted(assets_dir.rglob("*")):
        if not path.is_file() or path.is_symlink() or not path.name.lower().endswith(TEXT_SUFFIXES):
            continue
        if path.name.startswith("LICENSE"):
            continue
        rel = path.relative_to(assets_dir).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            for rule, (pattern, _why) in RULES.items():
                m = pattern.search(line)
                if m:
                    findings.append(Finding(rule, rel, lineno, line.strip()[:100]))
    return findings
