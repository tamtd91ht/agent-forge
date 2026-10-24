# dietrichgebert/ponytail hooks, band, statusline and runtime-bound skills

Source: `ponytail` (tag v5.3.2) — `hooks/` (`ponytail-activate.js`, `ponytail-mode-tracker.js`,
`ponytail-subagent.js`, `ponytail-map.js`, `ponytail-statusline.{sh,ps1}`, `band/`),
`hooks/claude-codex-hooks.json`, `hooks/claude-band.json`, `scripts/cursor-hooks.js`,
`skills/ponytail-gain`, `skills/ponytail-help`, the ~30 host adapters and plugin manifests.

## Decision

Not curated.

## Why

- **Hooks:** the SessionStart hook writes `~/.claude/.ponytail-active`, copies the statusline
  script into `~/.claude` on every session, and appends to the model's context "STATUSLINE
  SETUP NEEDED ... Proactively offer to set this up for the user", i.e. it steers the agent to
  edit `~/.claude/settings.json`. UserPromptSubmit and SubagentStart re-inject the ruleset
  every turn (always-loaded context that ADR-0003 asks to count, not to force). Upstream hook
  scripts are excluded (ADR-0001 D13) and nothing Agent Forge installs may write outside the
  project. `scripts/cursor-hooks.js install` merges into `~/.cursor/hooks.json`.
- **Band and board:** a Claude Code UI module that writes a per-project CSV under
  `~/.config/ponytail/band/` after every turn and, when configured, POSTs the task row
  (including the task name, i.e. the first prompt) to a webhook. Off by default and https-only,
  but telemetry that leaves the machine is not something a capability installs.
- **ponytail-gain:** a scoreboard of upstream's benchmark numbers; marketing, not a skill.
- **ponytail-help:** documents the levels, hooks, config file and plugin update flow that do
  not exist after a project-scoped install.
- **Adapters and manifests:** replaced by Agent Forge packaging.

## Revisit when

- `hooks/ponytail-map.js` (a 2,000-character codebase map built with `git ls-files` plus a
  regex per language, 3-second fail-open budget, writes nothing) is an idea worth a
  workspace-authored, stdlib-only SessionStart hook once Agent Forge accounts for the context a
  hook injects (today hooks count 0 in `context_load`) and a project asks for it.
- `skills/ponytail-audit` is the review checklist for a whole repo; curate when a project asks.
