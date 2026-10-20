"""Gemini CLI adapter.

Conventions verified on 2026-10-20 against the Gemini CLI documentation
(github.com/google-gemini/gemini-cli/docs: cli/gemini-md.md, cli/skills.md, tools/mcp-server.md,
cli/settings.md):
  GEMINI.md                      context file: ~/.gemini/GEMINI.md, then the workspace and its
                                 parents, then just-in-time for touched directories; all loaded
                                 files are concatenated. `@file.md` imports. The name can be
                                 changed with settings `context.fileName`.
  .gemini/skills/<name>/SKILL.md workspace skills (Agent Skills open standard); `.agents/skills/`
                                 is an alias that takes precedence (owned by Codex here)
  .gemini/settings.json          workspace settings; `mcpServers` -> command/args/env/cwd
                                 (stdio) or url (SSE) / httpUrl (streamable HTTP), headers,
                                 timeout, trust, includeTools/excludeTools. Stdio servers run
                                 only in a trusted folder (`gemini trust`).
Hooks (settings `hooksConfig`) and subagents exist but were not verified as project files.
"""

from __future__ import annotations

import json
import re

from agent_forge.adapters.base import AdapterInfo, PlatformAdapter
from agent_forge.models.capability import CapabilityKind, Platform
from agent_forge.models.project import AgentAsset, Evidence, PlatformDetection
from agent_forge.scanner.filesystem import Walker
from agent_forge.util import markdown_headings, parse_frontmatter, sha256_text

CONTEXT_FILE = "GEMINI.md"
SKILLS_DIR = ".gemini/skills/"
SETTINGS_FILE = ".gemini/settings.json"
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class GeminiAdapter(PlatformAdapter):
    info = AdapterInfo(
        platform=Platform.GEMINI,
        display_name="Gemini CLI",
        docs_url="https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/gemini-md.md",
        verified_on="2026-10-20",
        instruction_files=(CONTEXT_FILE,),
        shared_files=(CONTEXT_FILE, SETTINGS_FILE),
        managed_roots=(CONTEXT_FILE, ".gemini/", ".agent-forge/"),
        supported_kinds=(CapabilityKind.SKILL, CapabilityKind.INSTRUCTION, CapabilityKind.MCP),
        unsupported_notes=(
            "rule: Gemini CLI has no path-scoped rules; GEMINI.md sections or @imports only",
            "agent: subagents are not documented as project files; not installed",
            "hook: hooks are configured in settings.json and were not verified as project "
            "files; not installed",
            "mcp: merged into .gemini/settings.json `mcpServers`; servers launch processes, so "
            "plans need `approve --mcp`; stdio servers only connect in a trusted folder",
        ),
        version_command=("gemini", "--version"),
    )

    def detect(self, walker: Walker) -> PlatformDetection | None:
        ev: list[Evidence] = []
        if walker.exists(CONTEXT_FILE):
            ev.append(Evidence(path=CONTEXT_FILE, detail="context file"))
        if walker.under(".gemini/skills"):
            ev.append(Evidence(path=SKILLS_DIR, detail="workspace skills"))
        if walker.exists(SETTINGS_FILE):
            ev.append(Evidence(path=SETTINGS_FILE, detail="workspace settings"))
        elif walker.under(".gemini"):
            ev.append(Evidence(path=".gemini/", detail="workspace configuration directory"))
        if not ev:
            return None
        # GEMINI.md alone is weak evidence: Copilot and other tools read it too.
        only_context = len(ev) == 1 and ev[0].path == CONTEXT_FILE
        confidence = 0.5 if only_context else min(1.0, 0.6 + 0.2 * len(ev))
        return PlatformDetection(platform=self.platform, confidence=confidence, evidence=ev)

    def collect_assets(self, walker: Walker) -> list[AgentAsset]:
        out: list[AgentAsset] = []
        if walker.exists(CONTEXT_FILE):
            out.append(self._md_asset(walker, "instruction", CONTEXT_FILE, name=CONTEXT_FILE))
        for entry in walker.under(".gemini/skills"):
            parts = entry.rel.split("/")
            if len(parts) == 4 and parts[3] == "SKILL.md":
                out.append(self._md_asset(walker, "skill", entry.rel, name=parts[2]))
        if walker.exists(SETTINGS_FILE):
            text = walker.read_text(SETTINGS_FILE) or ""
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
                    kind="settings",
                    name=SETTINGS_FILE,
                    path=SETTINGS_FILE,
                    sha256=sha256_text(text),
                    frontmatter={"servers": names},
                )
            )
        return out

    def _md_asset(self, walker: Walker, kind: str, rel: str, *, name: str) -> AgentAsset:
        text = walker.read_text(rel)
        if text is None:
            return AgentAsset(platform=self.platform, kind=kind, name=name, path=rel)
        fm, body = parse_frontmatter(text)
        return AgentAsset(
            platform=self.platform,
            kind=kind,
            name=str(fm.get("name") or name),
            path=rel,
            sha256=sha256_text(text),
            lines=text.count("\n") + 1,
            frontmatter={k: v for k, v in fm.items() if k in ("name", "description")},
            headings=markdown_headings(body)[:40],
        )

    # ---- rendering (canonical -> Gemini) ---------------------------------------------------

    def render(self, kind: CapabilityKind, rel_path: str, content: str) -> str:
        """Canonical MCP fragment (Claude Code shape: type + command / type + url) -> Gemini
        settings shape: stdio keeps command/args/env, SSE uses `url`, HTTP uses `httpUrl`;
        `type` is dropped. Deterministic JSON (sorted keys)."""
        if kind != CapabilityKind.MCP:
            return content
        try:
            frag = json.loads(content)
        except ValueError:
            return content
        servers = frag.get("mcpServers") if isinstance(frag, dict) else None
        if not isinstance(servers, dict):
            return content
        out: dict[str, dict] = {}
        for name, cfg in servers.items():
            if not isinstance(cfg, dict):
                out[name] = cfg
                continue
            cfg = dict(cfg)
            t = cfg.pop("type", "stdio")
            url = cfg.pop("url", None)
            if url is not None:
                cfg["url" if t == "sse" else "httpUrl"] = url
            out[name] = cfg
        return json.dumps({"mcpServers": out}, indent=2, sort_keys=True) + "\n"

    # ---- validation ----------------------------------------------------------------------

    def validate_content(self, kind: CapabilityKind, rel_path: str, content: str) -> list[str]:
        problems: list[str] = []
        if kind == CapabilityKind.MCP:
            return self._validate_mcp(rel_path, content)
        fm, body = parse_frontmatter(content)
        if kind == CapabilityKind.SKILL:
            parts = rel_path.split("/")
            if not rel_path.startswith(SKILLS_DIR) or len(parts) != 4 or parts[3] != "SKILL.md":
                problems.append("skills must be installed at .gemini/skills/<name>/SKILL.md")
            else:
                name = fm.get("name")
                if not isinstance(name, str) or not SKILL_NAME_RE.match(name) or len(name) > 64:
                    problems.append(
                        "skill frontmatter 'name' must be 1-64 lowercase letters, digits and single hyphens"
                    )
                elif name != parts[2]:
                    problems.append(f"skill name {name!r} must match its directory {parts[2]!r}")
                desc = fm.get("description")
                if not isinstance(desc, str) or not desc.strip():
                    problems.append("skill frontmatter 'description' is required")
        elif kind == CapabilityKind.INSTRUCTION:
            if rel_path != CONTEXT_FILE:
                problems.append(f"instruction sections must target {CONTEXT_FILE}")
        else:
            return [f"Gemini CLI adapter does not support kind '{kind.value}'"]
        if not body.strip():
            problems.append("content body is empty")
        return problems

    def _validate_mcp(self, rel_path: str, content: str) -> list[str]:
        problems: list[str] = []
        if rel_path != SETTINGS_FILE:
            problems.append(f"MCP servers must be merged into {SETTINGS_FILE}")
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
            if "_" in name:
                problems.append(
                    f"mcpServers.{name}: avoid underscores in server names (policy parser)"
                )
            transports = [k for k in ("command", "url", "httpUrl") if k in cfg]
            if len(transports) != 1:
                problems.append(
                    f"mcpServers.{name}: exactly one of command, url or httpUrl is required"
                )
            if "type" in cfg:
                problems.append(f"mcpServers.{name}: Gemini CLI servers do not take a 'type' key")
            if "timeout" in cfg and not isinstance(cfg["timeout"], int):
                problems.append(f"mcpServers.{name}: timeout must be an integer (milliseconds)")
        return problems
