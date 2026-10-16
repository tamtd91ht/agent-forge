# Workspace status

Updated: 2026-10-16. Version 0.1.0. Git repository initialised by the build session; **no
commits made** (left for the maintainer to review and commit).

## Phase checklist

| Phase | State | Evidence |
|---|---|---|
| A — Discovery & design | done | `docs/discovery-report.md`, `docs/adr/0001-architecture-decisions.md`, platform conventions verified against official docs |
| B — Python foundation | done | `pyproject.toml` (hatchling), `src/agent_forge` (~6.6k lines), schemas exported to `registry/schema/`, `agent-forge --help` works |
| C — Read-only MVP | done | `init`, `sources list/clone/sync`, `catalog`, `scan`, `assign`, `upgrade` (plan only), `diff`, `plans`; plus `forge` (one-shot, still approval-first) |
| D — Curation | done (initial) | 20 capabilities in `registry/capabilities/` (skills, rules, agents, instruction, 4 hooks, 2 MCP servers) with provenance SHAs; `docs/source-curation.md` lists inclusions and exclusions |
| E — Adapters | done | Claude Code (skill/rule/agent/instruction), Codex (skill/instruction); unsupported kinds reported |
| F — Apply engine | done | `approve`, `apply`, `validate`, `status`, `rollback`, `reindex`; transactions + backups |
| G — End-to-end verification | done | `tests/e2e/test_cli.py::test_full_cli_lifecycle` and a manual run on `…/af-smoke/my app ünïcode` (Next.js fixture): assign → diff → approve → apply → validate → user edit → rollback refused → `--partial` kept the edit and removed everything else |
| H — Handover | done | README + 11 docs, this file, CHANGELOG |

## Test results (this environment: Windows 11, Python 3.14.3)

```
ruff check src tests scripts   -> All checks passed
pytest -q                      -> 127 passed, 2 skipped (symlink creation needs privilege;
                                  Windows junction tests run and pass)
agent-forge validate           -> 15 checks, 0 errors, 0 warnings (provenance verified)
```

## Definition-of-done check

| Requirement | Status |
|---|---|
| installs locally as a Python CLI; `--help` works | yes |
| `init` safe to rerun | yes (idempotent, tested) |
| registry schema validated | yes (Pydantic + exported JSON Schema; cross-checks in `validate`) |
| source metadata and provenance recorded | yes (`sources.yaml`, `state/cache/sources-state.json`, manifest SHAs verified by `git cat-file`) |
| scanner inspects without modifying | yes (mtime snapshot test) |
| Claude Code and Codex configs recognised | yes |
| recommendations explainable | yes (reasons + score breakdown + rejection categories) |
| unsupported capabilities rejected/marked | yes (`needs_runtime`, `unsupported_platform`, `reference_only`) |
| assign/upgrade generate plans only | yes |
| diff accurate | yes (projected content = what apply writes; verified by after-hash check) |
| apply requires valid approval | yes (digest-bound; `--yes` cannot bypass) |
| user-owned files protected | yes (collision rejection, section markers, drift detection) |
| stale plans rejected | yes (file hashes + registry digest + plan digest) |
| validation reports actual results | yes |
| rollback detects independent modifications | yes (strict refusal, `--partial`, section-aware) |
| security tests cover filesystem boundaries | yes (traversal, absolute, reserved names, junctions, fuzzed paths; symlink tests skip here) |
| tests run in the available environment | yes |
| docs match behaviour | yes (written from the implemented commands) |
| no unapproved global configuration changes | yes (nothing outside the workspace and temp fixtures was written) |

## Governance layer (ADR-0002, 2026-10-16)

- Policy engine (`policy/`), structured `grants`, integrity pins (20/20), `signed_off_by`
  (0/20 — human sign-off still pending), audit log, `remove` / `drift` / `repair` /
  `policy` / `audit` / `doctor` commands. Runtime plane and evaluation engine deliberately
  not built; see `docs/adr/0002-upgrade-roadmap.md`.

## Known limitations / incomplete

- Hooks and MCP servers are installable for Claude Code only, each behind its own approval
  class (`--hooks`, `--mcp`; ADR D13). Codex hooks/MCP (`.codex/*`) are not managed.
- Codex: rules and subagents are reported as requiring adaptation, not installed (ADR D10).
- ECC per-language rule sets (`rules/<lang>/`) and `security-reviewer` agent are not yet
  curated (candidates for v0.2).
- `validate` lists but does not run project test commands.
- Symlink-specific tests need a symlink-capable environment; junctions are covered on Windows.
- Human sign-off on curation rationale is pending (manifests say so in `review.reviewer`).
- The `uiux.full-toolkit` and `rea.reverse-engineer-anything` entries are recommendations with
  install hints only; their runtimes were not exercised.

## Suggested next steps

1. Commit this initial state; set up CI running ruff + pytest on Linux (symlink tests will run).
2. v0.2 curation: ECC language rule packs as path-scoped `.claude/rules` capabilities,
   `ecc.agent.security-reviewer` depending on `ecc.security-review`.
3. Optional AI-assisted analysis mode (`assign --explain-with-llm`) layered on top of the
   deterministic matcher, with an explicit data-flow note in `docs/security.md`.
4. A `bundles/` concept (e.g. `bundle.frontend-baseline`) once more capabilities exist.
