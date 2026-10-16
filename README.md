# Agent Forge

Local-first, approval-first platform that scans a software project, recommends curated
AI-agent capabilities (skills, rules, agents, instruction sections) from reviewed upstream
sources, and installs them inside a recoverable transaction — without ever rewriting your
`CLAUDE.md`, running upstream installers, or touching `~/.claude` / `~/.codex`.

```
SCAN → ASSIGN → PLAN → DIFF → APPROVE → APPLY → VALIDATE   (→ ROLLBACK)
```

- **Source-agnostic:** capabilities come from a versioned registry (`registry/capabilities/`),
  each with provenance (repo + commit SHA + paths), license, applicability rules, equivalence
  signals, conflicts, risk. Initial sources: REA, Everything Claude Code, UI UX Pro Max.
- **Project-aware:** evidence-based detection of languages, frameworks, project type and
  existing agent setup; nothing is installed just because it exists.
- **Explainable:** every recommendation and rejection carries reasons; scores only rank.
- **Safe:** path/symlink/junction boundaries, hash-bound approvals, atomic writes, backups,
  drift detection, conflict-aware rollback.
- **Platforms:** Claude Code (skills, rules, agents, CLAUDE.md sections) and OpenAI Codex
  (skills, AGENTS.md sections), verified against the official docs on 2026-10-16.

## Quick start

```bash
python -m venv .venv && .venv/Scripts/activate      # or source .venv/bin/activate
pip install -e ".[dev]"
agent-forge init
agent-forge forge "../my project"                 # one shot: scan → plan → diff → confirm → apply → validate
agent-forge forge "../my project" --dry-run       # look first, write nothing
```

Or step by step: `scan` → `assign --want security` → `diff plan-…` → `approve plan-… --shared-files`
→ `apply plan-…` → `validate`. Only capabilities that fit the project are selected: a backend
service never receives UI/UX material, a React app does.

Three change classes need their own explicit approval, on `approve` or `forge`:
`--shared-files` (sections in CLAUDE.md/AGENTS.md), `--hooks` (entries merged into
`.claude/settings.json`; they run commands) and `--mcp` (servers merged into `.mcp.json`;
they launch processes). Merges preserve everything else in those files and roll back
entry by entry.

Docs: [getting started](docs/getting-started.md) · [CLI reference](docs/cli-reference.md) ·
[architecture](docs/architecture.md) · [capability model](docs/capability-model.md) ·
[source curation](docs/source-curation.md) · [adapters](docs/adapters.md) ·
[upgrade lifecycle](docs/upgrade-lifecycle.md) · [security](docs/security.md) ·
[maintenance](docs/maintenance.md) · [troubleshooting](docs/troubleshooting.md) ·
[discovery report](docs/discovery-report.md) · [ADR-0001](docs/adr/0001-architecture-decisions.md)

Status and known limitations: [WORKSPACE_STATUS.md](WORKSPACE_STATUS.md).

## Development

```bash
.venv/Scripts/ruff check src tests scripts && .venv/Scripts/python -m pytest -q
python scripts/export_schemas.py     # after model changes
python scripts/curate.py             # re-copy curated assets from pinned checkouts
```

License: MIT (see `LICENSE`). Curated upstream content keeps its own notices
(`LICENSE-*.txt` next to installed files).
