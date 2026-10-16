# Platform adapters

An adapter (`src/agent_forge/adapters/`) encodes one platform's *verified* project-scoped
conventions. Adapters never write files; they detect, inventory, bound and validate.

| Concern | Claude Code (`claude_code.py`) | OpenAI Codex (`codex.py`) |
|---|---|---|
| Docs verified on | 2026-10-16, code.claude.com/docs | 2026-10-16, learn.chatgpt.com/docs (CLI rust-v0.163.0) |
| Detection evidence | `CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md`, `.claude/`, `.mcp.json` | `AGENTS.md`, `AGENTS.override.md`, `.agents/skills/`, `.codex/` (AGENTS.md alone = 0.5 confidence, since other tools read it too) |
| Inventory | instructions, `.claude/rules/*.md`, `.claude/skills/*/SKILL.md`, `.claude/agents/*.md`, `.claude/commands/*.md`, hooks in `settings*.json`, `.mcp.json` servers | instructions, `.agents/skills/*/SKILL.md`, `.codex/agents/*.toml`, `.codex/config.toml`, `.codex/hooks.json` |
| Managed roots (writes allowed) | `CLAUDE.md`, `.claude/`, `.mcp.json`, `.agent-forge/` | `AGENTS.md`, `.agents/skills/`, `.codex/`, `.agent-forge/` |
| Shared files (extra approval) | `CLAUDE.md`, `.claude/CLAUDE.md`, `.claude/settings.json`, `.mcp.json` | `AGENTS.md`, `AGENTS.override.md`, `.codex/config.toml`, `.codex/hooks.json` |
| Installable kinds | skill, rule, agent, instruction | skill, instruction |
| Content rules | skill: frontmatter `name` without forbidden chars, `description` recommended; agent: `name` + `description`, no `:`/leading `-`, ≤256; rule: `paths` list of globs | skill: `name` + `description` required, lowercase name equal to directory; instruction sections kept small (32 KiB AGENTS.md cap) |
| Not managed in v0.1 | hooks (33 events, execute commands), `.mcp.json` (launches processes), plugins | rules (no equivalent), subagents (`.codex/agents/*.toml`, trusted projects only), hooks (per-hash trust), MCP (`config.toml`, trusted only) |

## Reporting unsupported features

`assign` rejects with `unsupported_platform` and the adapter's reason, e.g.
"OpenAI Codex adapter does not support kind 'rule'". Nothing is silently renamed or
text-substituted; a capability is offered on a platform only if its manifest lists that
platform *and* the adapter supports the kind.

## Adding a platform

1. Verify the official conventions and record the URL + date in the module docstring.
2. Subclass `PlatformAdapter`: `info` (roots, shared files, kinds, unsupported notes),
   `detect`, `collect_assets`, `validate_content`.
3. Register in `adapters/__init__.py` and add the `Platform` enum value.
4. Add fixture coverage in `tests/unit/test_scanner.py` and `tests/integration/`.
