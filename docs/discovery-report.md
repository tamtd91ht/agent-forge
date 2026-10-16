# Discovery report (Phase A)

Date: 2026-10-16. Workspace: `D:\works\vihat\opensources\agent-forge` (was empty except the
master prompt; now a git repository created by this session, no commits made).

## 1. Environment

| Item | Finding |
|---|---|
| OS / shell | Windows 11 (10.0.26200), Git Bash (MSYS) + PowerShell 5.1 |
| Python | 3.14.3 (`python`); pip 25.3; no `uv`, `poetry`, `pipx` on PATH |
| Git | 2.44.0.windows.1 |
| Lint / test tools | none installed globally; `ruff 0.17.1`, `pytest 9.1.1`, `hypothesis 6.170` installed into a project-local `.venv` |
| Claude Code | CLI 2.1.301 at `~/.local/bin/claude`; `~/.claude/settings.json` present (permissions, model, plugins); `~/.claude/skills/` has 2 entries; no `~/.claude/agents` or `~/.claude/rules` |
| Codex | not installed; no `~/.codex` |
| Symlinks | cannot be created without elevation in this environment (tests that need them skip); junctions can, and are covered by tests |

Nothing was installed globally. All dependencies live in `.venv/`.

## 2. Upstream sources (verified by reading the checkouts, not READMEs alone)

Checkouts live in `sources/checkouts/` (git-ignored). Revisions recorded in
`state/cache/sources-state.json` and in every capability manifest.

### REA — github.com/morluto/rea @ `1b97b0f3` (2026-10-16), MIT

- **What it is:** npm package `rea-agents` 6.5.0; one binary that is a CLI *and* a stdio MCP
  server wrapping Ghidra, Hopper, IDA, JADX, Frida, adb, tshark, binwalk, LLDB, Chrome CDP,
  mitmproxy. Requires Node ^22.19 / ^24.11 / >=26.
- **Install surface:** `install.sh` runs `npm install --global rea-agents`, then `rea setup`,
  which writes `~/.claude.json` (MCP registration) and copies a skill into `~/.claude/skills`.
  Agent Forge never runs either.
- **Skills:** 4 under `.agents/skills/`. Three are for maintaining REA itself. The only
  end-user one, `reverse-engineer-anything` (355 lines), says itself that installing the skill
  "does not register the REA MCP server" and is useless without the runtime.
- **Security:** Frida script injection into live processes, LLDB-launched targets, adb device
  access, driving the user's real browser. All high privilege.
- **Licensing:** MIT; `THIRD_PARTY_NOTICES.md` lists LGPL (frida), Apache-2.0 and GPL runtime
  components that are not redistributed; `DISCLAIMER.md` restricts use (no DRM/anti-cheat
  bypass).
- **Decision:** one capability, `rea.reverse-engineer-anything`, recorded as
  `native_plugin` with install hints. Never recommended by default (tag-only), risk `high`.

### ECC — github.com/affaan-m/ECC @ `76aaa77d` (2026-10-15), MIT, v2.2.3

- **What it is:** Claude Code plugin (`.claude-plugin/plugin.json`) plus a content pack:
  311 skills, 71 agents, 97 legacy commands, `rules/` (10 common + 22 language dirs), `hooks/`,
  `mcp-configs/`, and ports for ~16 other harnesses.
- **Install surface:** `install.sh/.ps1` wrap `scripts/install-apply.js`; the `claude` target
  writes into `~/.claude/` and can register hooks in `~/.claude/settings.json`;
  `scripts/sync-ecc-to-codex.sh` sets `git config --global core.hooksPath`. Never run.
- **Hooks:** inline `node -e` bootstraps that run formatters, `npx tsc`, MCP health probes
  (HTTP), and write session/cost logs under `~/.claude`. Behaviour-altering gates (deny first
  edit per file, block linter-config edits). Excluded from curation entirely.
- **Licensing:** MIT overall; exceptions found and avoided: `skills/osint-investigation`
  (CC-BY-SA-4.0), 8 supply-chain skills (Apache-2.0), `react-performance` (adapted from
  vercel-labs, attributed).
- **Codex support:** partial; `.agents/skills/` holds 46 older forks of the Claude skills,
  no general converter. Agent Forge therefore installs the same markdown skill for both
  platforms only when its frontmatter already satisfies Codex (`name` + `description`).
- **Decision:** 10 capabilities curated (7 skills, 2 agents, 1 rule set) — all pure markdown,
  byte-identical to upstream except agents, which get an attribution footer. See
  `docs/source-curation.md` for what was excluded and why.

### UI UX Pro Max — github.com/nextlevelbuilder/ui-ux-pro-max-skill @ `56ea9cf1` (2026-10-15), MIT, v2.15.0

- **What it is:** Claude Code plugin with 7 skills, an npm installer (`uipro`, package
  `ui-ux-pro-max-cli`) that renders per-platform SKILL.md for 19 platforms, and a
  `skill.json` manifest. Source of truth is `src/ui-ux-pro-max/` (data CSVs ~3 MB, stdlib-only
  Python search + design-system generator).
- **Install surface:** `uipro init --ai <platform>` writes SKILL.md + `data/` + `scripts/` +
  6 sub-skills into the project; `--global` writes under `~`. Sub-skills `design/`,
  `ui-styling/`, `design-system/` call external APIs (Gemini, Pexels) or `subprocess`.
- **Portability issue:** the Claude SKILL.md hard-codes `${CLAUDE_PLUGIN_ROOT}`, which is only
  set for plugin installs.
- **Licensing:** MIT; `ui-styling` sub-skill is Apache-2.0 with SIL OFL fonts.
- **Decision:** `uiux.guidelines` (adapted, markdown-only: the two self-contained reference
  files plus a workspace-authored SKILL.md) for frontend projects, and `uiux.full-toolkit`
  recorded as `native_plugin` pointing at the upstream CLI.

## 3. Platform conventions verified (official docs, 2026-10-16)

| Platform | Project-scoped locations Agent Forge may manage | Verified but not managed in v0.1 |
|---|---|---|
| Claude Code (code.claude.com/docs) | `CLAUDE.md`, `.claude/skills/<n>/SKILL.md`, `.claude/rules/*.md` (`paths:` globs), `.claude/agents/<n>.md` | `.claude/settings.json` hooks (33 events), `.mcp.json`, plugins/marketplaces, `.claude/commands` (legacy, merged into skills) |
| Codex rust-v0.163.0 (learn.chatgpt.com/docs) | `AGENTS.md` (32 KiB chain cap), `.agents/skills/<n>/SKILL.md` (name + description required) | `.codex/config.toml`, `.codex/hooks.json`, `.codex/agents/*.toml` — all loaded only for *trusted* projects; custom prompts deprecated |

## 4. Risks identified

1. Upstream hooks/installers write to user-wide config and run network/subprocess code.
   Mitigation: hooks and MCP declarations are not installable kinds in v0.1.
2. Windows junctions bypass `is_symlink()`. Mitigation: walker and path resolver check the
   reparse-point attribute (tested).
3. Skill names collide across sources (`security-review` skill vs agent). Mitigation:
   equivalence signals + destination-collision rejection.
4. ECC content is large (some SKILL.md > 500 lines). Mitigation: reported by `validate` as
   guidance, not blocked.

## 5. Implementation plan (executed)

Phase B foundation → Phase C read-only MVP → Phase D curation (14 capabilities) → Phase E
adapters (Claude Code, Codex) → Phase F apply/validate/status/rollback → Phase G e2e on a
disposable fixture with spaces + Unicode in the path → Phase H docs. See
`WORKSPACE_STATUS.md` for the current state and `CHANGELOG.md` for what shipped.
