"""OpenAI Codex adapter.

Conventions verified against https://learn.chatgpt.com/docs (agents-md, build-skills, hooks,
config-reference, subagents) on 2026-10-16, Codex CLI rust-v0.163.0:
  AGENTS.md | AGENTS.override.md          project instructions (root -> cwd chain, 32 KiB cap)
  .agents/skills/<name>/SKILL.md          Agent Skills (name + description required)
  .agents/skills/<name>/agents/openai.yaml optional UI/policy manifest
  .codex/config.toml                      project config  (loaded only for *trusted* projects)
  .codex/hooks.json                       hooks           (trusted projects only; must be trusted via /hooks)
  .codex/agents/<name>.toml               custom subagents (trusted projects only)
Rules (.claude/rules-style path-scoped files) have no Codex equivalent.
"""

from __future__ import annotations

import re

from agent_forge.adapters.base import AdapterInfo, PlatformAdapter
from agent_forge.models.capability import CapabilityKind, Platform
from agent_forge.models.project import AgentAsset, Evidence, PlatformDetection
from agent_forge.scanner.filesystem import Walker
from agent_forge.util import markdown_headings, parse_frontmatter, sha256_text

_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
AGENTS_MD_MAX_BYTES = 32 * 1024


class CodexAdapter(PlatformAdapter):
    info = AdapterInfo(
        platform=Platform.CODEX,
        display_name="OpenAI Codex",
        docs_url="https://learn.chatgpt.com/docs/agent-configuration/agents-md",
        verified_on="2026-10-16",
        instruction_files=("AGENTS.md", "AGENTS.override.md"),
        shared_files=("AGENTS.md", "AGENTS.override.md", ".codex/config.toml", ".codex/hooks.json"),
        managed_roots=("AGENTS.md", ".agents/skills/", ".codex/", ".agent-forge/"),
        supported_kinds=(CapabilityKind.SKILL, CapabilityKind.INSTRUCTION),
        unsupported_notes=(
            "rule: Codex has no path-scoped rules; rules can only be represented as an AGENTS.md "
            "section (requires adaptation, not done automatically)",
            "agent: .codex/agents/*.toml subagents exist but are only loaded for trusted projects; "
            "not installed in this release",
            "hook: .codex/hooks.json exists but hooks execute code and need per-hash trust; not installed",
            "mcp: declared in .codex/config.toml (trusted projects only); not installed",
            "AGENTS.md chain is capped at 32 KiB by default (project_doc_max_bytes); sections must stay small",
        ),
    )

    def detect(self, walker: Walker) -> PlatformDetection | None:
        ev: list[Evidence] = []
        for f in self.info.instruction_files:
            if walker.exists(f):
                ev.append(Evidence(path=f, detail="project instructions"))
        if walker.under(".agents/skills"):
            ev.append(Evidence(path=".agents/skills/", detail="Agent Skills directory"))
        if walker.under(".codex"):
            ev.append(Evidence(path=".codex/", detail="project config directory"))
        if not ev:
            return None
        # AGENTS.md alone is weak evidence: Claude Code and other tools also read it.
        only_agents_md = len(ev) == 1 and ev[0].path in self.info.instruction_files
        confidence = 0.5 if only_agents_md else min(1.0, 0.6 + 0.2 * len(ev))
        return PlatformDetection(platform=self.platform, confidence=confidence, evidence=ev)

    def collect_assets(self, walker: Walker) -> list[AgentAsset]:
        out: list[AgentAsset] = []
        for f in self.info.instruction_files:
            if walker.exists(f):
                out.append(self._md_asset(walker, "instruction", f, name=f))
        for entry in walker.under(".agents/skills"):
            parts = entry.rel.split("/")
            if len(parts) == 4 and parts[3] == "SKILL.md":
                out.append(self._md_asset(walker, "skill", entry.rel, name=parts[2]))
        for entry in walker.under(".codex/agents"):
            if entry.rel.endswith(".toml"):
                text = walker.read_text(entry.rel) or ""
                out.append(
                    AgentAsset(
                        platform=self.platform,
                        kind="agent",
                        name=entry.rel.split("/")[-1][:-5],
                        path=entry.rel,
                        sha256=sha256_text(text),
                    )
                )
        for cfg in (".codex/config.toml", ".codex/hooks.json"):
            if walker.exists(cfg):
                text = walker.read_text(cfg) or ""
                out.append(
                    AgentAsset(
                        platform=self.platform,
                        kind="hook" if cfg.endswith("hooks.json") else "settings",
                        name=cfg,
                        path=cfg,
                        sha256=sha256_text(text),
                    )
                )
        return out

    def _md_asset(self, walker: Walker, kind: str, rel: str, *, name: str) -> AgentAsset:
        text = walker.read_text(rel)
        if text is None:
            return AgentAsset(platform=self.platform, kind=kind, name=name, path=rel)
        fm, body = parse_frontmatter(text)
        safe_fm = {k: v for k, v in fm.items() if k in ("name", "description")}
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

    def validate_content(self, kind: CapabilityKind, rel_path: str, content: str) -> list[str]:
        problems: list[str] = []
        fm, body = parse_frontmatter(content)
        if kind == CapabilityKind.SKILL:
            if not rel_path.startswith(".agents/skills/") or not rel_path.endswith("/SKILL.md"):
                problems.append("Codex skills must be installed at .agents/skills/<name>/SKILL.md")
            for req in ("name", "description"):
                if not isinstance(fm.get(req), str) or not fm[req].strip():
                    problems.append(f"Codex skill frontmatter requires '{req}'")
            name = fm.get("name")
            if isinstance(name, str) and not _SKILL_NAME_RE.match(name):
                problems.append(
                    "Codex skill name should be lowercase letters, digits, '-', '_' or '.'"
                )
            dir_name = rel_path.split("/")[2] if rel_path.count("/") >= 3 else None
            if isinstance(name, str) and dir_name and name != dir_name:
                problems.append(f"skill name {name!r} should match its directory {dir_name!r}")
        elif kind == CapabilityKind.INSTRUCTION:
            if rel_path not in self.info.instruction_files:
                problems.append("instruction sections must target AGENTS.md")
            if len(content.encode("utf-8")) > AGENTS_MD_MAX_BYTES // 4:
                problems.append(
                    "instruction section is large relative to Codex's 32 KiB AGENTS.md cap"
                )
        else:
            problems.append(
                f"capability kind {kind.value!r} is not supported on Codex by Agent Forge"
            )
        if not body.strip():
            problems.append("content body is empty")
        return problems
