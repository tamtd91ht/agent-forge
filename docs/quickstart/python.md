# Quickstart: Python (5 minutes)

What you get: reviewed skills, rules, a planning subagent and (if you say yes) hooks and MCP
servers chosen for a Python project, installed into `.claude/` and tracked in
`.agent-forge/managed.json` so every install can be rolled back.

Detection looks for `pyproject.toml`, `requirements*.txt` or `setup.py` (plus FastAPI/Django/Flask in dependencies, `pytest`).

## 1. Install (in the project root)

No project yet? Make a throw-away one:

```bash
mkdir demo-api && cd demo-api && printf '[project]
name="demo-api"
version="0"
dependencies=["fastapi","pytest"]
' > pyproject.toml && mkdir app && echo 'x = 1' > app/main.py && git init -q && git add -A && git commit -qm init
```

Then, in the project root:

```powershell
# Windows
irm https://raw.githubusercontent.com/tamtd91ht/agent-forge/main/install.ps1 | iex
```

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/tamtd91ht/agent-forge/main/install.sh | bash
```

This installs the latest release into `~/.agent-forge` and adds `/agent-forge-upgrade` to the
project. Nothing else is written yet.

## 2. Preview what fits (optional, 10 seconds)

```bash
~/.agent-forge/bin/agent-forge forge --dry-run .          # Windows: ~/.agent-forge/bin/agent-forge.cmd
```

Typical result for this stack:

- `ecc.rules.common`, `ecc.security-review`, `ecc.tdd-workflow`, `ecc.verification-loop`, `ecc.error-handling`
- `ecc.agent.planner`, `mattpocock.diagnosing-bugs`
- `karpathy.principles` section in `CLAUDE.md` (needs `--shared-files` / a yes)
- `forge.hook.guard-secrets-python` and `forge.hook.python-ruff-format`: block edits to secret files, run `ruff format` after edits (need `--hooks` / a yes)
- `mcp.context7` (needs `--mcp` / a yes)

Rows marked `needs_approval` are the ones that touch shared files, hooks or MCP; nothing is
written in a dry run.

## 3. Install with the agent

Open the project in Claude Code and run `/agent-forge-upgrade`. The agent reads your code and
`CLAUDE.md`, proposes a table (install / skip / why), asks for the three extra permissions
(shared files, hooks, MCP) and installs only after you answer **yes**.

Without the agent, the same thing in one command:

```bash
~/.agent-forge/bin/agent-forge forge . --shared-files --hooks --mcp
```

## 4. Check and commit

```bash
~/.agent-forge/bin/agent-forge status .     # what is installed, drift, outdated
~/.agent-forge/bin/agent-forge check .      # one exit code for CI: drift, revoked, invalid manifest
pytest -q
git add .claude .agent-forge CLAUDE.md .mcp.json && git commit -m "Add agent capabilities (agent-forge)"
```

Start a new Claude Code session so the new skills and rules load. Teammates who clone the
repository run `~/.agent-forge/bin/agent-forge sync .` after installing Agent Forge once; see
[team workflow](../team-workflow.md).

## Undo

`agent-forge status .` lists the transaction id; `agent-forge rollback tx-…` restores every
file you did not edit afterwards. `agent-forge remove . <id>` removes one capability.
