# Changelog

## Unreleased

### Fixed
- Matching: a dependency pulled in because it was "not applicable" skipped policy, so a
  policy-denied capability could enter a plan as a dependency. It is now policy-checked.
- Matching: a recommended capability could depend on one left optional (risk/permissions),
  installing it without its dependency. The dependant is now optional too, unless it was
  requested, in which case the dependency is promoted (transitively) with the reason shown.
- Planner: a capability whose dependency was left out for a missing approval class
  (`--shared-files` / `--hooks` / `--mcp`) was still planned without it; it is now reported as
  `needs_approval` too, naming the dependency and the flag.
- `ecc.rules.common` 1.1.0 (adapted): no longer tells the agent to use ECC subagents this
  registry does not install, links to the excluded `git-workflow.md` / `agents.md`, or a
  mandatory gh search / Context7 / Exa research step.

### Changed
- Plan tables fit an 80-column terminal: `adds` groups files per folder, `why` leaves the
  score breakdown to `--json`; `forge` hides already-installed rows and folds not-applicable
  ones into one line; `forge --dry-run` says to re-run without the flag; `upgrade` prints the
  next command.
- README rewritten as a user guide: workspace vs project, preview → install → open in
  Claude Code, the three permission flags, how to read "not selected", everyday tasks.

### Added
- `forge.skill.agent-forge-upgrade`: a Claude Code skill (`/agent-forge-upgrade <project>`)
  that reviews the project (CLAUDE.md, rules, skills, tooling) and drives Agent Forge with
  `--request/--exclude/--want`, dry-run first, apply only on the user's yes. Shipped in the
  registry (opt-in) and in the repo's own `.claude/skills/`.
- `forge.skill.agent-forge-scout`: a Claude Code skill (`/agent-forge-scout <github url>`)
  that reviews a public repository for Agent Forge: what is impressive, which parts could be
  curated or turned into engine upgrades per the ADRs, licence/safety check, verdict. Read-only.
- `init --refresh-registry`: update a workspace's registry copy from the packaged seed after
  pulling/reinstalling Agent Forge (own capabilities kept).
- `validate`: relative links in curated markdown assets must resolve inside `assets/`
  (code blocks ignored).

### Added (source: andrej-karpathy-skills)
- New source `karpathy` (multica-ai/andrej-karpathy-skills @ 2c606141).
- `karpathy.principles`: always-on section (think before coding, simplicity first,
  surgical changes, goal-driven execution) in `CLAUDE.md` / `AGENTS.md`; skipped when the
  project instructions already contain them.
- `karpathy.guidelines`: the same principles as an on-demand skill, `--want guidelines-skill`;
  conflicts with the section, explicit request wins.

### Added (governance, from ADR-0002)
- Policy engine: layered `default.yaml` → workspace `policy.yaml` → project
  `.agent-forge/policy.yaml`, strictest wins; verdicts allow / require_request / deny
  evaluated before scoring; `agent-forge policy [PATH]`.
- Structured runtime grants on capabilities (`grants`, kind-derived defaults) feeding policy.
- Integrity pins (`integrity.assets_sha256`, `scripts/pin_integrity.py`) checked by `validate`;
  `review.signed_off_by` and policy `require_signoff`.
- `remove PATH ID...`, `drift PATH`, `repair PATH --strategy restore|unmanage` (all plan-based).
- Append-only audit log `state/audit.jsonl` and `agent-forge audit`; transactions record
  registry digest and profile fingerprint.
- `agent-forge doctor`.

### Fixed
- A dependency rejected by policy or any other hard rule is no longer pulled back in by a
  dependant.

### Added
- `agent-forge forge PATH`: one-shot scan → upgrade managed → add recommended → diff →
  single confirmation → approve + apply → validate. `--dry-run`, `--show-diff`,
  `--shared-files`, `--hooks`, `--mcp`, `--yes`, `--json`.
- Hook and MCP capabilities with their own approval classes (`approve --hooks`,
  `approve --mcp`): JSON fragments merged into `.claude/settings.json` / `.mcp.json`,
  other entries preserved, MCP name conflicts refused, entry-aware rollback and upgrade,
  `validate` checks merged entries. Plans built for `forge` without a granted class never
  contain that class (reported as `needs_approval`).
- Six curated entries: `forge.hook.guard-secrets-python`, `forge.hook.guard-secrets-node`,
  `forge.hook.python-ruff-format`, `forge.hook.node-prettier-format`, `mcp.context7`,
  `mcp.playwright`.
- Operations on the same file are chained in plan order (planner, pre-flight, diff), so two
  capabilities can merge into one settings file.

### Changed
- Matching evaluates applicability *before* runtime requirements, so native capabilities
  (REA, full UI UX Pro Max toolkit) are hinted only for projects they fit; a backend-only
  project no longer sees UI/UX runtime suggestions.
- `.gitattributes` forces LF so registry digests and managed-file hashes match across OSes.

## 0.1.0 — 2026-10-16

Initial release (built from the Agent Forge master prompt).

### Added
- Python package `agent_forge` with Typer CLI: `init`, `sources list|clone|sync`,
  `catalog [show]`, `scan`, `assign`, `upgrade`, `plans`, `diff`, `approve`, `apply`,
  `validate`, `status`, `rollback`, `reindex`; stable exit codes and `--json` output.
- Capability registry model (Pydantic, `extra=forbid`) with exported JSON Schemas; lifecycle
  states; install strategies `file_copy`, `section_merge`, `native_plugin`, `reference_only`.
- Source manager for approved git repositories (clone, status, fetch/compare, explicit
  update) and provenance verification against pinned commit SHAs.
- Read-only scanner: bounded walker that never follows symlinks or Windows junctions, skips
  secret-looking files, evidence-based language/framework/project-type detection, agent
  inventory for Claude Code and Codex, managed-manifest validation with drift detection.
- Deterministic matching engine (hard rules → scoring) with equivalence detection,
  destination-collision and declared-conflict handling, dependency pull-in, explanations.
- Planner producing hash-bound file operations and unified diffs; approval bound to the
  plan digest; shared-file operations require `approve --shared-files`.
- Transactional apply with backups, atomic writes, read-back verification and sealed
  transaction records; conflict-aware rollback (strict, `--partial`, section-aware).
- Validation of registry, provenance, managed installs, config syntax, duplicates and
  transaction integrity.
- Adapters for Claude Code (skills, rules, agents, CLAUDE.md sections) and OpenAI Codex
  (skills, AGENTS.md sections), conventions verified on 2026-10-16.
- Initial curated catalog: 10 from ECC, 2 from UI UX Pro Max, 1 from REA, 1 workspace-authored.
- Test suite (unit, security incl. hypothesis fuzzing and junction tests, integration, e2e).
- Documentation set under `docs/`, ADR-0001, discovery report, workspace status.
