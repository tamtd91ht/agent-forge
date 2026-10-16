# Source curation record (initial catalog, 2026-10-16)

Principle: small, verified, low-duplication. Every item below was read in the checkout at the
recorded revision. "Verbatim" means byte-identical to upstream.

## Curated (20)

| Capability | From | Decision | Why |
|---|---|---|---|
| `ecc.tdd-workflow` | ECC `skills/tdd-workflow/SKILL.md` | verbatim, both platforms, always | pure markdown; optional `.claude/tdd/` mention is harmless |
| `ecc.verification-loop` | ECC `skills/verification-loop/SKILL.md` | verbatim, Claude only, always | wording is Claude-session specific; mentions hooks informationally |
| `ecc.security-review` | ECC `skills/security-review/*` (2 files) | verbatim, both, backend/fullstack/service/infra or `--want security` | no external refs |
| `ecc.coding-standards` | ECC `skills/coding-standards/SKILL.md` | verbatim, both, always; conflicts with `ecc.rules.common` | one mention of "narrower ECC skill"; harmless |
| `ecc.error-handling` | ECC `skills/error-handling/SKILL.md` | verbatim, both, TS/JS/Python/Go only | content covers only those languages |
| `ecc.conventional-commit-review` | ECC `skills/conventional-commit-review/SKILL.md` | verbatim, both, tag `git` | many teams already document commit rules |
| `ecc.architecture-decision-records` | ECC `skills/architecture-decision-records/SKILL.md` | verbatim, both, tag `adr` | not every project keeps ADRs |
| `ecc.agent.planner` | ECC `agents/planner.md` | adapted (attribution footer), Claude only, always | documented frontmatter only (`tools`, `model: opus`) |
| `ecc.agent.code-reviewer` | ECC `agents/code-reviewer.md` | adapted (footer), Claude only, optional (`runs_shell`) | has Bash access ⇒ permission flag |
| `ecc.rules.common` | ECC `rules/common/{coding-style,testing,security,code-review,patterns,development-workflow}.md` | verbatim into `.claude/rules/ecc-common/`, Claude only, always | no frontmatter ⇒ always-on; cheaper than the skill |
| `uiux.guidelines` | UI UX Pro Max `references/{quick-reference,pro-rules}.md` + workspace SKILL.md | adapted, both, frontend/fullstack/mobile | upstream SKILL.md needs `${CLAUDE_PLUGIN_ROOT}` + Python scripts |
| `uiux.full-toolkit` | UI UX Pro Max (whole skill set) | `native_plugin` with `uipro` hints | installer copies 3 MB data + scripts; sub-skills call external APIs |
| `rea.reverse-engineer-anything` | REA `.agents/skills/reverse-engineer-anything` + MCP server | `native_plugin`, tag-only, risk high | skill is inert without the REA runtime; runtime attaches debuggers |
| `forge.managed-notice` | workspace | `section_merge` into `CLAUDE.md` / `AGENTS.md`, always | makes managed skills discoverable; exercises shared-file approval |
| `forge.hook.guard-secrets-python` / `-node` | workspace | hook (class `hook`): PreToolUse script blocks edits to `.env*`, keys, credentials; Python variant for Python projects, Node variant for JS/TS (mutually conflicting) | stdlib / dependency-free, exit 2 blocks the tool call, never reads the file |
| `forge.hook.python-ruff-format` | workspace | hook: PostToolUse `ruff format` on the edited `.py`; no-op without ruff | single file, no network |
| `forge.hook.node-prettier-format` | workspace | hook: PostToolUse runs the project's `node_modules/.bin/prettier` on the edited file; no-op if absent | never uses npx |
| `mcp.context7` | ECC `mcp-configs/mcp-servers.json` (template) | mcp (class `mcp`): `npx -y @upstash/context7-mcp@latest`, always | docs lookup for any project; network, downloads on first use |
| `mcp.playwright` | ECC `mcp-configs/mcp-servers.json` (template) | mcp: `npx -y @playwright/mcp@latest`, frontend/fullstack only | browser automation; `--browser chrome` flag dropped |

## Excluded on purpose

| Item | Reason |
|---|---|
| ECC `hooks/` and all `scripts/hooks/*.js` | execute `node -e`, run `npx tsc`/formatters, probe HTTP, write under `~/.claude`, gate edits |
| ECC `rules/common/{agents,hooks,git-workflow,performance}.md` | describe ECC's own agents/hooks, reference `~/.claude/settings.json` and CLI flags |
| ECC `rules/<language>/` | useful, but each file "extends ../common/…"; needs a per-language capability with path globs — candidate for v0.2 |
| ECC `commands/` | legacy shims; skills are canonical |
| ECC `mcp-configs/`, `.mcp.json` | launch processes (`npx -y …`) |
| ECC `skills/osint-investigation` | CC-BY-SA-4.0 (share-alike) |
| ECC supply-chain skills (8) | Apache-2.0 and niche |
| ECC `skills/continuous-learning*`, `gateguard`, `strategic-compact`, `safety-guard`, `delivery-gate` | depend on ECC hooks/scripts |
| ECC `.agents/skills/*` (Codex forks) | older divergent copies; the Claude SKILL.md already satisfies Codex frontmatter |
| ECC `agents/security-reviewer.md` | deferred: overlaps `ecc.security-review`; add with a dependency in v0.2 |
| UI UX Pro Max `design/`, `ui-styling/`, `design-system/`, `brand/`, `slides/`, `banner-design/` | call Gemini/Pexels/external APIs, `subprocess`, Node scripts; `ui-styling` is Apache-2.0 with OFL fonts |
| UI UX Pro Max `stack/` | a sample project with `.mcp.json` launching Playwright/chrome-devtools via `npx -y` |
| REA `rea-changelog-update`, `rea-ci-tests-audit`, `rea-tool-design` | only meaningful inside the REA repo |

## Re-curation workflow

```bash
agent-forge sources sync --update        # moves checkouts to upstream HEAD
python scripts/curate.py --allow-revision-drift
git diff registry/                       # review every changed asset
# bump `version` and `source.revision` in affected capability.yaml files
agent-forge validate
```

Nothing in a target project changes until a user runs `upgrade` → `approve` → `apply`.
