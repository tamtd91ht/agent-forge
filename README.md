# Agent Forge

Set up Claude Code (or Codex) for your project: reviewed skills, rules, subagents, hooks and
MCP servers, chosen by the agent for your code and installed only after you say yes. Every
install can be undone.

## Install

Requirement: Python 3.11+. Run this **in your project's root folder**:

**Windows (PowerShell)**

```powershell
irm https://raw.githubusercontent.com/tamtd91ht/agent-forge/main/install.ps1 | iex
```

**macOS / Linux**

```bash
curl -fsSL https://raw.githubusercontent.com/tamtd91ht/agent-forge/main/install.sh | bash
```

## Use

1. Open the project in Claude Code.
2. Run:

   ```
   /agent-forge-upgrade
   ```

   Optional focus: `/agent-forge-upgrade testing and code review only`.
   In Codex, run the `agent-forge-upgrade` skill.
3. Read the proposed table (what to add, what to skip, and why), then answer **yes** to install.
4. Start a new session to load the new skills and rules. If MCP servers were added, accept
   Claude Code's trust prompt.
5. Commit the new files together with `.agent-forge/managed.json`.

The agent asks before adding anything that edits `CLAUDE.md` / `AGENTS.md`, adds hooks to
`.claude/settings.json`, or adds MCP servers to `.mcp.json`.

## Update

Run the install command again in the project root, then `/agent-forge-upgrade`.

Teammates who clone a project that already has `/agent-forge-upgrade` run the install command
once on their machine.

## Commands

`AF` = `~/.agent-forge/bin/agent-forge` (Windows PowerShell / cmd:
`~/.agent-forge/bin/agent-forge.cmd`). Run them in the project root.

| I want to… | Command |
|---|---|
| See what is installed | `AF status .` |
| See everything available | `AF catalog` |
| Read about one capability | `AF catalog show ecc.security-review` |
| Preview without the agent | `AF forge --dry-run .` |
| See what I changed in installed files | `AF drift .` |
| Undo an install | `AF status .` (copy the `tx-…` id), then `AF rollback tx-…` |
| Remove one capability | `AF remove . <id>`, then `AF approve <plan-id>` and `AF apply <plan-id>` |
| Limit what may ever be installed | create `.agent-forge/policy.yaml` ([example](docs/getting-started.md)) |

Useful topics for `/agent-forge-upgrade <focus>` or `AF forge . --want <tag>`: `security`,
`testing`, `tdd`, `review`, `planning`, `adr`, `git`, `ui`, `ux`, `e2e`, `docs`, `hooks`,
`formatting`, `karpathy`, `grill-with-docs`, `grilling`, `domain-modeling`,
`codebase-design`, `agent-docs`, `tdd-seams`, `git-guard`, `mattpocock`.

## Uninstall

1. Remove what was installed in a project: `AF status .`, then `AF rollback tx-…` for each
   transaction (newest first).
2. Remove Agent Forge from the machine: delete the `~/.agent-forge` folder.

## Troubleshooting

| Message | Fix |
|---|---|
| `/agent-forge-upgrade` is not listed | Start a new Claude Code session in the project root |
| `Python 3.11 or newer is required` | Install Python from python.org, then re-run the install command |
| `plan is stale` | The project changed after planning; run `/agent-forge-upgrade` again |
| `destination exists and is user-owned` | You already have a file there; rename it or skip that capability |
| MCP server installed but not working | Remove its name from `disabledMcpjsonServers` in `.claude/settings.local.json` |
| `files changed independently after apply` | You edited installed files; use `AF rollback --partial tx-…` |

More: [troubleshooting](docs/troubleshooting.md) · `AF doctor`.

## Docs

- [Getting started](docs/getting-started.md) · [CLI reference](docs/cli-reference.md) ·
  [Security model](docs/security.md) · [Architecture](docs/architecture.md) ·
  [Capability model](docs/capability-model.md) · [Adapters](docs/adapters.md)
- Curation: [source curation](docs/source-curation.md) · [rejections](docs/rejections/README.md) ·
  [maintenance](docs/maintenance.md) · [upgrade lifecycle](docs/upgrade-lifecycle.md)
- Decisions: [ADR-0001](docs/adr/0001-architecture-decisions.md) ·
  [ADR-0002](docs/adr/0002-upgrade-roadmap.md) ·
  [ADR-0003](docs/adr/0003-context-load-and-skill-calls.md) ·
  [ADR-0004](docs/adr/0004-install-into-project.md) · [status](WORKSPACE_STATUS.md)

Content comes from Everything Claude Code, UI UX Pro Max, REA, andrej-karpathy-skills and
Matt Pocock's skills; each item records its source commit and license.

## Developing Agent Forge

```bash
git clone https://github.com/tamtd91ht/agent-forge.git
cd agent-forge
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"          # macOS/Linux: .venv/bin/pip
.venv/Scripts/ruff check src tests scripts && .venv/Scripts/python -m pytest -q
.venv/Scripts/agent-forge validate
```

- After model changes: `python scripts/export_schemas.py`.
- Re-copy curated assets from pinned checkouts: `python scripts/curate.py`.
- Review a GitHub repo for the catalog: `/agent-forge-scout https://github.com/owner/repo`
  (Claude Code opened in this repository).
- Test the installer against this checkout: set `AGENT_FORGE_SOURCE` to the checkout path
  before running `install.ps1` / `install.sh`.
- Agent rules for contributors: [AGENTS.md](AGENTS.md).

License: MIT (see `LICENSE`). Curated upstream content keeps its own notices
(`LICENSE-*.txt` next to installed files).
