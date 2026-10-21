"""Lint the agent configuration a project already has (ADR-0007, the frictionless entry).

Read-only, no workspace, no catalog, no LLM, under a few seconds. It answers four questions
about `CLAUDE.md` / `AGENTS.md` / `GEMINI.md`, rules, skills, agents, hooks and MCP servers:

1. How much always-loaded context does every session pay, and for which files?
2. Which rules repeat each other (duplicate paragraphs, near-duplicate files)?
3. Is a credential sitting in an agent file or MCP config?
4. Does a hook run something the content-safety rules flag?

It never proposes a capability; that is `/agent-forge-upgrade`. Contradictions between
rules need judgement and belong to the skill's `conflicts` ground, not here.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_forge.apply.filesystem_safety import resolve_in_root
from agent_forge.errors import SafetyViolation
from agent_forge.registry.content_safety import RULES
from agent_forge.scanner.project_profile import scan_project
from agent_forge.util import normalize_newlines, parse_frontmatter

MAX_FILE_BYTES = 1_000_000
MIN_PARAGRAPH_CHARS = 80
SHINGLE_WORDS = 8
NEAR_DUPLICATE_JACCARD = 0.5
MIN_FILE_CHARS_FOR_SIMILARITY = 200

# Keys whose values must never be literal secrets in an agent file or MCP config.
_SECRET_KEY_RE = re.compile(
    r"(?i)^(.*(password|passwd|secret|token|api[_-]?key|private[_-]?key|credential).*)$"
)
_PLACEHOLDER_RE = re.compile(
    r"^\s*(\$\{?[A-Z_]+\}?|<[^>]+>|\$[A-Za-z_]+|your[-_ ].*|xxx+|\.\.\.|\*+)\s*$", re.I
)
_HOOK_RULES = tuple(r for r in RULES if r not in ("embedded-secret", "instruction-override"))


@dataclass
class ContextFile:
    path: str
    kind: str
    chars: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class LintFinding:
    level: str  # error | warning | info
    check: str  # context | duplicate | secret | hook | mcp | injection | budget
    path: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class LintReport:
    target: str
    platforms: list[str]
    always_on_total: int = 0
    files: list[ContextFile] = field(default_factory=list)
    findings: list[LintFinding] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    budget: int | None = None

    @property
    def errors(self) -> list[LintFinding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "target": self.target,
            "platforms": self.platforms,
            "always_on_total": self.always_on_total,
            "budget": self.budget,
            "files": [f.to_dict() for f in self.files],
            "counts": self.counts,
            "findings": [f.to_dict() for f in self.findings],
        }


# ---- reading -------------------------------------------------------------------------------


def _read(root: Path, rel: str) -> str | None:
    try:
        p = resolve_in_root(root, rel)
    except SafetyViolation:
        return None
    if not p.is_file() or p.is_symlink():
        return None
    try:
        with p.open("rb") as fh:
            raw = fh.read(MAX_FILE_BYTES)
    except OSError:
        return None
    return normalize_newlines(raw.decode("utf-8", errors="replace"))


# ---- always-loaded context -----------------------------------------------------------------


def _always_on(rel: str, kind: str, text: str) -> tuple[int, str] | None:
    """(chars, reason) when this file costs context in every session, else None."""
    fm, body = parse_frontmatter(text)
    name = rel.rsplit("/", 1)[-1]
    if (
        kind == "instruction"
        or name in ("CLAUDE.md", "AGENTS.md", "GEMINI.md")
        or rel
        in (
            ".github/copilot-instructions.md",
            ".cursorrules",
            ".windsurfrules",
            ".clinerules",
            ".junie/guidelines.md",
        )
    ):
        return len(text.strip()), "instruction file, loaded in full"
    if rel.endswith("/SKILL.md"):
        if fm.get("disable-model-invocation") is True:
            return 0, "user-invoked skill: only its name is known"
        return (
            len(str(fm.get("name") or "")) + len(str(fm.get("description") or "")),
            "skill name + description",
        )
    if kind == "agent":
        return (
            len(str(fm.get("name") or "")) + len(str(fm.get("description") or "")),
            "subagent name + description",
        )
    if rel.startswith(".claude/rules/") and rel.endswith(".md"):
        if fm.get("paths"):
            return 0, "rule scoped by `paths:` (loaded only for matching files)"
        return len(body.strip()), "unscoped rule, loaded in full"
    if rel.startswith(".cursor/rules/"):
        if fm.get("alwaysApply") is True:
            return len(body.strip()), "Cursor rule with alwaysApply"
        return 0, "Cursor rule applied by globs or on request"
    if rel.startswith(".github/instructions/"):
        if fm.get("applyTo"):
            return 0, "Copilot instruction scoped by `applyTo`"
        return len(body.strip()), "Copilot instruction without `applyTo`"
    return None


# ---- duplicates ----------------------------------------------------------------------------

_WS = re.compile(r"\s+")


def _paragraphs(text: str) -> list[str]:
    _fm, body = parse_frontmatter(text)
    out = []
    for para in re.split(r"\n\s*\n", body):
        norm = _WS.sub(" ", para).strip().lower()
        if len(norm) >= MIN_PARAGRAPH_CHARS and not norm.startswith("<!-- agent-forge"):
            out.append(norm)
    return out


def _shingles(text: str) -> set[str]:
    words = _WS.sub(" ", text).strip().lower().split(" ")
    return {
        " ".join(words[i : i + SHINGLE_WORDS])
        for i in range(0, max(0, len(words) - SHINGLE_WORDS + 1))
    }


# ---- secrets, hooks, MCP -------------------------------------------------------------------


def _secret_lines(text: str) -> list[tuple[int, str]]:
    pattern = RULES["embedded-secret"][0]
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if pattern.search(line):
            out.append((n, line.strip()[:80]))
    return out


def _secret_values(data: Any, path: str = "") -> list[str]:
    """JSON keys that look like credentials and hold a literal (non-placeholder) value."""
    out: list[str] = []
    if isinstance(data, dict):
        for k, v in data.items():
            here = f"{path}.{k}" if path else str(k)
            if isinstance(v, str) and _SECRET_KEY_RE.match(str(k)) and len(v) >= 12:
                if not _PLACEHOLDER_RE.match(v):
                    out.append(here)
            else:
                out.extend(_secret_values(v, here))
    elif isinstance(data, list):
        for i, v in enumerate(data):
            out.extend(_secret_values(v, f"{path}[{i}]"))
    return out


def _hook_commands(data: Any) -> list[tuple[str, str]]:
    """(event, command) for every command handler in a Claude Code settings document."""
    out: list[tuple[str, str]] = []
    hooks = data.get("hooks") if isinstance(data, dict) else None
    if not isinstance(hooks, dict):
        return out
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            continue
        for g in groups:
            for h in g.get("hooks", []) if isinstance(g, dict) else []:
                if isinstance(h, dict) and isinstance(h.get("command"), str):
                    out.append((str(event), h["command"]))
    return out


# ---- entry point ---------------------------------------------------------------------------


def lint_project(
    target: Path, *, max_context: int | None = None, limits: dict[str, int] | None = None
) -> LintReport:
    profile = scan_project(target, limits=limits)
    root = Path(profile.canonical_path)
    rep = LintReport(
        target=profile.canonical_path,
        platforms=[p.platform.value for p in profile.platforms],
        budget=max_context,
    )
    texts: dict[str, str] = {}
    kinds: dict[str, str] = {}
    for a in profile.assets:
        if a.path in texts or a.kind in ("hook",):  # hooks are rows of their settings file
            continue
        text = _read(root, a.path)
        if text is None:
            continue
        texts[a.path] = text
        kinds[a.path] = a.kind
    rep.counts = {
        "assets": len(texts),
        "managed": len(profile.managed),
        "hand_written": sum(1 for a in profile.assets if a.managed_by is None and a.path in texts),
    }

    # 1. always-loaded context
    for rel, text in sorted(texts.items()):
        res = _always_on(rel, kinds[rel], text)
        if res is None:
            continue
        chars, reason = res
        rep.files.append(ContextFile(rel, kinds[rel], chars, reason))
        rep.always_on_total += chars
    rep.files.sort(key=lambda f: (-f.chars, f.path))
    if max_context is not None and rep.always_on_total > max_context:
        rep.findings.append(
            LintFinding(
                "error",
                "budget",
                "-",
                f"always-loaded context {rep.always_on_total} chars exceeds --max-context {max_context}",
            )
        )

    # 2. duplicates among prose files (instructions and rules)
    prose = {
        rel: text
        for rel, text in texts.items()
        if kinds[rel] in ("instruction", "rule")
        or rel.rsplit("/", 1)[-1] in ("CLAUDE.md", "AGENTS.md")
    }
    para_owner: dict[str, str] = {}
    reported: set[tuple[str, str]] = set()
    for rel in sorted(prose):
        for para in _paragraphs(prose[rel]):
            first = para_owner.setdefault(para, rel)
            if first != rel and (first, rel) not in reported:
                reported.add((first, rel))
                rep.findings.append(
                    LintFinding(
                        "warning",
                        "duplicate",
                        rel,
                        f"repeats a paragraph of {first}: {para[:60]!r}…",
                    )
                )
    shingles = {
        rel: _shingles(parse_frontmatter(t)[1])
        for rel, t in prose.items()
        if len(t) >= MIN_FILE_CHARS_FOR_SIMILARITY
    }
    names = sorted(shingles)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            sa, sb = shingles[a], shingles[b]
            if not sa or not sb or (a, b) in reported:
                continue
            j = len(sa & sb) / len(sa | sb)
            if j >= NEAR_DUPLICATE_JACCARD:
                rep.findings.append(
                    LintFinding(
                        "warning",
                        "duplicate",
                        b,
                        f"near-duplicate of {a} (shingle similarity {j:.2f})",
                    )
                )

    # 3. secrets and instruction overrides in any agent file
    for rel, text in sorted(texts.items()):
        for n, excerpt in _secret_lines(text):
            rep.findings.append(
                LintFinding("error", "secret", rel, f"line {n} looks like a credential: {excerpt}")
            )
        if rel.endswith(".json"):
            try:
                data = json.loads(text)
            except ValueError:
                rep.findings.append(LintFinding("error", "syntax", rel, "not valid JSON"))
                continue
            for key in _secret_values(data):
                rep.findings.append(
                    LintFinding("error", "secret", rel, f"{key} holds a literal credential value")
                )
        else:
            pattern = RULES["instruction-override"][0]
            for n, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    rep.findings.append(
                        LintFinding(
                            "warning",
                            "injection",
                            rel,
                            f"line {n} reads like an instruction override: {line.strip()[:80]}",
                        )
                    )

    # 4. hooks that run flagged commands; MCP servers defined but disabled
    hook_count = 0
    disabled: set[str] = set()
    for rel in (".claude/settings.json", ".claude/settings.local.json"):
        text = texts.get(rel)
        if text is None:
            continue
        try:
            data = json.loads(text)
        except ValueError:
            continue
        for name in data.get("disabledMcpjsonServers", []) if isinstance(data, dict) else []:
            disabled.add(str(name))
        for event, command in _hook_commands(data):
            hook_count += 1
            for rule in _HOOK_RULES:
                if RULES[rule][0].search(command):
                    rep.findings.append(
                        LintFinding(
                            "error",
                            "hook",
                            rel,
                            f"{event} hook {RULES[rule][1]} ({rule}): {command[:80]}",
                        )
                    )
    rep.counts["hooks"] = hook_count
    mcp_text = texts.get(".mcp.json")
    servers: list[str] = []
    if mcp_text is not None:
        try:
            doc = json.loads(mcp_text)
            servers = sorted((doc.get("mcpServers") or {}).keys()) if isinstance(doc, dict) else []
        except ValueError:
            servers = []
        for name in servers:
            if name in disabled:
                rep.findings.append(
                    LintFinding(
                        "warning",
                        "mcp",
                        ".mcp.json",
                        f"server {name!r} is defined but disabled in settings.local.json",
                    )
                )
    rep.counts["mcp_servers"] = len(servers)
    rep.findings.sort(key=lambda f: ({"error": 0, "warning": 1, "info": 2}[f.level], f.path))
    return rep
