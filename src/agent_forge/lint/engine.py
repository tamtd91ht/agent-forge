"""Lint the agent configuration a project already has (ADR-0007, the frictionless entry).

Read-only, no workspace, no catalog, no LLM, under a few seconds. It answers eight questions
about `CLAUDE.md` / `AGENTS.md` / `GEMINI.md`, rules, skills, agents, hooks and MCP servers:

1. How much always-loaded context does every session pay, and for which files?
2. Which rules repeat each other (duplicate paragraphs, near-duplicate files)?
3. Is a credential sitting in an agent file or MCP config?
4. Does a hook run something the content-safety rules flag?
5. Does an instruction name a skill, agent, command, rule or `@import` that does not exist?
   (`deadref`; config drifts as files are renamed and retired)
6. Does an instruction state a count ("23 agents") that disagrees with the disk? (`index_drift`)
7. Do two skills or two agents describe themselves so alike that the model cannot tell which
   one to call? (`overlap`)
8. Is a skill or agent missing the `name` / `description` frontmatter the tool needs to
   discover it? (`schema`)

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
    # context | duplicate | secret | hook | mcp | injection | budget | syntax
    # | deadref | index_drift | overlap | schema
    check: str
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


# ---- references, counts, overlapping descriptions, frontmatter -----------------------------

# `skills/<name>`, `agents/<name>`, `commands/<name>`, `rules/<path>.md`, optionally prefixed
# by `.claude/`, in prose or backticks; and `@path` imports at a line or token boundary.
_ASSET_REF_RE = re.compile(
    r"(?<![\w/.-])(?:\.claude/)?(skills|agents|commands|rules)/([A-Za-z0-9][\w.-]*(?:/[\w.-]+)*)"
)
_IMPORT_RE = re.compile(r"(?:^|(?<=\s))@((?:\.{0,2}/)?[\w.-]+(?:/[\w.-]+)*\.[A-Za-z0-9]+)", re.M)
_COUNT_RE = re.compile(
    r"\b(\d{1,3})\s+(skills?|sub-?agents?|agents?|rules?|commands?|hooks?)\b", re.I
)
_WORD_RE = re.compile(r"[a-z0-9]{4,}")
_STOPWORDS = frozenset(
    [
        "this",
        "that",
        "with",
        "when",
        "then",
        "than",
        "from",
        "into",
        "your",
        "what",
        "which",
        "while",
        "about",
        "after",
        "before",
        "where",
        "have",
        "been",
        "will",
        "would",
        "should",
        "could",
        "also",
        "only",
        "such",
        "them",
        "they",
        "their",
        "there",
        "these",
        "those",
        "uses",
        "used",
        "using",
        "make",
        "makes",
        "made",
        "need",
        "needs",
        "every",
        "each",
        "some",
        "more",
        "most",
        "very",
    ]
)
OVERLAP_JACCARD = 0.6
MIN_DESCRIPTION_WORDS = 5
# Asset kinds whose text is prose the model follows (hooks are rows of settings files).
_PROSE_KINDS = ("instruction", "rule", "skill", "agent", "command")
_KIND_WORDS = frozenset({"skills", "agents", "rules", "commands", "docs", "hooks", "workflows"})


def _asset_name_from_rel(rel: str) -> str:
    """`.claude/skills/x/SKILL.md` → `x`; `.claude/agents/x.md` → `x`."""
    parts = rel.split("/")
    if parts[-1] == "SKILL.md" and len(parts) >= 2:
        return parts[-2]
    return parts[-1].rsplit(".", 1)[0]


def _resolve_asset_ref(
    root: Path, kind: str, name: str, assets_by_kind: dict[str, set[str]]
) -> bool:
    """Does `<kind>/<name>` exist as an agent asset or as a path under .claude/?"""
    kind_singular = kind[:-1]
    first = name.split("/")[0]
    if kind_singular in ("skill", "agent", "command") and first in assets_by_kind.get(
        kind_singular, set()
    ):
        return True
    base = name[:-3] if name.endswith(".md") else name
    for rel in (
        f".claude/{kind}/{name}",
        f".claude/{kind}/{base}.md",
        f".claude/{kind}/{base}/SKILL.md",
        f".claude/{kind}/{base}",
    ):
        try:
            if resolve_in_root(root, rel).exists():
                return True
        except SafetyViolation:
            continue
    return False


def _exists_relative(root: Path, from_rel: str, target: str) -> bool:
    bases = [""]
    if "/" in from_rel:
        bases.append(from_rel.rsplit("/", 1)[0] + "/")
    for base in bases:
        candidate = (base + target).replace("//", "/")
        if candidate.startswith("./"):
            candidate = candidate[2:]
        try:
            if resolve_in_root(root, candidate).exists():
                return True
        except SafetyViolation:
            continue
    return False


_SCRIPT_TOKEN_RE = re.compile(
    r"""["']?(\$CLAUDE_PROJECT_DIR/|\./)?([\w./-]+\.(?:py|sh|js|mjs|ps1))["']?"""
)
_STDOUT_WRITES = {
    ".py": (
        re.compile(r"\bprint\s*\((?![^)]*file\s*=\s*sys\.stderr)"),
        re.compile(r"sys\.stderr|hookSpecificOutput"),
    ),
    ".sh": (re.compile(r"^\s*echo\b(?![^\n]*>&2)", re.M), re.compile(r">&2|hookSpecificOutput")),
    ".js": (
        re.compile(r"console\.log\s*\("),
        re.compile(r"console\.error|process\.stderr|hookSpecificOutput"),
    ),
    ".mjs": (
        re.compile(r"console\.log\s*\("),
        re.compile(r"console\.error|process\.stderr|hookSpecificOutput"),
    ),
    ".ps1": (
        re.compile(r"Write-(Output|Host)\b"),
        re.compile(r"Write-Error|\[Console\]::Error|hookSpecificOutput"),
    ),
}


def _hook_script_path(command: str) -> str | None:
    """The project-relative script a hook command runs, when one is named in it."""
    for m in _SCRIPT_TOKEN_RE.finditer(command):
        rel = m.group(2)
        if rel.startswith(".claude/") or rel.startswith("scripts/") or m.group(1):
            return rel
    return None


def _stdout_only(script: str, text: str) -> str | None:
    """A reason when the script writes to stdout and never to stderr or a hook JSON document."""
    suffix = "." + script.rsplit(".", 1)[-1].lower()
    pair = _STDOUT_WRITES.get(suffix)
    if pair is None:
        return None
    writes_stdout, reaches_model = pair
    if writes_stdout.search(text) and not reaches_model.search(text):
        return "writes to stdout and never to stderr"
    return None


def _description_words(text: str) -> set[str]:
    fm, _ = parse_frontmatter(text)
    desc = str(fm.get("description") or "")
    return {w for w in _WORD_RE.findall(desc.lower()) if w not in _STOPWORDS}


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
    hook_entries: list[tuple[str, str, str]] = []
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
            hook_entries.append((rel, event, command))
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

    # 5. references to skills / agents / commands / rules / @imports that do not exist
    assets_by_kind: dict[str, set[str]] = {}
    for a in profile.assets:
        assets_by_kind.setdefault(a.kind, set()).add(_asset_name_from_rel(a.path))
    prose_rels = sorted(rel for rel in texts if kinds[rel] in _PROSE_KINDS)
    for rel in prose_rels:
        text = texts[rel]
        missing: dict[str, int] = {}
        for m in _ASSET_REF_RE.finditer(text):
            kind, name = m.group(1), m.group(2)
            name = name.rstrip(".,;:)")
            if (
                any(ch in name for ch in "*{}<>$")
                or name.startswith("_")
                or text[m.end() : m.end() + 1] in ("*", "{", ".")
                or name.split("/")[0] in _KIND_WORDS
            ):
                continue  # a glob, a placeholder or prose like "rules/skills", not a reference
            if not _resolve_asset_ref(root, kind, name, assets_by_kind):
                missing.setdefault(f"{kind}/{name}", text.count("\n", 0, m.start()) + 1)
        for m in _IMPORT_RE.finditer(text):
            target = m.group(1)
            if not _exists_relative(root, rel, target):
                missing.setdefault(f"@{target}", text.count("\n", 0, m.start()) + 1)
        for ref, line in sorted(missing.items(), key=lambda kv: kv[1]):
            rep.findings.append(
                LintFinding(
                    "warning", "deadref", rel, f"line {line} refers to {ref}, which does not exist"
                )
            )

    # 6. counts stated in instructions that claim more than the disk holds. A smaller number
    # may describe a subset ("13 VOIP skills"), so only an overclaim is reported; `_INDEX`-style
    # files are not counted as assets of their kind.
    on_disk = {
        kind: len({n for n in assets_by_kind.get(kind, set()) if not n.startswith("_")})
        for kind in ("skill", "agent", "rule", "command")
    }
    on_disk["hook"] = hook_count
    for rel in prose_rels:
        name = rel.rsplit("/", 1)[-1]
        if not (kinds[rel] == "instruction" or name.startswith("_") or name == "README.md"):
            continue
        for m in _COUNT_RE.finditer(texts[rel]):
            stated = int(m.group(1))
            word = m.group(2).lower().replace("-", "")
            kind = "agent" if word.startswith("subagent") else word.rstrip("s")
            actual = on_disk[kind]
            if stated >= 2 and stated > actual:
                line = texts[rel].count("\n", 0, m.start()) + 1
                rep.findings.append(
                    LintFinding(
                        "warning",
                        "index_drift",
                        rel,
                        f"line {line} says {stated} {kind}s, only {actual} found on disk",
                    )
                )

    # 7. skills / agents whose descriptions overlap (the model may call the wrong one)
    for kind in ("skill", "agent"):
        words = {
            rel: _description_words(texts[rel])
            for rel in prose_rels
            if kinds[rel] == kind and len(_description_words(texts[rel])) >= MIN_DESCRIPTION_WORDS
        }
        # reported on the one whose name sorts later, so `deploy-prod` is flagged against `deploy`
        names = sorted(words, key=lambda rel: (_asset_name_from_rel(rel), rel))
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                j = len(words[a] & words[b]) / len(words[a] | words[b])
                if j >= OVERLAP_JACCARD:
                    rep.findings.append(
                        LintFinding(
                            "warning",
                            "overlap",
                            b,
                            f"description overlaps with {a} (similarity {j:.2f}); "
                            "the model may call the wrong one",
                        )
                    )

    # 8. skills and agents the tool cannot discover (missing name / description)
    for rel in prose_rels:
        if kinds[rel] not in ("skill", "agent") or _asset_name_from_rel(rel).startswith("_"):
            continue  # `_ROUTING.md`-style tables under agents/ are not subagents
        fm, _ = parse_frontmatter(texts[rel])
        absent = [k for k in ("name", "description") if not str(fm.get(k) or "").strip()]
        if absent:
            rep.findings.append(
                LintFinding(
                    "warning",
                    "schema",
                    rel,
                    f"{kinds[rel]} frontmatter lacks {' and '.join(absent)}; "
                    "the tool cannot discover or describe it",
                )
            )

    # 9. hook scripts whose only output goes to stdout: the model never sees it
    for _rel, event, command in hook_entries:
        if event not in ("PreToolUse", "PostToolUse", "Stop", "SubagentStop"):
            continue
        script = _hook_script_path(command)
        if script is None:
            continue
        text = _read(root, script)
        if text is None:
            continue
        verdict = _stdout_only(script, text)
        if verdict:
            rep.findings.append(
                LintFinding(
                    "warning",
                    "hook_output",
                    script,
                    f"{event} hook {verdict}; only stderr with exit 2 (or a hookSpecificOutput "
                    "JSON document) reaches the model",
                )
            )

    rep.findings.sort(key=lambda f: ({"error": 0, "warning": 1, "info": 2}[f.level], f.path))
    return rep
