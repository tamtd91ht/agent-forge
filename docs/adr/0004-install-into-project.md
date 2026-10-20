# ADR-0004: Install from the project root; the project's agent drives Agent Forge

Status: accepted (2026-10-20). Changes the user-facing entry point; ADR-0001 invariants stay.

## Context

Until now a user cloned this repository, made it a workspace, and pointed commands at a
project (`agent-forge forge path/to/app`). Two problems: the human had to learn the CLI, and
Agent Forge's matching (manifests, rules) cannot read the project the way the coding agent
in that project can. `forge.skill.agent-forge-upgrade` already let the agent review and drive
the CLI, but it had to be copied into each project by hand.

## Decision

1. **One command, run in the project root.** `install.ps1` (`irm … | iex`) and `install.sh`
   (`curl … | bash`) install or update Agent Forge, then add the entry skill to the project.
   They need only Python 3.11+.
2. **Where Agent Forge lives: `~/.agent-forge/`.** It is already the default workspace of
   ADR-0001 D1, so no new global location is introduced. Layout: workspace files
   (`agent-forge.yaml`, `registry/`, `sources/`, `state/`), the engine in `.venv/`, and
   launchers in `bin/` (`agent-forge` for POSIX shells and Claude Code's Bash tool on every
   OS, `agent-forge.cmd` for PowerShell / cmd). Each launcher sets `AGENT_FORGE_HOME` to that
   folder so a project never picks up another workspace by accident.

   Chosen over the alternatives from Claude Code's point of view:
   - *Inside the project* (`.agent-forge/cache`): a venv and a catalog copy per project, a
     risk of committing them, and the scanner and the agent's searches would see them.
   - *Under `~/.claude/`*: Claude Code's own directory (settings, transcripts, plugins);
     ADR-0001 forbids writing there.
   - *A Claude Code plugin*: user-scoped, so teammates who clone the project do not get the
     command, and the engine that writes files would still have to be installed separately.
   The path `~/.agent-forge/bin/agent-forge` is the same for every user and OS, so the skill
   committed to the project works for the whole team.
3. **The entry point is a managed capability.** `agent-forge setup [PATH]` (run by the
   installer) plans, approves and applies only `forge.skill.agent-forge-upgrade`, so it is
   recorded in `.agent-forge/managed.json` and `status`, `remove` and `rollback` apply to it.
   Running the installer in the project is the user's consent; the approval is recorded as
   `agent-forge setup`. Other managed capabilities are never touched by `setup` (`upgrade`
   now honours `excluded_ids`).
4. **The skill is user-invoked** (`disable-model-invocation`, Codex
   `allow_implicit_invocation: false`): no always-loaded context (ADR-0003). Its
   `allowed-tools` pre-approve only read-only subcommands and `forge --dry-run`; a write
   needs the user's yes in the conversation and Claude Code's permission prompt. The agent
   talks to the catalog only through the CLI, so it never needs to read outside the project.
5. **Installer source:** the GitHub archive of `AGENT_FORGE_REF` (default `main`);
   `AGENT_FORGE_SOURCE` points at another pip-installable source (a local checkout for tests).
   `init` drops the bytecode pip compiles inside the packaged seed.

## Invariants kept

Agent Forge remains the only writer into the project, through `apply` and `rollback`.
Nothing is written under `~/.claude` or `~/.codex`, PATH is not changed, no upstream
installer runs. The LLM ranks and explains; plans, policy and approvals decide.

## Out of scope

PyPI publishing and signed releases (pin with `AGENT_FORGE_REF=<tag>` until then); Codex
custom prompts (`~/.codex/prompts` is user-global); uninstall automation (delete
`~/.agent-forge`).
