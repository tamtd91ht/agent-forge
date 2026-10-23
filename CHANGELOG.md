# Changelog

## Unreleased

Content for what a project *does*, not only what it is built with (ADR-0010).

### Added
- **Traits** (`docs/traits.md`): the scanner detects domain characteristics with evidence and
  confidence from sampled source files (`multi_tenant`, `money`, `pii`, `telephony`) or from a
  detected broker (`event_driven`); `scan` prints them, `.agent-forge/profile.yaml` confirms
  (`traits:`) or rules them out (`ignore:`), and `applicability.traits` gates capabilities on
  them (`not_applicable` with the trait named when absent; `stack_mismatch` in `decisions
  verify`). A trait appearing or disappearing stales a plan; projects without traits keep
  their fingerprints. RabbitMQ is now recorded as an integration across ecosystems.
- First trait-gated capabilities, generalised from a production multi-tenant platform's
  critical rules: `forge.skill.tenant-isolation` (`multi_tenant`) and
  `forge.skill.money-safety` (`money`), on-demand skills for all four platforms.
- The `event_driven` pack, generalised from the same platform's Kafka and RabbitMQ rules:
  `forge.skill.event-consumer-safety` (acknowledge after commit, dedup, failure classes,
  bounded retries, owned DLQ, ordering per key, commit-then-close) and
  `forge.skill.event-contract` (outbox, envelope, business keys, one type per topic with a
  version, compatible evolution, reuse-before-create and retirement, producer-built payloads,
  transport table); proposed when a Kafka, RabbitMQ or Celery dependency is detected.
- The `pii` pack: `forge.skill.pii-protection` (tiers recorded with the schema, encryption at
  rest with a key-version prefix, keyed hash and opaque blind index for search, display
  pattern per field, nothing in clear in logs / events / caches / exports, rotation with
  re-encryption, erasure that scrubs in place and propagates to every copy).
- Trait sampling spreads the 300 sampled source files round-robin across top-level
  directories, so a large first directory cannot hide tenant or money code elsewhere.
- `forge.skill.webhook-signature-verification` (on request, or when the entry skill finds
  inbound callback endpoints):
  verify over raw bytes before parsing, constant-time compare per language, one secret per
  provider with rotation, replay controls, body-free logging, compensating controls.
- `forge.hook.changelog-gate` (opt-in): a feat / fix commit with no CHANGELOG.md staged is
  blocked before it exists; `[skip-changelog]` bypasses.
- `agent-forge import PATH [--kind] [--path] [--yes]` (ADR-0011): hand-written skills,
  subagents, rules and commands are adopted in place as `local.<kind>.<name>` entries of
  `managed.json`, through an ordinary plan whose only operation is the manifest write.
  Nothing is copied or rewritten. `upgrade` / `sync` / `restore` skip or refuse local entries,
  `status` shows `local`, `check` never fails on the team's own edits, re-running `import`
  refreshes the hashes, `remove` and `repair --strategy unmanage` work on them. The scanner
  now hashes managed files on normalised text, so a CRLF file is not drift.
- `lint` check `hook_output`: a hook script that writes to stdout only (print, echo,
  console.log without stderr or a hookSpecificOutput document) is reported, since the
  model never sees stdout. `examples/lint-messy` carries one.
- `forge.hook.guard-secret-literals`: PreToolUse guard that refuses a credential *value* in
  the text about to be written (complements the by-name `guard-secrets-*` hooks); opt-in.
- `agent-forge lint` gains four warning checks: `deadref` (a skill / agent / command / rule or
  `@import` that does not exist), `index_drift` (an instruction claims more skills, agents,
  rules, commands or hooks than the disk holds), `overlap` (two skills or two agents whose
  descriptions are too alike for the model to choose), `schema` (a skill or agent without
  `name` / `description`). `examples/lint-messy` carries one of each, reviewed.
- `docs/contributing-capabilities.md#writing-a-hook`: the stderr / exit-code, Stop-hook,
  marker-confirmation, fail-open and Bash-bypass lessons every hook must follow.

- New source `superpowers` (obra/superpowers, MIT, pinned to v7.0.1). Curated verbatim:
  `superpowers.verification-before-completion` (tag `verification`; always-on only after
  eval evidence) and `superpowers.receiving-code-review` (tag `code-review`). Bootstrap
  hook, brainstorming companion and session diagnosis rejected
  (`docs/rejections/superpowers-bootstrap-and-runtime.md`).
- `validate` (ADR-0012) warns when a curated `SKILL.md` reaches 20,000 bytes (Claude Code's
  post-compaction cut) and errors on plugin-namespaced skill references (`superpowers:x`)
  that a project install cannot resolve.
- **Field-test fixes (2026-10-23).** A field test on a JVM / Next.js monorepo (Spring Boot,
  Vert.x, Kafka, MongoDB, Elasticsearch, Kubernetes, Terraform) measured scanner recall
  10/13 and one false positive; the misses and the false positive are closed:
  - the scanner records `vertx` (an `io.vertx` build dependency; a backend framework),
    `elasticsearch` (Java API client, Spring Data Elasticsearch, the REST client,
    `@elastic/elasticsearch`, the Python and Go clients, OpenSearch forks), `jpa`
    (`spring-boot-starter-data-jpa`, `hibernate-core`, `jakarta.persistence`, Kotlin
    `plugin.jpa`; never `org.hibernate.validator`) and `kubernetes` (a YAML document with
    `apiVersion:` and a workload / networking `kind:` anywhere in the tree, a Helm chart or a
    kustomization; pipeline YAML, compose files and bare directory names are not evidence).
    Words in README, docs or comments were never dependencies and a test now proves it.
  - `examples/jvm-platform`: the field-test shape as a reviewed fixture (13/13 indicators).
  - `forge.skill.mongodb-patterns` (`mongodb`), `forge.skill.elasticsearch-patterns`
    (`elasticsearch`) and `forge.skill.vertx-patterns` (`vertx`): on-demand stack skills
    with identical Codex copies, proposed only when the integration is a real dependency.
  - `forge.skill.backend-review`: the backend reviewer's checklist as a skill for Codex,
    Copilot and Gemini, whose adapters install skills but not agents; the body is generated
    from the agent asset and a test keeps the two identical. On Claude Code the subagent is
    installed instead, so no platform gets both.
- **Self-update before planning.** An installer install carries the catalog of the release
  it installed, so a project upgraded at some earlier time was compared with that catalog,
  never with a newer one. `upgrade` and a real `forge` run now ask api.github.com for the
  latest release first; when it is newer than `~/.agent-forge/VERSION` and the command was
  started by the installer's launcher, the engine leaves the tag in `~/.agent-forge/UPDATE_TO`
  and exits 16, and the launcher (v2, regenerated by the installer) runs the same verified
  installer (checksum + Sigstore, ADR-0004) for that tag and re-runs the command once with
  `--no-self-update`. The engine never reinstalls over its own running files (a field check
  on Windows showed that breaks the venv). Nothing happens when current, offline (a note
  says so), for pipx / uvx / checkout installs, on `--dry-run` (reported only), without the
  launcher (reported only), or with `--no-self-update` / `AGENT_FORGE_NO_SELF_UPDATE=1`.
  New command `agent-forge self-update [--check] [--release]`; the entry skill (2.5.0) runs
  `self-update --check` first and tells the user when an update is waiting. Installs made
  before this release have the old launcher: run the install command once more by hand.
- **Evidence level per recommendation.** Every selected capability carries `confidence`:
  `confirmed` (each matched condition rests on a detection at >= 0.8, or the capability
  applies everywhere), `probable` (a weaker detection, e.g. a source-token trait at 0.6) or
  `needs_confirmation` (selected by `--want` / `--request` / policy or as a dependency, not
  by the project). Reasons now cite the evidence (`framework: spring (pom.xml, 0.85)`), the
  plan table has an `evidence` column, `--json` carries the field. Plans approved before this
  change no longer verify (their digest predates the field) and must be re-planned.

### Changed
- `ecc.jpa-patterns` 1.1.0 is gated on the `jpa` integration instead of `spring` (a Spring
  Boot service on JDBC, R2DBC or MongoDB no longer gets JPA patterns); `ecc.kubernetes-patterns`
  1.1.0 is gated on the `kubernetes` detection instead of tag-only. `examples/java-spring`
  expectations reviewed accordingly.
- An `unsupported_platform` rejection says when the platform's adapter does not install the
  capability's kind (`its adapter does not install kind 'agent'`), so a reader looks for a
  counterpart in another kind rather than for a curation gap.
- Frontmatter that is not valid YAML (a description containing `Triggered by: …`) is read
  leniently as `key: value` lines, as the tools do; `lint` now counts such skills' context
  instead of reporting 0, and no longer calls them undiscoverable.
- The entry skill (2.3.0) reads `traits` from `scan --json`, treats a trait-gated capability
  on a project without the trait as `stack_mismatch`, and asks the user to confirm a missed
  trait in `profile.yaml` instead of asserting it.
- Nine ECC skills over the 20,000-byte post-compaction cut are optimised, not shortened
  (1.1.0, `adapted`): situational sections move verbatim into `references/` with a
  "read when" pointer, anchors are re-pointed, nothing is removed (`Split` in
  `scripts/curate.py`, ADR-0012). Every `SKILL.md` is now under 17,500 bytes.
- `ecc.verification-loop`'s `verif` equivalence pattern no longer matches
  `verification-before-completion`.

## 0.4.0 — 2026-10-21

The catalog serves every detected stack, and review becomes a first-class capability.

### Added
- **89 stack-specific ECC capabilities**, so a project is served in its own stack instead of
  only by the generic TypeScript-flavoured skills: 21 path-scoped rule packs
  (`ecc.rules.<language|framework>`, 0 always-loaded context, `hooks.md` excluded) and 68
  framework / language / data skills (Spring Boot, Quarkus, JPA, Kotlin, Ktor, Go, NestJS,
  React, Next.js, Vue, Nuxt, Vite, Prisma, Playwright, React Native, Python, FastAPI, Django,
  Celery, Rust, .NET, Laravel, Rails, Swift, Dart/Flutter, C++, Perl, Redis, PostgreSQL,
  MySQL, migrations, Kubernetes, deployment, API design, accessibility). Framework-specific
  TDD / security / verification skills conflict with and outrank the generic ones, so a Spring
  project gets `springboot-tdd`, not `ecc.tdd-workflow`. `docs/source-curation.md` has the map;
  `docker-patterns` and `angular-developer` are rejected with reasons.
- Scanner records integrations as frameworks from dependency manifests across ecosystems
  (`redis`, `kafka`, `postgres`, `mysql`, `mongodb`, `prisma`, `vite`, `celery`, `ktor`,
  `exposed`; `docker` from a Dockerfile / compose file), so data-store and tooling skills apply
  only when the dependency is really there.
- `forge.skill.view-data-loading` (workspace-authored): request discipline for a web or
  mobile view - request map (first paint vs enhancement vs on interaction), one request per
  resource, independent requests in parallel, nothing secondary blocking the first render,
  fetch on need, dedupe / cache / cancel. Applies to frontend, fullstack and mobile-or-desktop
  projects, so `/agent-forge-upgrade` proposes it whenever a web part is detected.
- **Review subagents** `forge.agent.backend-reviewer` (security, money and transactions, data
  integrity, readiness for traffic, API contract, clarity) and `forge.agent.frontend-reviewer`
  (backend contract, view data loading, state, client security, performance, resilience,
  clarity): read-only, stack-neutral, one per detected part. The entry skill (2.2.0) gains a
  review-coverage step: it lists the project's own reviewer subagents and decides ADD / SKIP
  covered / ASK (missing dimensions) instead of adding a second reviewer blindly; the
  capabilities declare existing reviewers as equivalents.
- `scripts/curate.py`: `rewrite_links` (relative links to sibling skills become names) and
  `frozen` items (hand-adapted assets such as `ecc.rules.common` are never overwritten by a
  re-run).

## 0.3.2 — 2026-10-21

Parts 2 and 3 of the external review's fix list (`docs/history/agent-forge-fix-v0.3.1.md`).

### Added
- `check` gates on decision records: a SKIP / REMOVE that no longer verifies against the
  project (basis disappeared) and an applied plan whose `decisions_digest` matches no
  committed record are failures (`decisions/gate.py`).
- `scripts/decision_report.py` + `examples/lint-messy/expected_decisions.json`: golden
  decisions for the trap fixture, compared cell by cell; `--run` executes the skill with
  `claude -p` / `codex exec` on a fixture copy (never in CI). The entry skill's own context
  budget is recorded in its manifest and pinned by `tests/unit/test_entry_skill_budget.py`
  (0 always-on, < 16k on demand).

### Changed
- Pre-flight problems are data: `Problem(code, message, op_id, path)` with a `ProblemCode`
  enum; the code picks the exit code (stale 7 > approval 8 > apply 10) instead of substring
  matching on messages. Table in `docs/cli-reference.md`.
- `examples/lint-messy`: a deliberately untidy fixture with reviewed `expected_lint.json`
  (duplicate rules, pipe-to-shell hook, disabled MCP server; a contradicting rule and a
  `${API_KEY}` placeholder that must not be flagged). Also the trap fixture for golden decisions.
- `agent_forge.cli` is a package (one module per command group, none above 600 lines);
  `agent_forge.cli:main` and `from agent_forge.cli import app` are unchanged. The
  `--decisions` wiring moved from the CLI into `decisions/plan_input.py`.

## 0.3.1 — 2026-10-21

### Fixed
- **v0.2.0–v0.3.0 could not be installed on Linux/macOS.** `sha256_tree` sorted `Path`
  objects, and `WindowsPath` compares case-insensitively while `PosixPath` does not, so any
  asset tree with an upper-case file next to a lower-case one (`LICENSE-*.txt`, `SKILL.md`)
  hashed differently per OS. 12 of 34 pins, including `forge.skill.agent-forge-upgrade`,
  were computed on Windows and never matched on POSIX: `validate` failed, the installer
  rejected the entry skill, the `v0.3.0` release job failed. The earlier CRLF explanation
  was wrong. Files are now visited in code-point order of their POSIX relative path; all
  pins re-computed; `tests/unit/test_util_hashing.py` pins a known digest that CI checks on
  Windows, Linux and macOS. The registry digest in plans changes too: plans approved before
  the upgrade are reported stale and must be re-planned.
- CI `registry-integrity` runs on all three OS; the docs site built with three broken
  relative links to files outside `docs/` (strict mode), now absolute links.
- Root cause and fix list from an external review: `docs/history/agent-forge-fix-v0.3.1.md`.

## 0.3.0 — 2026-10-21

### The decision layer (ADR-0007; tracked checklist in docs/roadmap-decision-layer.md)
- **Decision records.** `/agent-forge-upgrade` 2.1.0 assesses every capability on a fixed,
  negative-first rubric (grounds to skip with their evidence, then the gap, then cost / risk /
  evidence from the catalog) and writes `.agent-forge/decisions/<plan-id>.json`
  (`registry/schema/decisions.schema.json`). It is the one file the skill writes.
- `agent-forge decisions verify`: cited paths must exist inside the project, quotes must be
  real substrings, `context_chars` / `evidence` must match the catalog, every ground must
  carry its evidence, policy wins. An unprovable SKIP / REMOVE becomes ASK; exit 12 when any
  check failed. `decisions diff` (only changed verdicts, old and new reason),
  `decisions explain PATH ID`, `decisions report DIR...` (organisation-wide capability ×
  verdict × ground with threshold suggestions).
- `forge --decisions FILE`: verifies, turns effective SKIP / REMOVE into exclusions and
  effective ADD into requests, refuses a real run while an ASK is unanswered (exit 6;
  `--exclude` / `--request` answer per id), binds the record's digest to the plan
  (`Plan.decisions_digest`, part of the content digest when present). `status` lists what
  is absent by decision; `drift` reports a decision whose cited file or line disappeared.
- **Policy `required` / `forbidden`.** `capabilities.required` ids are always planned when
  installable, cannot be excluded (exit 2) or skipped by the agent, and `check` fails when
  one is missing (`required_missing`). `forbidden` is an alias of `deny`. `policy` shows both.
- **`agent-forge lint PATH`** (no workspace, no catalog, no LLM): always-loaded context per
  file and in total, duplicate paragraphs and near-duplicate rule files, credentials in agent
  files and MCP configs, hooks whose commands trip the content-safety rules, MCP servers
  defined but disabled; `--max-context N` as a CI gate (exit 12). Proposes nothing.
- **Usage log.** `forge.hook.usage-log` (opt-in, Claude Code `PostToolUse` on Skill / Agent)
  appends id, kind, timestamp and a short session id to `.agent-forge/usage.jsonl`, offline;
  `agent-forge usage PATH` and the `unused` hint in `status` read it; the `unused` ground of a
  decision record is verified against it (≥ 14 observed days).
- `doctor`: orphaned locks (dead pid) reported; installed release and verification method
  from `~/.agent-forge/VERSION`; `--check-latest` compares with the newest GitHub Release.
- Docs: ADR-0007 (accepted), ADR-0008 default-catalog criteria (proposed),
  `roadmap-decision-layer.md`, policy and CLI reference, pilots guide (enable the usage log on
  day one), team policy template with `required` / `forbidden` / `max_total_context_chars`.

### Installer and release safety (checklist P0)
- `install.sh` / `install.ps1` install a GitHub Release wheel only after its SHA-256 matches
  the release's `SHA256SUMS`, verify the Sigstore bundle when `cosign` is on PATH (a warning
  otherwise), write `~/.agent-forge/VERSION`, and **never fall back to `main`**: when no
  release can be resolved they stop with exit 1 and the pin hint. `AGENT_FORGE_REF=<branch>`
  installs an unverified archive for development and says so.
- CI: `registry-integrity` job (no CRLF in `registry/`, `pin_integrity.py --check`,
  `validate`) independent of the test suite; the installer job runs `validate` and `doctor`
  on the installed catalog on Windows, Linux and macOS and proves that an unverifiable
  release installs nothing.
- `contributing-capabilities.md`: line-ending rule (`core.autocrlf false`, never pin from
  a CRLF working copy). The `v0.2.0` tag predates the CRLF re-pin and its release never
  published; `v0.3.0` is the first release the installers can resolve.

### Opening up (6-month plan, phase 4)
- **Breaking for automation:** every `--json` command prints JSON envelope v1
  (`{envelope: 1, command, agent_forge, generated_at, ok, data}`); the previous document is
  `data`. `registry/schema/envelope.schema.json`; `tests/e2e/test_json_envelope.py` covers
  every command. The entry skill (`forge.skill.agent-forge-upgrade` 2.0.1) reads `data`.
- Dependency version constraints: `dependencies: ["id >=1.2.0 <2.0.0", "id ^1.0.0"]`;
  `validate` checks the registry version, matching rejects an unsatisfied dependency
  (`dependency_missing`), `validate PATH` checks installed versions.
- `validate` errors when `license.notice_file` is missing from `assets/`.
- `status` prints a deprecation / revocation line with the replacement and the policy link;
  `docs/deprecation-policy.md` (notice periods, who decides).
- Capability submission process: `docs/contributing-capabilities.md`, PR template,
  `.github/CODEOWNERS`, `MAINTAINERS.md` (roster and merge/release rules).
- `docs/registries.md`: a private or public registry in 10 minutes (layered registries).
- Documentation site: `mkdocs.yml` + `docs-site` workflow (GitHub Pages); `docs/index.md`.
- `docs/roadmap-2026h2.md`: the 6-month plan with per-item status and what is left for people.

### Value (6-month plan, phase 3)
- `tools/agent-forge-eval`: opt-in local evaluation harness (ADR-0002). Baseline vs candidate
  (installed by the real engine) on a fixture's task set with `claude -p` / `codex exec`,
  hidden acceptance tests decide, Wilson 95% intervals, verdict improved / no_evidence /
  worse, JSON + Markdown reports under `docs/evaluation/results/`. `--tool scripted` exists
  for harness tests only and is labelled as not a measurement.
- Task sets: five reviewed tasks per example fixture (feature, bugfix, refactor, review,
  docs) in `examples/<name>/tasks/*.yaml`, 30 in total.
- `review.evidence` on capability manifests (date, fixture, tool, runs, tasks, pass rates,
  candidate CI, verdict, report path, who decided); `catalog show` prints the evidence table
  or says the value was not measured. Schema exported.
- Policy `max_total_context_chars`: a plan whose always-loaded context total exceeds the
  budget carries a note and a decision line for the approver.
- `scripts/matching_report.py --corpus DIR --min-precision --min-recall`: reviewed external
  projects (anonymised) and micro-averaged thresholds for CI; aggregate printed.
- No capability has been measured yet; `docs/evaluation.md` records the plan for the five
  core skills and the budget it needs.

### Platforms (6-month plan, phase 2; ADR-0006)
- Adapters for **Cursor** (`.cursor/rules/**/*.mdc`, `.cursor/mcp.json`), **GitHub Copilot**
  (`.github/copilot-instructions.md`, `.github/instructions/*.instructions.md`,
  `.github/skills/<name>/SKILL.md`) and **Gemini CLI** (`GEMINI.md`, `.gemini/skills/<name>/SKILL.md`,
  `.gemini/settings.json` `mcpServers`), each verified against the official pages on 2026-10-20.
- Canonical content + per-adapter rendering: a destination points any platform at the
  canonical (Claude Code format) asset; `PlatformAdapter.render` transpiles it in the planner,
  deterministically, before hashing (Cursor rules/instructions, Copilot rules, Gemini MCP).
  24 curated capabilities gained Cursor / Copilot / Gemini destinations with no new asset files.
  `tests/conformance/test_render.py` gates every adapter and every curated destination.
- Tool version detection: adapters declare `version_command` and the verified range;
  `doctor` shows the detected version; `forge`/`assign`/`upgrade`/`setup` refuse a tool
  outside the range (new exit code 15) and note tools that are absent. Claude Code: ≥ 2.0.0.
- `scripts/watch_docs.py` + weekly `docs-watch` workflow: digests of the verified
  documentation pages (`adapters/docs_hashes.json`); a change opens an issue.
- `validate` checks `.cursor/mcp.json` and `.gemini/settings.json` syntax; the scanner
  attributes `GEMINI.md` and `.github/copilot-instructions.md` to their adapters.

### Team workflow (6-month plan, phase 1)
- `agent-forge check PATH`: read-only CI gate with one exit code (0 / 12) for drift, missing
  or revoked capabilities, invalid `managed.json`, unfinished transactions and config syntax;
  `.github/actions/check` runs it (and optionally `forge --approval-file`) in any repository.
- `agent-forge sync [PATH]`: a fresh clone restores managed files *and* managed sections that
  are missing or modified, at the versions `managed.json` pinned, through a journaled
  transaction; refuses when the workspace registry lacks a pinned version. `repair --strategy
  restore` now restores missing managed sections too.
- Approval files: `approve --approval-file F` / `forge --approval-file F` approve
  non-interactively from a committed YAML/JSON file (ids, versions, classes, optional registry
  digest); a plan outside it is refused with the new exit code 14 and nothing is written.
  `approve --export-approval F` writes the file for a plan.
- Several registries: `registries:` in `agent-forge.yaml` layers a team registry over the core
  one (first wins on a duplicate id; `validate` and `doctor` report shadowing; `catalog show`
  names the registry). The registry digest distinguishes overrides.
- `agent-forge stats [--since DAYS]`: installs, rollbacks and projects per capability from the
  local audit log; nothing is sent anywhere.
- `examples/policy/team-default.yaml`, `docs/team-workflow.md`, `docs/pilots/` (baseline and
  feedback templates).

## 0.2.0 — 2026-10-20

First tagged release. Everything below was developed after the untagged 0.1.0 build; the
installers now resolve the latest GitHub Release instead of `main`.

### Release engineering (6-month plan, phase 0)
- `install.sh` / `install.ps1` install the latest GitHub Release by default; `AGENT_FORGE_VERSION=vX.Y.Z`
  pins a release, `AGENT_FORGE_REF` still selects any branch or tag. `main` is used only when no
  release can be resolved, and the installer says so.
- `uv.lock` (cross-platform) locks every runtime and dev dependency; CI installs with
  `uv sync --locked` on Windows, Linux and macOS and audits the locked runtime set with pip-audit.
- `release.yml`: on a `vX.Y.Z` tag it checks the tag against the package version and the
  changelog, runs the full verification from the lock, builds sdist + wheel, writes
  `SHA256SUMS`, generates a CycloneDX SBOM, signs every file with Sigstore (keyless) and
  publishes the GitHub Release with the changelog section as notes.
- Installer smoke test runs on macOS as well.
- Historical documents moved to `docs/history/`; quickstarts per stack in `docs/quickstart/`.

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
