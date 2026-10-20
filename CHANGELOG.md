# Changelog

## Unreleased

### Production hardening (ADR-0005; audit and gates in docs/engineering-roadmap.md)

Security and integrity
- Approvals are recorded in the workspace (`state/approvals/`); apply refuses a plan whose
  digest differs from the recorded one, so a hand-edited and re-hashed plan needs a new
  `approve`.
- Plans bind the effective policy (`policy_digest`) and expire after 7 days (`expires_at`);
  the registry digest now covers `registry/policies/`. An invalid project `policy.yaml` fails
  closed instead of being ignored.
- Writes create directories one at a time and re-check the full path right before the
  rename; `.git`, case/Unicode aliases of existing entries, `CONIN$`/`CONOUT$` and superscript
  device names are refused; `managed.json` paths get the full path validation; backup
  references are validated; scanner reads are bounded even if a file grows after the walk.
- Content-safety scan of curated assets in `validate` (pipe-to-shell, broad deletes, sudo,
  global config writes, embedded credentials, instruction overrides); findings are errors
  unless acknowledged with a reason in the manifest.
- Capabilities whose assets no longer match their pinned digest are rejected at plan time
  (`integrity_mismatch`). `source.revision` must be a commit SHA. `review.risk_rationale` is
  required above low risk. New `revoked` status and `replaced_by`; installed deprecated or
  revoked capabilities are reported by `validate`.
- Audit log redacts credential-looking values. Unknown `schema_version`s are refused.

Recovery
- Per-project exclusive lock around apply and rollback (stale locks of dead processes are
  taken over).
- Every operation is journaled (before hash, exact backup hash, intended hash) before its
  write. Rollback now handles interrupted (`in_progress`), `failed` and `partial`
  transactions, resolving journaled operations from what is on disk; a failed rollback marks
  the original `recovery_required` and can be resumed. Backups are restored only when their
  bytes match.
- If saving the failure record fails, the original error is still reported.
- `doctor`, `status` and `validate` report unfinished transactions with the rollback command.

Quality and operations
- `examples/` (Java/Spring, Go/Gin, Next.js, FastAPI, ASP.NET Core, mixed monorepo) with
  reviewed expectations; `scripts/matching_report.py` measures precision/recall; CI gate.
- Scanner: nested manifests (monorepos), Maven/Gradle/Spring/Quarkus/Micronaut, Go
  frameworks, .NET/ASP.NET Core, Rust frameworks, Rails, Laravel/Symfony, build/test commands
  per subproject, Makefile lint/format/build; low-confidence detections become warnings;
  `.agent-forge/profile.yaml` confirms or rules out detections.
- Adapter conformance suite; adapters own the path → platform mapping.
- New `agent-forge impact <id>`; CI matrix (Windows/Linux/macOS × 3.11/3.14), installer
  smoke tests, pip-audit, Dependabot; `export_schemas.py --check`; every exit code tested;
  version single-sourced from `agent_forge/__init__.py`.
- Docs: `product-vision.md` (the blueprint, as north star), `engineering-roadmap.md`
  (evidence audit, backlog, release gates), `policy.md`, `operations.md`, `evaluation.md`,
  ADR-0005, `SECURITY.md`, `CONTRIBUTING.md`; security doc states per-file atomicity and the
  runtime boundary.

### Fixed (hardening)
- Codex adapter listed `AGENTS.override.md` as a shared file it can never write.

### Changed (ADR-0004: install from the project root)
- New entry point: run `install.ps1` (`irm … | iex`) or `install.sh` (`curl … | bash`) in a
  project root. It installs or updates Agent Forge in `~/.agent-forge` (venv, launchers in
  `bin/`, workspace) and adds `/agent-forge-upgrade` to the project; the agent there reviews
  the project and drives Agent Forge. README rewritten around this flow.
- `forge.skill.agent-forge-upgrade` 2.0.0: user-invoked (no always-loaded context), works on
  the current directory, calls `~/.agent-forge/bin/agent-forge`, pre-approves only read-only
  commands and `forge --dry-run`, weighs `context_chars`; also shipped for Codex.

### Added
- `agent-forge setup [PATH]`: plans, approves and applies only the entry skill; tracked in
  `managed.json` like any install.

### Fixed
- `upgrade` (and `forge`'s upgrade step) ignored `--exclude`.
- `init` copied the bytecode pip compiles inside an installed package's seed registry into the
  workspace, which then failed planning ("not UTF-8 text") and integrity checks.

### Added (ADR-0003: context load, skill calls)
- Plans report each capability's always-loaded context (`ctx` column, `context_chars` in
  JSON) and the total: skill/agent descriptions (user-invoked skills cost none), unscoped
  rules, CLAUDE.md/AGENTS.md sections. Policy `max_context_chars` makes anything above it
  require an explicit request.
- `validate`: a curated skill that calls another skill through the Skill tool must ship it in
  its own capability or its dependencies, and the called skill must be model-invoked.
- `scripts/curate.py`: exact-text `replacements` for adapted items; a passage missing upstream
  stops the run instead of being skipped.
- `forge.hook.guard-dangerous-git` (opt-in `--want git-guard`): PreToolUse hook blocking
  force-push, remote ref deletion, `reset --hard`, `clean -f`, `branch -D`, wholesale
  `checkout`/`restore` and `stash drop/clear`. Stdlib Python, fails open.
- `docs/rejections/`: one record per rejected or deferred upstream item (replaces the table
  in `docs/source-curation.md`); `agent-forge-scout` 1.1.0 reads it and ADR-0003.

### Added (source: mattpocock/skills)
- New source `mattpocock` (mattpocock/skills, tag v1.3.1 @ 24fe0ef7).
- `mattpocock.diagnosing-bugs` (always), `mattpocock.grilling`, `mattpocock.domain-modeling`,
  `mattpocock.codebase-design`, `mattpocock.grill-with-docs` (user-invoked, depends on
  grilling + domain-modeling), `mattpocock.writing-for-agents`; verbatim, both platforms.
- `mattpocock.two-axis-review` (adapted from `code-review`: renamed to avoid harness
  built-ins, no setup-skill precondition) and `mattpocock.tdd` (adapted, depends on
  codebase-design, conflicts with `ecc.tdd-workflow`), both tag-only.
- Not curated: the setup-matt-pocock-skills chain, package-installing misc skills, `pr`
  (licence of its humanlayer source unverified) — see `docs/rejections/`.

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
