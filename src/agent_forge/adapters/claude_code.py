"""Claude Code adapter.

Conventions verified against https://code.claude.com/docs (memory, skills, sub-agents, hooks,
mcp, settings) on 2026-10-16:
  CLAUDE.md | .claude/CLAUDE.md | CLAUDE.local.md      project instructions (concatenated)
  .claude/rules/*.md (optional `paths:` globs)         rules
  .claude/skills/<name>/SKILL.md                       skills (frontmatter optional, name defaults to dir)
  .claude/agents/<name>.md                             subagents (name + description required)
  .claude/commands/*.md                                legacy slash commands (merged into skills)
  .claude/settings.json | .claude/settings.local.json  hooks + permissions (project scope)
  .mcp.json                                            project MCP servers
"""

from __future__ import annotations

import json
import re

from agent_forge.adapters.base import AdapterInfo, PlatformAdapter
from agent_forge.models.capability import CapabilityKind, Platform
from agent_forge.models.project import AgentAsset, Evidence, PlatformDetection
from agent_forge.scanner.filesystem import Walker
from agent_forge.util import markdown_headings, parse_frontmatter, sha256_text

_NAME_BAD = re.compile(r"[<>​-‏‪-‮\x00-\x1f]")


class ClaudeCodeAdapter(PlatformAdapter):
    info = AdapterInfo(
        platform=Platform.CLAUDE_CODE,
        display_name="Claude Code",
        docs_url="https://code.claude.com/docs/en/memory",
        verified_on="2026-10-16",
        instruction_files=("CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md"),
        shared_files=("CLAUDE.md", ".claude/CLAUDE.md", ".claude/settings.json", ".mcp.json"),
        managed_roots=("CLAUDE.md", ".claude/", ".mcp.json", ".agent-forge/"),
        supported_kinds=(
            CapabilityKind.SKILL,
            CapabilityKind.RULE,
            CapabilityKind.AGENT,
            CapabilityKind.INSTRUCTION,
        ),
        unsupported_notes=(
            "hooks: supported by the platform, but Agent Forge does not install hooks in this "
            "release because hook commands execute code; declare them as native_plugin capabilities",
            "mcp: .mcp.json entries launch processes; not installed automatically in this release",
            "user-scoped ~/.claude is never touched",
        ),
    )

    # ---- detection -----------------------------------------------------------------------

    def detect(self, walker: Walker) -> PlatformDetection | None:
        ev: list[Evidence] = []
        for f in self.info.instruction_files:
            if walker.exists(f):
                ev.append(Evidence(path=f, detail="project instructions"))
        if walker.under(".claude"):
            ev.append(Evidence(path=".claude/", detail="project configuration directory"))
        if walker.exists(".mcp.json"):
            ev.append(Evidence(path=".mcp.json", detail="project MCP servers"))
        if not ev:
            return None
        confidence = min(1.0, 0.6 + 0.2 * len(ev))
        return PlatformDetection(platform=self.platform, confidence=confidence, evidence=ev)

    def collect_assets(self, walker: Walker) -> list[AgentAsset]:
        out: list[AgentAsset] = []
        for f in self.info.instruction_files:
            if walker.exists(f):
                out.append(self._md_asset(walker, "instruction", f, name=f))
        for entry in walker.under(".claude/rules"):
            if entry.rel.endswith(".md"):
                out.append(
                    self._md_asset(walker, "rule", entry.rel, name=entry.rel.split("/")[-1][:-3])
                )
        for entry in walker.under(".claude/skills"):
            parts = entry.rel.split("/")
            if len(parts) == 4 and parts[3] == "SKILL.md":
                out.append(self._md_asset(walker, "skill", entry.rel, name=parts[2]))
        for entry in walker.under(".claude/agents"):
            if entry.rel.endswith(".md"):
                out.append(
                    self._md_asset(walker, "agent", entry.rel, name=entry.rel.split("/")[-1][:-3])
                )
        for entry in walker.under(".claude/commands"):
            if entry.rel.endswith(".md"):
                out.append(
                    self._md_asset(walker, "command", entry.rel, name=entry.rel.split("/")[-1][:-3])
                )
        for settings in (".claude/settings.json", ".claude/settings.local.json"):
            if walker.exists(settings):
                out.extend(self._settings_assets(walker, settings))
        if walker.exists(".mcp.json"):
            text = walker.read_text(".mcp.json") or ""
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
                    name=".mcp.json",
                    path=".mcp.json",
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
        safe_fm = {
            k: v for k, v in fm.items() if k in ("name", "description", "paths", "tools", "model")
        }
        return AgentAsset(
            platform=self.platform,
            kind=kind,
            name=str(fm.get("name") or name),
            path=rel,
            sha256=sha256_text(text),
            lines=text.count("\n") + 1,
            frontmatter=safe_fm,
            headings=markdown_headings(body)[:40],
        )

    def _settings_assets(self, walker: Walker, rel: str) -> list[AgentAsset]:
        text = walker.read_text(rel) or ""
        out = [
            AgentAsset(
                platform=self.platform,
                kind="settings",
                name=rel,
                path=rel,
                sha256=sha256_text(text),
            )
        ]
        try:
            data = json.loads(text)
        except ValueError:
            return out
        hooks = data.get("hooks") if isinstance(data, dict) else None
        if isinstance(hooks, dict):
            for event, groups in hooks.items():
                count = (
                    sum(len(g.get("hooks", [])) for g in groups if isinstance(g, dict))
                    if isinstance(groups, list)
                    else 0
                )
                out.append(
                    AgentAsset(
                        platform=self.platform,
                        kind="hook",
                        name=str(event),
                        path=rel,
                        frontmatter={"handlers": count},
                    )
                )
        return out

    # ---- validation ----------------------------------------------------------------------

    def validate_content(self, kind: CapabilityKind, rel_path: str, content: str) -> list[str]:
        problems: list[str] = []
        fm, body = parse_frontmatter(content)
        if kind == CapabilityKind.SKILL:
            if not rel_path.startswith(".claude/skills/") or not rel_path.endswith("/SKILL.md"):
                problems.append("skills must be installed at .claude/skills/<name>/SKILL.md")
            name = fm.get("name")
            if name is not None and (not isinstance(name, str) or _NAME_BAD.search(name)):
                problems.append("skill frontmatter 'name' contains forbidden characters")
            if "description" not in fm:
                problems.append("skill frontmatter should include 'description'")
            # The docs recommend keeping SKILL.md under ~500 lines; that is guidance, not a
            # format rule, so it is reported by `validate` as info rather than rejected here.
        elif kind == CapabilityKind.AGENT:
            if not rel_path.startswith(".claude/agents/") or not rel_path.endswith(".md"):
                problems.append("agents must be installed at .claude/agents/<name>.md")
            for req in ("name", "description"):
                if not isinstance(fm.get(req), str) or not fm[req].strip():
                    problems.append(f"agent frontmatter requires '{req}'")
            name = fm.get("name")
            if isinstance(name, str) and (":" in name or name.startswith("-") or len(name) > 256):
                problems.append("agent name may not contain ':' or start with '-' (max 256 chars)")
        elif kind == CapabilityKind.RULE:
            if not rel_path.startswith(".claude/rules/") or not rel_path.endswith(".md"):
                problems.append("rules must be installed under .claude/rules/")
            paths = fm.get("paths")
            if paths is not None and (
                not isinstance(paths, list) or not all(isinstance(p, str) for p in paths)
            ):
                problems.append("rule frontmatter 'paths' must be a list of glob strings")
        elif kind == CapabilityKind.INSTRUCTION and rel_path not in self.info.instruction_files:
            problems.append("instruction sections must target CLAUDE.md or .claude/CLAUDE.md")
        if not body.strip():
            problems.append("content body is empty")
        return problems
