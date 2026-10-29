# Agent Forge

[![ci](https://github.com/tamtd91ht/agent-forge/actions/workflows/ci.yml/badge.svg)](https://github.com/tamtd91ht/agent-forge/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/tamtd91ht/agent-forge?sort=semver)](https://github.com/tamtd91ht/agent-forge/releases/latest)
[![license](https://img.shields.io/github/license/tamtd91ht/agent-forge)](LICENSE)

Set up Claude Code, Codex, Cursor, GitHub Copilot or Gemini CLI for your project: reviewed skills, rules, subagents, hooks and
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

The installer installs the latest [release](https://github.com/tamtd91ht/agent-forge/releases/latest)
and verifies its SHA-256 (and its Sigstore signature when `cosign` is installed) before
anything is written; it never falls back to an unpinned branch. To pin a release (or roll
back), set the version first:

```bash
AGENT_FORGE_VERSION=v0.7.0 bash -c "$(curl -fsSL https://raw.githubusercontent.com/tamtd91ht/agent-forge/main/install.sh)"
```

```powershell
$env:AGENT_FORGE_VERSION = 'v0.7.0'; irm https://raw.githubusercontent.com/tamtd91ht/agent-forge/main/install.ps1 | iex
```

`AF doctor` shows which release is installed and how it was verified
(`--check-latest` compares with the newest release). [How to verify a release by hand](docs/operations.md#verifying-a-release).

Five-minute quickstarts: [Node / TypeScript](docs/quickstart/node.md) ·
[Python](docs/quickstart/python.md) · [Go](docs/quickstart/go.md) · [Java](docs/quickstart/java.md).

## Use

1. Open the project in Claude Code.
2. Run:

   ```
   /agent-forge-upgrade
   ```

   Optional focus: `/agent-forge-upgrade testing and code review only`.
   In Codex, run the `agent-forge-upgrade` skill.
3. Read the assessment table (what to add, what to skip, and the file or number that proves
   it; Agent Forge verifies every cited path and quote and turns an unprovable skip into a
   question), answer the open questions, then answer **yes** to install.
4. Start a new session to load the new skills and rules. If MCP servers were added, accept
   Claude Code's trust prompt.
5. Commit the new files together with `.agent-forge/managed.json`.

The agent asks before adding anything that edits `CLAUDE.md` / `AGENTS.md`, adds hooks to
`.claude/settings.json`, or adds MCP servers to `.mcp.json`.

## Install without the installer (uvx / pipx)

Teams that do not want a Python environment of their own can run a release through
[uv](https://docs.astral.sh/uv/) or pipx; both create an isolated environment:

```bash
uvx --from "git+https://github.com/tamtd91ht/agent-forge@v0.7.0" agent-forge --version
pipx install "git+https://github.com/tamtd91ht/agent-forge@v0.7.0"
```

Then `agent-forge init --workspace ~/.agent-forge` once, and `agent-forge setup` in a
project root adds `/agent-forge-upgrade`. The installer remains the recommended path
because it also wires the launcher the skill expects.

## Update

`AF forge .` and `AF upgrade .` check for a newer release first; when one exists the launcher
installs it through the same verified installer and re-runs the command, so a project upgraded
months ago is compared with the current catalog, not the one installed back then.
`AF self-update --check` only looks, `AF self-update` only installs, `--no-self-update` plans
with the installed version. Running the install command again in the project root does the
same by hand (and is the way to update an install made before this launcher existed).

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
| Score the config I already have, without installing anything | `AF lint .` |
| See why the agent skipped a capability | `AF decisions explain . <id>` |
| See which installed skills are never used (opt-in hook) | `AF usage .` after `AF forge . --want usage --hooks` |
| Bring a fresh clone to the committed state | `AF sync .` |
| Fail CI when installed files drifted | `AF check .` ([GitHub Action](docs/team-workflow.md#the-flow)) |
| Undo an install | `AF status .` (copy the `tx-…` id), then `AF rollback tx-…` |
| Remove one capability | `AF remove . <id>`, then `AF approve <plan-id>` and `AF apply <plan-id>` |
| Limit what may ever be installed | create `.agent-forge/policy.yaml` ([example](docs/getting-started.md)) |

Useful topics for `/agent-forge-upgrade <focus>` or `AF forge . --want <tag>`: `security`,
`testing`, `tdd`, `review`, `planning`, `adr`, `git`, `ui`, `ux`, `e2e`, `docs`, `hooks`,
`formatting`, `karpathy`, `grill-with-docs`, `grilling`, `domain-modeling`,
`codebase-design`, `agent-docs`, `tdd-seams`, `git-guard`, `mattpocock`, and per stack:
`java`, `spring`, `kotlin`, `go`, `react`, `vue`, `angular`, `python`, `django`, `rust`, `dotnet`,
`laravel`, `rails`, `swift`, `flutter`, `redis`, `postgres`, `mysql`, `kubernetes`, `api`,
`data-fetching`, `hexagonal`, `a11y`. Stack-specific content is proposed automatically when the
scan detects the language, framework or dependency; tags are for what a scan cannot see.

## Uninstall

1. Remove what was installed in a project: `AF status .`, then `AF rollback tx-…` for each
   transaction (newest first).
2. Remove Agent Forge from the machine: delete the `~/.agent-forge` folder.

## Troubleshooting

| Message | Fix |
|---|---|
| `/agent-forge-upgrade` is not listed | Start a new Claude Code session in the project root |
| `Python 3.11 or newer is required` | Install Python from python.org, then re-run the install command |
| `plan is stale` / `expired` / `policy changed` | Run `/agent-forge-upgrade` again |
| `needs recovery: tx-…` (status, doctor) | `AF rollback tx-…` ([recovery guide](docs/operations.md#recovery)) |
| `another Agent Forge process is writing to this project` | Wait for it; if none is running, delete the lock file named in the message |
| `invalid policy` | Fix or delete `.agent-forge/policy.yaml` ([policy](docs/policy.md)) |
| `destination exists and is user-owned` | You already have a file there; rename it or skip that capability |
| MCP server installed but not working | Remove its name from `disabledMcpjsonServers` in `.claude/settings.local.json` |
| `files changed independently after apply` | You edited installed files; use `AF rollback --partial tx-…` |

More: [troubleshooting](docs/troubleshooting.md) · `AF doctor`.

## Docs

- [Getting started](docs/getting-started.md) · [CLI reference](docs/cli-reference.md) ·
  [Operations & recovery](docs/operations.md) · [Policy](docs/policy.md) ·
  [Security model](docs/security.md) · [Architecture](docs/architecture.md) ·
  [Capability model](docs/capability-model.md) · [Adapters](docs/adapters.md) ·
  [Evaluation](docs/evaluation.md)
- Direction and status: [product vision](docs/product-vision.md) ·
  [engineering roadmap & release gates](docs/engineering-roadmap.md) ·
  [6-month plan](docs/roadmap-2026h2.md)
- Curation: [source curation](docs/source-curation.md) · [rejections](docs/rejections/README.md) ·
  [maintenance](docs/maintenance.md) · [upgrade lifecycle](docs/upgrade-lifecycle.md)
- Decisions: [ADR-0001](docs/adr/0001-architecture-decisions.md) ·
  [ADR-0002](docs/adr/0002-upgrade-roadmap.md) ·
  [ADR-0003](docs/adr/0003-context-load-and-skill-calls.md) ·
  [ADR-0004](docs/adr/0004-install-into-project.md) ·
  [ADR-0005](docs/adr/0005-production-hardening.md) ·
  [ADR-0006](docs/adr/0006-canonical-format-and-adapters.md) ·
  [ADR-0007](docs/adr/0007-decision-layer.md) ·
  [ADR-0008](docs/adr/0008-default-catalog-criteria.md) (proposed)
- Value: [evaluation](docs/evaluation.md) · [agent-forge-eval](tools/agent-forge-eval/README.md) ·
  [results](docs/evaluation/README.md)
- Teams: [team workflow](docs/team-workflow.md) · [pilots](docs/pilots/README.md) ·
  [team policy template](examples/policy/team-default.yaml)
- Contributing: [a capability](docs/contributing-capabilities.md) · [your own registry](docs/registries.md) ·
  [deprecation policy](docs/deprecation-policy.md) · [maintainers](MAINTAINERS.md)
- [Security policy](SECURITY.md) · [Contributing](CONTRIBUTING.md)

Content comes from Everything Claude Code, UI UX Pro Max, REA, andrej-karpathy-skills and
Matt Pocock's skills; each item records its source commit and license.

## Developing Agent Forge

```bash
git clone https://github.com/tamtd91ht/agent-forge.git
cd agent-forge
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"          # macOS/Linux: .venv/bin/pip
.venv/Scripts/ruff check src tests scripts tools && .venv/Scripts/python -m pytest -q
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
