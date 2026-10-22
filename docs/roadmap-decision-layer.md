# Decision-layer roadmap (owner's upgrade checklist, tracked)

Written 2026-10-21 from the owner's checklist
([`history/agent-forge-upgrade-checklist.md`](history/agent-forge-upgrade-checklist.md)) and
the rubric for the entry skill ([`history/SKILL-section-3-4-rubric.md`](history/SKILL-section-3-4-rubric.md)).
This file is the tracked version: one line per item, its status in this repository, and what
is left for a person. The architecture decisions are [ADR-0007](adr/0007-decision-layer.md)
(accepted) and [ADR-0008](adr/0008-default-catalog-criteria.md) (proposed). The 6-month plan
([`roadmap-2026h2.md`](roadmap-2026h2.md)) is unchanged; this layer sits on top of its phase 1.

Status: ✅ done in the repo · 🟡 done in the repo, needs a human action · ⏳ not started ·
👤 only a person can do it (noted what the repo provides) · ✖ deliberately not done, with the reason.

## P0 · Blockers before anyone else runs the installer

| # | Item | Status | Evidence / what is left |
|---|---|---|---|
| 0.1 | Registry integrity on Linux/macOS | 🟡 | **0.3.1:** the real cause was `sha256_tree` sorting `Path` objects (case-insensitive on Windows), not CRLF; fixed, 12 pins re-computed, known-digest test on 3 OS, `registry-integrity` job on 3 OS (`history/agent-forge-fix-v0.3.1.md`).  Pins re-computed at `a1c98ef`; `pin_integrity.py` refuses CRLF; new CI job `registry-integrity` (LF check + `--check` + `validate`, ubuntu); `core.autocrlf` note in `contributing-capabilities.md`. **Left:** tag `v0.3.0` once CI is green (the `v0.2.0` tag predates the fix; its release never published). No pre-commit framework was added: the CI job and the script's refusal cover it without a new dependency. |
| 0.2 | CI reflects the truth | ✅ | installer job runs `validate --no-provenance` and `doctor` on the installed catalog on all three OS; `release.yml` already blocks on `validate`; README badges point at `ci.yml` / releases. |
| 0.3 | Installer safe by default | ✅ | `install.sh` / `install.ps1`: release wheel + `SHA256SUMS` verified, Sigstore bundle verified when `cosign` is present (warning otherwise), `~/.agent-forge/VERSION`, **no fallback to `main`** (exit 1 with the pin hint); `AGENT_FORGE_REF` is an explicit, announced, unverified development path. CI proves the "unverifiable release installs nothing" path on POSIX and Windows. `doctor` shows the installed release and `--check-latest` compares. README puts the pin line next to the install command. **Not exercised:** the Sigstore branch itself (needs a published release and `cosign` on a runner). |

## P1 · Technical trust and the decision layer

| # | Item | Status | Evidence / what is left |
|---|---|---|---|
| 1.1 | Split `cli.py` into `cli/` | ✅ | `agent_forge/cli/` package: `_app`, `_common`, `_envelope`, `_tables` + `registry`, `plans`, `forge`, `ops`, `doctor`, `team`, `decisions`, `lint`; largest file 553 lines; `test_json_envelope.py` unchanged. The decisions-to-plan wiring moved out of the CLI into `decisions/plan_input.py`. |
| 1.2 | Errors as data (`Problem` codes) | ✅ | `apply/engine.py`: `Problem(code, message, op_id, path)`, `ProblemCode` enum, `error_for()` picks the exception / exit code (stale > approval > apply); `grep '"stale" in' src/` is empty; table in `cli-reference.md`; `tests/unit/test_preflight_problems.py`. |
| 1.3 | Property tests for apply/rollback on sections and JSON merges | ⏳ | hypothesis is already a dev dependency; `tests/unit/test_sections.py` has one property test. |
| 1.4 | Locks: wait instead of refuse; doctor cleans orphans | 🟡 | `doctor` reports orphaned locks (pid dead); apply/rollback already take them over. Waiting instead of refusing is a behaviour change left out: an immediate, explicit refusal is safer for an approval-first tool. |
| 1.5 | Audit log with a per-command schema | ✖ | The audit log is JSONL with domain events and `stats` reads it; a per-command line for read-only commands was judged noise. Re-open if a pilot needs durations. |
| 1.6 | Decision record ⭐ | ✅ | `models/decision.py`, `registry/schema/decisions.schema.json`, `decisions verify` (paths, quotes, catalog numbers, grounds, policy; SKIP/REMOVE → ASK), `forge --decisions` (exclusions/requests, ASK gate, `Plan.decisions_digest`), `status` (absent by decision), `drift` (basis missing), `decisions diff`, `decisions explain`. Tests: `tests/unit/test_decisions.py`, `tests/e2e/test_decisions_cli.py`. |
| 1.7 | Golden decisions (model drift) | 🟡 | `scripts/decision_report.py` (compare cell by cell; `--run` executes `claude -p` / `codex exec` on a fixture copy), reviewed golden file for the trap fixture `examples/lint-messy/expected_decisions.json`, `tests/unit/test_decision_report.py`. **Left:** the first real runs (model time), golden files for the six stack fixtures, reports under `docs/evaluation/decisions/`. |
| 1.8 | Skill on the negative-first rubric | ✅ | `forge.skill.agent-forge-upgrade` 2.1.0: sections 3–4 replaced, `lint` / `usage` / `decisions` added to the read-only steps, `forge --decisions` in step 4; Codex copy identical; 6.5k → 13k chars, all on demand (0 always-on). **Left:** run old vs new on the six fixtures (1.7). |
| 1.9 | Three-level policy | ✅ | `capabilities.required` (always planned, never excludable, `check` fails when missing, the agent cannot skip it) · default · `capabilities.forbidden` (= `deny`). `policy` shows `required`. |

## P2 · Pilots

| # | Item | Status | Evidence / what is left |
|---|---|---|---|
| 2.1 | Three pilot repos, baseline first | 👤 | `docs/pilots/TEMPLATE.md`; enable `forge.hook.usage-log` on day one (`forge . --want usage --hooks`) so the 30-day window starts early; commit each `decisions/*.json`. |
| 2.2 | Company policy + CI gate | 🟡 | `check` now also fails when a SKIP / REMOVE of the latest decision record no longer verifies (its basis disappeared) and when an applied plan's `decisions_digest` matches no record in the project (`decisions/gate.py`).  `examples/policy/team-default.yaml` has `required` / `forbidden` / `max_total_context_chars`; `.github/actions/check` fails on drift, revoked, missing required. **Left:** the policy review process page per team. |
| 2.3 | Context budget where the decision is made | ✅ | plan `ctx` column + total, `max_total_context_chars` note (ADR-0003 / phase 3); `lint` gives the before-number. |
| 2.4 | Real upgrade round | 👤 | `upgrade` / `forge` respect drift; deprecation in `check`. **Left:** one round on three pilots. |
| 2.5 | Internal capabilities | 👤 | layered registries (`docs/registries.md`). |

## P3 · Proving value (gate before public)

| # | Item | Status | Evidence / what is left |
|---|---|---|---|
| 3.1 | Default-catalog criteria ⭐ | 🟡 | ADR-0008 **proposed**: evidence, context, conflicts, owner, falsifiable, used; ≤ 15 default entries. **Left:** accept after the first harness runs; then `validate` warns and `catalog --default` filters. |
| 3.2 | Run the evaluation harness | 👤 | `tools/agent-forge-eval`, 30 reviewed tasks; budget in `evaluation.md`. |
| 3.3 | Scheduled evaluation | ⏳ | after 3.2. |
| 3.4 | Pilot KPIs and go/no-go | 👤 | new KPI available now: share of SKIPs downgraded to ASK by `decisions verify` (fabrication rate); `usage` gives the "installed but never invoked" share. |

## P4 · Public

All 👤 / ⏳ as in `roadmap-2026h2.md` phase 4, plus: a public example whose conclusion is
"this repository needs nothing" (`lint` + a decision record with only SKIPs is the artefact).
Content-safety rules for base64 blobs and hidden network calls in scripts: ⏳.

## P5 · Differentiators

| # | Item | Status | Evidence / what is left |
|---|---|---|---|
| 5.1 | `agent-forge lint .` ⭐ | ✅ | read-only, no workspace, < 2 s on this repository: context per file and total, duplicate paragraphs / near-duplicate files, credentials, flagged hook commands, disabled MCP servers; since 2026-10-22 also dead references, overclaimed counts, overlapping descriptions and missing frontmatter (all warnings); `--max-context` as a CI gate (exit 12); proposes nothing. Contradictions stay with the skill (`conflicts`). Fixture `examples/lint-messy` with reviewed `expected_lint.json` (every finding expected, no false positive; also the trap fixture for golden decisions). First real run: a private 290-asset Claude Code configuration (167 skills, 23 subagents, 12 hooks) gave 2 true dead references and 0 false positives after calibration (the lenient frontmatter read removed 102 wrong `schema` findings and corrected the always-on total from 87k to 123k chars). **Left:** run on five public repositories and record the findings. |
| 5.7 | Traits: content for what a project does (ADR-0010) | ✅ | `ProjectProfile.traits` with evidence, `profile.yaml` `traits:` / `ignore:`, `applicability.traits`, two generalised packs (`tenant-isolation`, `money-safety`), `docs/traits.md`. **Left:** the `event_driven`, `pii` and `telephony` packs; measure trait precision on the anonymised corpus (3.5) once it exists. |
| 5.2 | Dead config: usage log ⭐ | ✅ | `forge.hook.usage-log` (opt-in, local, id + kind + timestamp + short session), `agent-forge usage`, `unused` hint in `status`, `unused` ground verified against the log (≥ 14 observed days). |
| 5.3 | `agent-forge import .` | ⏳ | design: wrap hand-written config as `<project>.local` in a project-level registry layer; needs a decision on where that layer lives. |
| 5.4 | Organisation-wide decision report | ✅ | `decisions report DIR...`: capability × verdict × ground, suggestions at 70% / 90% thresholds (≥ 3 repos). |
| 5.5 | Behaviour probes after install | ⏳ | after the harness runs (3.2). |
| 5.6 | Canary rollout | ⏳ | after 2.4. |
| — | `explain <id>` | ✅ | `decisions explain PATH ID`. |
| — | GitHub Action posts the assessment table on PRs | ⏳ | `decisions verify --json` is the input. |
| — | Trap fixtures for golden decisions | ⏳ | with 1.7. |
| — | Split the registry repository | ⏳ | layered registries make it possible (`docs/registries.md`). |

## Keeping the repository honest (cross-cutting)

- One PR, one goal; a feature answers "which pilot needs it, which number improves".
- Docs describe what runs; everything else is here with a status.
- A person reviews `apply/`, `rollback/`, `registry/`, `install.*`, and now `decisions/`.
