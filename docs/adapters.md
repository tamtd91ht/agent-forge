# Platform adapters

An adapter (`src/agent_forge/adapters/`) encodes one platform's *verified* project-scoped
conventions. Adapters never write files; they detect, inventory, bound, **render** and
validate. Content is authored once in the canonical (Claude Code) formats and rendered into
each platform's format by the planner ([ADR-0006](adr/0006-canonical-format-and-adapters.md)).

| Concern | Claude Code | OpenAI Codex | Cursor | GitHub Copilot | Gemini CLI |
|---|---|---|---|---|---|
| Module | `claude_code.py` | `codex.py` | `cursor.py` | `copilot.py` | `gemini.py` |
| Docs verified on | 2026-10-16, code.claude.com/docs | 2026-10-16, learn.chatgpt.com/docs (CLI rust-v0.163.0) | 2026-10-20, cursor.com/docs/context/{rules,mcp} | 2026-10-20, docs.github.com (repository instructions, agent skills) | 2026-10-20, gemini-cli docs (gemini-md, skills, mcp-server, settings) |
| Detection evidence | `CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md`, `.claude/`, `.mcp.json` | `AGENTS.md`, `AGENTS.override.md`, `.agents/skills/`, `.codex/` (AGENTS.md alone = 0.5) | `.cursor/rules/`, `.cursor/`, `.cursor/mcp.json`, `.cursorrules` (legacy) | `.github/copilot-instructions.md`, `.github/instructions/`, `.github/skills/` | `GEMINI.md` (alone = 0.5), `.gemini/skills/`, `.gemini/settings.json` |
| Managed roots | `CLAUDE.md`, `.claude/`, `.mcp.json` | `AGENTS.md`, `.agents/skills/`, `.codex/` | `.cursor/` | `.github/copilot-instructions.md`, `.github/instructions/`, `.github/skills/` | `GEMINI.md`, `.gemini/` |
| Shared files (extra approval) | `CLAUDE.md`, `.claude/CLAUDE.md`, `.claude/settings.json`, `.mcp.json` | `AGENTS.md`, `AGENTS.override.md`, `.codex/config.toml`, `.codex/hooks.json` | `.cursor/mcp.json` | `.github/copilot-instructions.md` | `GEMINI.md`, `.gemini/settings.json` |
| skill | `.claude/skills/<name>/SKILL.md` | `.agents/skills/<name>/SKILL.md` | — (no documented project format) | `.github/skills/<name>/SKILL.md` (Agent Skills spec) | `.gemini/skills/<name>/SKILL.md` (Agent Skills spec) |
| rule | `.claude/rules/*.md` (`paths:`) | — | `.cursor/rules/**/*.mdc`, rendered: `paths` → `globs`, `alwaysApply: false` | `.github/instructions/<name>.instructions.md`, rendered: `paths` → `applyTo` (`**` when none) | — |
| instruction | section in `CLAUDE.md` | section in `AGENTS.md` | `.cursor/rules/agent-forge-<section>.mdc`, `alwaysApply: true` | section in `.github/copilot-instructions.md` | section in `GEMINI.md` |
| agent | `.claude/agents/<name>.md` | — (trusted projects only) | — | — (`.github/agents` not on verified pages) | — |
| hook | `.claude/settings.json` fragment (class `hook`) | — (per-hash trust) | — (`.cursor/hooks.json` not on verified pages) | — (no mechanism) | — (settings hooks not verified as project files) |
| mcp | `.mcp.json` fragment (class `mcp`) | — (`config.toml`, trusted only) | `.cursor/mcp.json` fragment (`type: stdio` + `command`, or `url`) | — (repository settings / IDE) | `.gemini/settings.json` fragment, rendered: `type` dropped, `url` → `httpUrl` unless sse |
| Content rules | skill `name` without forbidden chars; agent `name` + `description`; rule `paths` list | skill `name` + `description`, lowercase = directory; AGENTS.md 32 KiB cap | `.mdc` with frontmatter; `globs` string; `alwaysApply` bool; instructions `alwaysApply: true` | skill name 1-64 lowercase/hyphens = directory, description ≤ 1024; rule `applyTo` required, `excludeAgent` ∈ code-review/cloud-agent | skill name = directory, description; MCP: exactly one of command/url/httpUrl, no `type`, no `_` in names |
| Tool version | `claude --version`, verified ≥ 2.0.0 | `codex --version` (no range yet) | `cursor --version` (no range yet) | `copilot --version` (no range yet) | `gemini --version` (no range yet) |

Every curated skill, rule, instruction and MCP capability declares destinations for the
platforms that can express it; the conformance suite (`tests/conformance/`) renders each one
and checks it against the adapter's own rules.

## Rendering

`PlatformAdapter.render(kind, rel_path, content)` is a pure function called by the planner for
each primary file of a destination, before validation and hashing. The plan, the diff shown
at approval, the approval-bound hash and `managed.json` all carry the rendered bytes;
`apply` never transforms. Rendering must be deterministic across operating systems
(`tests/conformance/test_render.py` checks CRLF/LF input renders the same bytes). The
default is the identity; Cursor renders rules and instructions, Copilot renders rules,
Gemini renders MCP fragments. Anything a platform cannot express is listed in
`unsupported_notes` and rejected, never approximated.

## Tool versions

`AdapterInfo.version_command`, `min_version`, `max_version` record how to ask the installed
tool for its version and the range the conventions were verified for. `agent-forge doctor`
shows the detected version per platform. Planning commands (`forge`, `assign`, `upgrade`,
`setup`) refuse a tool outside the range with both versions in the message (exit 15) and
add a note when the tool is absent or silent, since a project can be prepared on a machine
that does not run the tool.

## Watching upstream documentation

Adapters record `docs_url` and `verified_on`. `scripts/watch_docs.py --update` stores a
digest of every verified page in `adapters/docs_hashes.json`; the weekly `docs-watch`
workflow runs `--check` and opens an issue when a page changed. The fix is one PR that
re-verifies the conventions, bumps `verified_on` and refreshes the digests.

## Reporting unsupported features

`assign` rejects with `unsupported_platform` and the adapter's reason, e.g.
"Gemini CLI adapter does not support kind 'rule'". Nothing is silently renamed or
text-substituted; a capability is offered on a platform only if its manifest lists that
platform *and* the adapter supports the kind.

## Adding a platform

1. Verify the official conventions and record the URL + date in the module docstring; add
   the page(s) to `EXTRA_PAGES` in `scripts/watch_docs.py` and run `--update`.
2. Subclass `PlatformAdapter`: `info` (roots, shared files, kinds, unsupported notes,
   `version_command`), `detect`, `collect_assets`, `validate_content`, and `render` when
   the platform's format differs from the canonical one.
3. Add the `Platform` enum value, register in `adapters/__init__.py`, run
   `scripts/export_schemas.py`.
4. Add a destination row to `tests/conformance/test_render.py` and fixtures in
   `tests/unit/test_new_adapters.py`; the whole conformance suite must pass unchanged.
5. Add destinations to the curated manifests that the platform can express (skills and
   instruction sections reuse `claude_code/...` assets; rules are listed per file).
