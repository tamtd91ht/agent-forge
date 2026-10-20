"""Cursor adapter.

Conventions verified against https://cursor.com/docs/context/rules and
https://cursor.com/docs/context/mcp on 2026-10-20:
  .cursor/rules/**/*.mdc     project rules; YAML frontmatter `description` (string),
                             `globs` (comma-separated string), `alwaysApply` (bool).
                             alwaysApply: true -> every session; globs -> auto attached;
                             description only -> agent decides; neither -> manual (@rule).
                             A plain .md in that directory is ignored. Keep under ~500 lines.
  AGENTS.md                  also read (root and nested); owned by the Codex adapter here, so
                             Agent Forge writes Cursor instructions as alwaysApply rules.
  .cursor/mcp.json           project MCP servers: `mcpServers` -> stdio (type + command) or
                             remote (url, optional headers)
  .cursorrules               legacy single-file rules (detected, never written)
Skills, subagents and hooks are not documented on the verified pages and are not managed.
"""

from __future__ import annotations

import json

from agent_forge.adapters.base import AdapterInfo, PlatformAdapter
from agent_forge.models.capability import CapabilityKind, Platform
from agent_forge.models.project import AgentAsset, Evidence, PlatformDetection
from agent_forge.scanner.filesystem import Walker
from agent_forge.util import dump_yaml, markdown_headings, parse_frontmatter, sha256_text

RULES_DIR = ".cursor/rules/"
MCP_FILE = ".cursor/mcp.json"


class CursorAdapter(PlatformAdapter):
    info = AdapterInfo(
        platform=Platform.CURSOR,
        display_name="Cursor",
        docs_url="https://cursor.com/docs/context/rules",
        verified_on="2026-10-20",
        instruction_files=(),
        shared_files=(MCP_FILE,),
        managed_roots=(".cursor/", ".agent-forge/"),
        supported_kinds=(CapabilityKind.RULE, CapabilityKind.INSTRUCTION, CapabilityKind.MCP),
        unsupported_notes=(
            "skill: Cursor has no documented project skill format; skills are offered as "
            "agent-requested rules only when a capability declares such a destination",
            "agent: Cursor subagents are not documented as project files; not installed",
            "hook: .cursor/hooks.json is not on the verified documentation pages; not installed",
            "instruction: written as an alwaysApply rule under .cursor/rules/ (AGENTS.md is "
            "shared with Codex and left to that adapter)",
            "mcp: merged into .cursor/mcp.json; servers launch processes, so plans need `approve --mcp`",
        ),
        version_command=("cursor", "--version"),
    )

    def detect(self, walker: Walker) -> PlatformDetection | None:
        ev: list[Evidence] = []
        if walker.under(".cursor/rules"):
            ev.append(Evidence(path=RULES_DIR, detail="project rules"))
        elif walker.under(".cursor"):
            ev.append(Evidence(path=".cursor/", detail="project configuration directory"))
        if walker.exists(MCP_FILE):
            ev.append(Evidence(path=MCP_FILE, detail="project MCP servers"))
        if walker.exists(".cursorrules"):
            ev.append(Evidence(path=".cursorrules", detail="legacy rules file"))
        if not ev:
            return None
        return PlatformDetection(
            platform=self.platform, confidence=min(1.0, 0.6 + 0.2 * len(ev)), evidence=ev
        )

    def collect_assets(self, walker: Walker) -> list[AgentAsset]:
        out: list[AgentAsset] = []
        for entry in walker.under(".cursor/rules"):
            if entry.rel.endswith(".mdc"):
                text = walker.read_text(entry.rel)
                name = entry.rel.split("/")[-1][: -len(".mdc")]
                if text is None:
                    out.append(
                        AgentAsset(platform=self.platform, kind="rule", name=name, path=entry.rel)
                    )
                    continue
                fm, body = parse_frontmatter(text)
                kind = "instruction" if fm.get("alwaysApply") is True else "rule"
                out.append(
                    AgentAsset(
                        platform=self.platform,
                        kind=kind,
                        name=name,
                        path=entry.rel,
                        sha256=sha256_text(text),
                        lines=text.count("\n") + 1,
                        frontmatter={
                            k: v
                            for k, v in fm.items()
                            if k in ("description", "globs", "alwaysApply")
                        },
                        headings=markdown_headings(body)[:40],
                    )
                )
        if walker.exists(MCP_FILE):
            text = walker.read_text(MCP_FILE) or ""
            names: list[str] = []
            try:
                data = json.loads(text)
                names = (
                    sorted((data.get("mcpServers") or {}).keys()) if isinstance(data, dict) else []
                )
            except ValueError:
                pass
            out.append(
                AgentAsset(
                    platform=self.platform,
                    kind="mcp",
                    name=MCP_FILE,
                    path=MCP_FILE,
                    sha256=sha256_text(text),
                    frontmatter={"servers": names},
                )
            )
        return out

    # ---- rendering (canonical -> Cursor) ---------------------------------------------------

    def render(self, kind: CapabilityKind, rel_path: str, content: str) -> str:
        """Canonical rule/instruction markdown -> .mdc with Cursor frontmatter.

        Canonical frontmatter: `description` (string), `paths` (list of globs, Claude Code
        style). Cursor: `globs` is one comma-separated string; `alwaysApply` true for
        instructions. Deterministic: the same input always renders the same bytes.
        """
        if kind not in (CapabilityKind.RULE, CapabilityKind.INSTRUCTION):
            return content
        fm, body = parse_frontmatter(content)
        paths = fm.get("paths") or fm.get("globs")
        if isinstance(paths, str):
            paths = [p.strip() for p in paths.split(",") if p.strip()]
        out: dict[str, object] = {}
        desc = fm.get("description")
        if not isinstance(desc, str) or not desc.strip():
            desc = _first_heading_or_line(body)
        out["description"] = desc
        if kind == CapabilityKind.INSTRUCTION:
            out["alwaysApply"] = True
        else:
            if isinstance(paths, list) and paths:
                out["globs"] = ", ".join(str(p) for p in paths)
            out["alwaysApply"] = bool(fm.get("alwaysApply", False))
        return f"---\n{dump_yaml(out)}---\n\n{body.lstrip()}"

    # ---- validation ----------------------------------------------------------------------

    def validate_content(self, kind: CapabilityKind, rel_path: str, content: str) -> list[str]:
        problems: list[str] = []
        if kind == CapabilityKind.MCP:
            return _validate_mcp_fragment(rel_path, content)
        if kind not in (CapabilityKind.RULE, CapabilityKind.INSTRUCTION):
            return [f"Cursor adapter does not support kind '{kind.value}'"]
        if not rel_path.startswith(RULES_DIR) or not rel_path.endswith(".mdc"):
            problems.append("Cursor rules must be installed as .cursor/rules/**/*.mdc")
        if not content.startswith("---\n"):
            problems.append("Cursor rules need YAML frontmatter (a plain .md body is ignored)")
        fm, body = parse_frontmatter(content)
        if "globs" in fm and not isinstance(fm["globs"], str):
            problems.append("rule frontmatter 'globs' must be one comma-separated string")
        if "alwaysApply" in fm and not isinstance(fm["alwaysApply"], bool):
            problems.append("rule frontmatter 'alwaysApply' must be a boolean")
        if kind == CapabilityKind.INSTRUCTION and fm.get("alwaysApply") is not True:
            problems.append("instruction rules must set alwaysApply: true")
        if "description" in fm and not isinstance(fm["description"], str):
            problems.append("rule frontmatter 'description' must be a string")
        if not body.strip():
            problems.append("content body is empty")
        return problems


def _first_heading_or_line(body: str) -> str:
    for line in body.splitlines():
        s = line.strip().lstrip("#").strip()
        if s:
            return s[:200]
    return "Project rule"


def _validate_mcp_fragment(rel_path: str, content: str) -> list[str]:
    problems: list[str] = []
    if rel_path != MCP_FILE:
        problems.append(f"MCP servers must be merged into {MCP_FILE}")
    try:
        frag = json.loads(content)
    except ValueError as exc:
        return [f"fragment is not valid JSON: {exc}"]
    if not isinstance(frag, dict) or set(frag) != {"mcpServers"}:
        return [*problems, "MCP fragment must contain exactly the 'mcpServers' key"]
    for name, cfg in (frag.get("mcpServers") or {}).items():
        if not isinstance(cfg, dict):
            problems.append(f"mcpServers.{name} must be an object")
            continue
        if "url" in cfg:
            if not isinstance(cfg["url"], str):
                problems.append(f"mcpServers.{name}: url must be a string")
        else:
            if cfg.get("type") != "stdio":
                problems.append(f"mcpServers.{name}: stdio servers need type: stdio")
            if not isinstance(cfg.get("command"), str):
                problems.append(f"mcpServers.{name}: stdio servers need a 'command'")
    return problems
