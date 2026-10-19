# Agent Forge

**Set up Claude Code (or Codex) for a project in one command.** Agent Forge looks at your
project, picks reviewed skills, rules and subagents that actually fit it, shows you exactly
which files it will write, and installs them only after you say yes. Every install can be
undone.

```bash
agent-forge forge "path/to/my-app"
```

What it will **never** do: change your own text in `CLAUDE.md` / `AGENTS.md` (it only adds a
clearly marked section, and only if you allow it), touch `~/.claude` or `~/.codex`, run
third-party installers, or write anything before you confirm.

## What you get

Real result for a small Python/FastAPI backend:

```
my-app/
├── CLAUDE.md                            # + one marked section (only with --shared-files)
├── .claude/
│   ├── rules/ecc-common/                # always-on rules: style, testing, security, review
│   ├── skills/security-review/          # because it is a backend
│   ├── skills/error-handling/           # because it is Python
│   ├── skills/tdd-workflow/
│   ├── skills/verification-loop/
│   └── agents/planner.md
└── .agent-forge/managed.json            # what Agent Forge installed: commit it with your project
```

A React/Next.js app would also get UI/UX guidelines; a backend never does. Nothing is
installed just because it exists in the catalog.

## Install (once)

Needs Python 3.11+ and git.

```bash
git clone https://github.com/tamtd91ht/agent-forge.git
cd agent-forge
python -m venv .venv
.venv\Scripts\Activate.ps1          # Windows PowerShell   (macOS/Linux: source .venv/bin/activate)
pip install -e .
agent-forge init
```

> **The cloned folder is your workspace, not your project.** It holds the capability
> catalog and Agent Forge's own records (plans, backups, audit log). Your projects stay
> separate: **do not run `agent-forge init` inside a project**.

To run `agent-forge` from any directory, point it at the workspace:

```bash
setx AGENT_FORGE_HOME "D:\tools\agent-forge"      # Windows (new terminals)
export AGENT_FORGE_HOME=~/tools/agent-forge       # macOS/Linux (add to your shell profile)
```

Without it, run the commands from inside the cloned folder.

## Set up a project

**1. Preview.** This writes nothing:

```bash
agent-forge forge "path/to/my-app" --dry-run
```

You get the detected stack, the list of **selected** capabilities with the reason for each,
what was **not selected** and why, and every file that would be created.

**2. Install.**

```bash
agent-forge forge "path/to/my-app"
```

It shows the same plan and asks once. If the plan wants to edit `CLAUDE.md`, add hooks or
add MCP servers, it asks for each of those separately (see below).

**3. Open the project in Claude Code.** New skills, rules and agents load in a new session.
If MCP servers were added, Claude Code asks whether to trust them: answer **yes**, otherwise
they stay installed but disabled.

> Tip: commit your project first. Then `git diff` shows exactly what Agent Forge added.

### The three extra permissions

Plain files under `.claude/` only need your normal "yes". These need an explicit opt-in,
because they change shared files or run things:

| Flag | What it allows | Suggestion |
|---|---|---|
| `--shared-files` | A marked section in `CLAUDE.md` / `AGENTS.md` | Usually yes |
| `--hooks` | Entries in `.claude/settings.json` that run commands on edits (secret-file guard, auto-format) | Yes if you use ruff / prettier (the format hook does nothing when they are missing) |
| `--mcp` | Servers in `.mcp.json` (Context7 docs, Playwright browser); they start processes and use the network | Only if you want them; needs Node.js |

Interactive runs ask for each one. With `--yes` (scripts/CI), anything not granted by a flag
is simply left out.

### Reading the "not selected" list

| Category | Meaning | To include it anyway |
|---|---|---|
| `needs_approval` | Needs one of the flags above | add `--shared-files` / `--hooks` / `--mcp` |
| `optional` | Higher risk or needs extra permissions (e.g. a subagent that can run shell commands) | `--request <id>` or `--include-optional` |
| `not_applicable` | Does not fit the detected stack, or is opt-in only | `--want <tag>` or `--request <id>` |
| `conflict` | Overlaps with something already selected or a file you own | `--exclude` the other one, or move your file |
| `equivalent_exists` | Your project already has something similar | `--request <id>` |

## Let Claude do the review

Agent Forge matches on manifests and declared rules; it cannot read your code or judge
whether a catalog item contradicts your own `.claude/rules`. The `agent-forge-upgrade` skill
hands that review to Claude Code and keeps Agent Forge as the only writer:

```
/agent-forge-upgrade path/to/my-app
```

Claude scans with Agent Forge, reads the project's `CLAUDE.md`, rules, skills and tooling,
proposes ADD / SKIP / UPGRADE / ASK per capability with the file it checked, runs the
resulting `forge --dry-run`, and applies only after you say yes. It works out of the box when
Claude Code is opened in the Agent Forge workspace; to use it from any project copy
`.claude/skills/agent-forge-upgrade/` into `~/.claude/skills/`, or install it into a project
with `--request forge.skill.agent-forge-upgrade`.

Its sibling `/agent-forge-scout https://github.com/owner/repo` reviews a public repository for
Agent Forge itself: what is genuinely impressive in it, and whether it could become curated
content or an engine upgrade in line with the ADRs. Read-only, it never runs the repo's code,
and it hands you a proposed `sources.yaml` entry or ADR stub instead of writing them.

## Everyday tasks

| I want to… | Command |
|---|---|
| See everything available | `agent-forge catalog` |
| Read about one capability | `agent-forge catalog show ecc.security-review` |
| Add a specific capability | `agent-forge forge "my-app" --request ecc.agent.code-reviewer` |
| Add everything about a topic | `agent-forge forge "my-app" --want security` |
| Never install something | `agent-forge forge "my-app" --exclude ecc.agent.planner` |
| See what is installed | `agent-forge status "my-app"` |
| Get updates | `git pull` in the workspace, then `agent-forge forge "my-app"` again (if your workspace is a separate folder, run `agent-forge init --refresh-registry` after the pull) |
| See what I changed in installed files | `agent-forge drift "my-app"` |
| Undo an install | `agent-forge status "my-app"` (copy the `tx-…` id), then `agent-forge rollback tx-…` |
| Remove one capability | `agent-forge remove "my-app" <id>`, then `approve` + `apply` the printed plan |
| Run without prompts (CI) | `agent-forge forge "my-app" --yes --shared-files --json` |

Useful `--want` tags: `security`, `testing`, `tdd`, `review`, `planning`, `adr`, `git`,
`ui`, `ux`, `e2e`, `docs`, `hooks`, `formatting`, `karpathy`.

Rollback never overwrites files you edited after the install: it stops and tells you. Use
`--partial` to undo everything else and keep your edits.

## When something goes wrong

| Message | Fix |
|---|---|
| `No Agent Forge workspace found` | Run from the cloned folder, or set `AGENT_FORGE_HOME` (see Install) |
| `plan is stale` | The project changed after planning; just run `forge` again |
| `destination exists and is user-owned` | You already have a file there. Rename it, or `--exclude` that capability |
| MCP server installed but not working | Claude Code was told not to trust it. Remove its name from `disabledMcpjsonServers` in `.claude/settings.local.json` |
| `files changed independently after apply` | You edited installed files; use `rollback --partial` |

More: [troubleshooting](docs/troubleshooting.md) · `agent-forge doctor` checks your setup.

## Going further

- [Getting started](docs/getting-started.md): the step-by-step flow (`scan` → `assign` →
  `diff` → `approve` → `apply`) for reviewing a plan before approving it, and project
  policies (`.agent-forge/policy.yaml`) that restrict what may ever be installed
- [CLI reference](docs/cli-reference.md): every command, flag and exit code
- [Security model](docs/security.md) · [Architecture](docs/architecture.md) ·
  [Capability model](docs/capability-model.md) · [Adapters](docs/adapters.md)
- Curating new content: [source curation](docs/source-curation.md) ·
  [maintenance](docs/maintenance.md) · [upgrade lifecycle](docs/upgrade-lifecycle.md)
- Design decisions: [ADR-0001](docs/adr/0001-architecture-decisions.md) ·
  [ADR-0002](docs/adr/0002-upgrade-roadmap.md) · status: [WORKSPACE_STATUS.md](WORKSPACE_STATUS.md)

Content comes from reviewed upstream projects: Everything Claude Code, UI UX Pro Max, REA and
andrej-karpathy-skills. Each item records its source commit and license.

## Development

```bash
pip install -e ".[dev]"
.venv/Scripts/ruff check src tests scripts && .venv/Scripts/python -m pytest -q
agent-forge validate
python scripts/export_schemas.py     # after model changes
python scripts/curate.py             # re-copy curated assets from pinned checkouts
```

Agent rules for contributors: [AGENTS.md](AGENTS.md).

License: MIT (see `LICENSE`). Curated upstream content keeps its own notices
(`LICENSE-*.txt` next to installed files).
