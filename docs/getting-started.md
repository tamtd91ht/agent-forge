# Getting started

The usual path is the one-line installer run in a project root, then `/agent-forge-upgrade`
in Claude Code (see the [README](https://github.com/tamtd91ht/agent-forge/blob/main/README.md) and ADR-0004). This page is the CLI underneath,
for reviewing plans by hand or scripting. `agent-forge` below means the launcher
`~/.agent-forge/bin/agent-forge` (`agent-forge.cmd` in PowerShell / cmd), or the
`.venv` entry point in a development checkout.

## Workspace

The installer creates the workspace in `~/.agent-forge` (catalog, plans, backups, audit log).
In a development checkout, the repository itself is a workspace:

```bash
agent-forge init            # in the repo: verifies registry/, sources/, state/
agent-forge init --workspace ~/.agent-forge   # or anywhere else: seeds registry + sources.yaml
```

`init` is idempotent and never overwrites existing files. Set `AGENT_FORGE_HOME` or pass
`--workspace` to use a workspace that is not the current directory.

## Optional: clone upstream sources

```bash
agent-forge sources clone          # git clone into sources/checkouts/ (network)
agent-forge sources list
agent-forge sources sync --update  # fetch + move checkout; never touches registry or targets
```

Cloning is only needed to re-curate (`scripts/curate.py`) or to verify provenance
(`validate` reports "checkout not present" otherwise). Installing capabilities does not need
the checkouts.

## One command: `forge`

```bash
agent-forge forge "/path/to/my app"                       # interactive: shows plan + diff, asks once
agent-forge forge "/path/to/my app" --shared-files        # also allow a managed section in CLAUDE.md / AGENTS.md
agent-forge forge "/path/to/my app" --dry-run --show-diff # plan + full diff, write nothing
agent-forge forge "/path/to/my app" --yes --shared-files --json   # CI / scripted
```

`forge` scans the project, upgrades what Agent Forge already manages, adds the capabilities
whose applicability rules match (languages, frameworks, project type, existing assets), then
approves and applies after a single confirmation and validates the result. It is strictly
project-aware: a backend-only service gets security/error-handling/TDD material, never UI/UX
guidance; a Next.js app gets the UI guidelines too. Capabilities that need a native runtime
(REA, the full UI UX Pro Max toolkit) are listed with install hints only when they are
relevant and requested (`--want reverse-engineering`, `--want design-system`).

Three kinds of change need their own approval class and are asked for separately
(interactively, or via flags):

```bash
agent-forge forge "/path/to/my app" --shared-files --hooks --mcp   # grant all three
```

- `--shared-files` — a managed section in `CLAUDE.md` / `AGENTS.md`
- `--hooks` — hook entries merged into `.claude/settings.json` plus small scripts under
  `.claude/hooks/agent-forge/` (secret-file guard, format-on-edit); they run commands
- `--mcp` — MCP servers merged into `.mcp.json` (Context7 docs, Playwright browser); they
  launch processes and use the network, and Claude Code will ask you to trust them too

Without a flag the matching capabilities are left out and listed as `needs_approval`.

## Step by step (the same flow, one command at a time)

```bash
agent-forge scan   "/path/to/my app"               # read-only profile
agent-forge assign "/path/to/my app" --want security   # writes a plan, not the project
agent-forge diff   plan-…                          # exact changes
agent-forge approve plan-… --shared-files          # binds approval to the plan digest
agent-forge apply  plan-…                          # asks for confirmation, then writes
agent-forge validate "/path/to/my app"
agent-forge status   "/path/to/my app"
```

Useful flags:

- `--platform claude_code|codex` (repeatable) — default is what `scan` detected, else
  `claude_code`.
- `--want <tag>` — request capabilities carrying a tag (`security`, `ui`, `git`, `adr`, …).
- `--request <id>` / `--exclude <id>` — force-consider or never select a capability.
- `--include-optional` — promote optional candidates (high risk / needs permissions).
- `--json` on every command for machine-readable output.

## Project policy (optional)

Put a `.agent-forge/policy.yaml` in the project to tighten what Agent Forge may ever plan
there; it can only restrict, never loosen, the workspace defaults:

```yaml
name: team
max_risk: medium                 # deny anything riskier
classes: { hook: deny }          # never plan hooks here
capabilities:
  deny: ["rea.*"]
  require_request: ["mcp.*"]     # MCP servers only when explicitly requested
```

`agent-forge policy "/path/to/my app"` shows the merged layers and every verdict.

## In a team

```bash
agent-forge sync  "/path/to/my app"                           # fresh clone: restore managed files to the committed state
agent-forge check "/path/to/my app"                           # CI gate: exit 0 clean, 12 drift/problems
agent-forge approve <plan> --export-approval .agent-forge/approval.yaml   # record the reviewed set for CI
agent-forge forge "/path/to/my app" --approval-file .agent-forge/approval.yaml  # CI: apply only what the file covers
```

Roles, the approval flow and the team registry are in [team-workflow.md](team-workflow.md).

## Maintain what is installed

```bash
agent-forge drift  "/path/to/my app"                         # what changed since install
agent-forge repair "/path/to/my app" --strategy restore      # plan: rewrite drifted files
agent-forge repair "/path/to/my app" --strategy unmanage     # plan: keep files, stop managing
agent-forge remove "/path/to/my app" ecc.tdd-workflow        # plan: uninstall one capability
agent-forge audit                                            # who planned/approved/applied what
agent-forge doctor                                           # environment + workspace health
```

## Undo

```bash
agent-forge rollback tx-…            # refuses if you edited installed files
agent-forge rollback tx-… --partial  # rolls back untouched files, keeps your edits
```

## Keep installed capabilities current

```bash
git pull                                       # in the Agent Forge checkout
agent-forge init --refresh-registry            # only if your workspace is not that checkout
agent-forge forge "/path/to/my app"            # upgrades managed capabilities, then adds new fits
agent-forge upgrade "/path/to/my app"          # or: plan only; then diff / approve / apply as above
```
