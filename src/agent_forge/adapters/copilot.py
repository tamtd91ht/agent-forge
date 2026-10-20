"""GitHub Copilot adapter (coding agent, code review, CLI, agent mode in VS Code / JetBrains).

Conventions verified on 2026-10-20 against
https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-repository-instructions
and https://docs.github.com/en/copilot/concepts/agents/about-agent-skills:
  .github/copilot-instructions.md               repository-wide instructions (plain markdown)
  .github/instructions/**/NAME.instructions.md  path-specific instructions; frontmatter
                                                `applyTo` (comma-separated globs), optional
                                                `excludeAgent: code-review | cloud-agent`
  .github/skills/<name>/SKILL.md                agent skills (Agent Skills spec, agentskills.io);
                                                .claude/skills and .agents/skills are read too
  AGENTS.md (nearest wins), CLAUDE.md, GEMINI.md also read; owned by other adapters here.
Custom agents (.github/agents) and MCP (repository settings / IDE config) are not on the
verified pages and are not managed. Hooks do not exist.
"""

from __future__ import annotations

import re

from agent_forge.adapters.base import AdapterInfo, PlatformAdapter
from agent_forge.models.capability import CapabilityKind, Platform
from agent_forge.models.project import AgentAsset, Evidence, PlatformDetection
from agent_forge.scanner.filesystem import Walker
from agent_forge.util import dump_yaml, markdown_headings, parse_frontmatter, sha256_text

INSTRUCTIONS_FILE = ".github/copilot-instructions.md"
INSTRUCTIONS_DIR = ".github/instructions/"
SKILLS_DIR = ".github/skills/"
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")  # agentskills.io: 1-64, no '--'


class CopilotAdapter(PlatformAdapter):
    info = AdapterInfo(
        platform=Platform.COPILOT,
        display_name="GitHub Copilot",
        docs_url="https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-repository-instructions",
        verified_on="2026-10-20",
        instruction_files=(INSTRUCTIONS_FILE,),
        shared_files=(INSTRUCTIONS_FILE,),
        managed_roots=(INSTRUCTIONS_FILE, INSTRUCTIONS_DIR, SKILLS_DIR, ".agent-forge/"),
        supported_kinds=(CapabilityKind.SKILL, CapabilityKind.RULE, CapabilityKind.INSTRUCTION),
        unsupported_notes=(
            "agent: custom agents (.github/agents) are not on the verified documentation pages; "
            "not installed",
            "hook: GitHub Copilot has no project hook mechanism",
            "mcp: MCP servers are configured in repository settings or the IDE, not in a "
            "project file Agent Forge can manage",
            "path-specific instructions on GitHub.com are used by the cloud agent and code "
            "review; IDE agent mode reads them through its own settings",
        ),
        version_command=("copilot", "--version"),
    )

    def detect(self, walker: Walker) -> PlatformDetection | None:
        ev: list[Evidence] = []
        if walker.exists(INSTRUCTIONS_FILE):
            ev.append(Evidence(path=INSTRUCTIONS_FILE, detail="repository instructions"))
        if walker.under(".github/instructions"):
            ev.append(Evidence(path=INSTRUCTIONS_DIR, detail="path-specific instructions"))
        if walker.under(".github/skills"):
            ev.append(Evidence(path=SKILLS_DIR, detail="agent skills"))
        if not ev:
            return None
        return PlatformDetection(
            platform=self.platform, confidence=min(1.0, 0.6 + 0.2 * len(ev)), evidence=ev
        )

    def collect_assets(self, walker: Walker) -> list[AgentAsset]:
        out: list[AgentAsset] = []
        if walker.exists(INSTRUCTIONS_FILE):
            out.append(
                self._md_asset(walker, "instruction", INSTRUCTIONS_FILE, name=INSTRUCTIONS_FILE)
            )
        for entry in walker.under(".github/instructions"):
            if entry.rel.endswith(".instructions.md"):
                name = entry.rel.split("/")[-1][: -len(".instructions.md")]
                out.append(self._md_asset(walker, "rule", entry.rel, name=name))
        for entry in walker.under(".github/skills"):
            parts = entry.rel.split("/")
            if len(parts) == 4 and parts[3] == "SKILL.md":
                out.append(self._md_asset(walker, "skill", entry.rel, name=parts[2]))
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
            frontmatter={k: v for k, v in fm.items() if k in ("name", "description", "applyTo")},
            headings=markdown_headings(body)[:40],
        )

    # ---- rendering (canonical -> Copilot) --------------------------------------------------

    def render(self, kind: CapabilityKind, rel_path: str, content: str) -> str:
        """Canonical rule (`paths:` list) -> `.instructions.md` with `applyTo`; a rule without
        paths applies everywhere (`**`). Skills and instruction sections are used verbatim."""
        if kind != CapabilityKind.RULE:
            return content
        fm, body = parse_frontmatter(content)
        paths = fm.get("paths") or fm.get("applyTo")
        if isinstance(paths, str):
            paths = [p.strip() for p in paths.split(",") if p.strip()]
        apply_to = ", ".join(str(p) for p in paths) if isinstance(paths, list) and paths else "**"
        out: dict[str, object] = {"applyTo": apply_to}
        if isinstance(fm.get("description"), str) and fm["description"].strip():
            out["description"] = fm["description"]
        return f"---\n{dump_yaml(out)}---\n\n{body.lstrip()}"

    # ---- validation ----------------------------------------------------------------------

    def validate_content(self, kind: CapabilityKind, rel_path: str, content: str) -> list[str]:
        problems: list[str] = []
        fm, body = parse_frontmatter(content)
        if kind == CapabilityKind.SKILL:
            parts = rel_path.split("/")
            if not rel_path.startswith(SKILLS_DIR) or len(parts) != 4 or parts[3] != "SKILL.md":
                problems.append("skills must be installed at .github/skills/<name>/SKILL.md")
            else:
                name = fm.get("name")
                if not isinstance(name, str) or not SKILL_NAME_RE.match(name) or len(name) > 64:
                    problems.append(
                        "skill frontmatter 'name' must be 1-64 lowercase letters, digits and single hyphens"
                    )
                elif name != parts[2]:
                    problems.append(f"skill name {name!r} must match its directory {parts[2]!r}")
                desc = fm.get("description")
                if not isinstance(desc, str) or not desc.strip() or len(desc) > 1024:
                    problems.append(
                        "skill frontmatter 'description' is required (1-1024 characters)"
                    )
        elif kind == CapabilityKind.RULE:
            if not rel_path.startswith(INSTRUCTIONS_DIR) or not rel_path.endswith(
                ".instructions.md"
            ):
                problems.append(
                    "rules must be installed as .github/instructions/<name>.instructions.md"
                )
            if not isinstance(fm.get("applyTo"), str) or not fm["applyTo"].strip():
                problems.append("rule frontmatter 'applyTo' (comma-separated globs) is required")
            if "excludeAgent" in fm and fm["excludeAgent"] not in ("code-review", "cloud-agent"):
                problems.append(
                    "rule frontmatter 'excludeAgent' must be code-review or cloud-agent"
                )
        elif kind == CapabilityKind.INSTRUCTION:
            if rel_path != INSTRUCTIONS_FILE:
                problems.append(f"instruction sections must target {INSTRUCTIONS_FILE}")
        else:
            return [f"GitHub Copilot adapter does not support kind '{kind.value}'"]
        if not body.strip():
            problems.append("content body is empty")
        return problems
