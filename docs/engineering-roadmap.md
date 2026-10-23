# Engineering roadmap (evidence audit → backlog)

Source of truth for **implementation tasks**. The product direction lives in
[`product-vision.md`](product-vision.md) (the blueprint); architecture decisions in
[`adr/`](adr/). When they disagree, an accepted ADR wins over the vision, and this file is
updated to match.

## Phase 0 audit (2026-10-20)

Baseline: `pytest` 176 passed / 2 skipped (symlink privilege), `agent-forge validate` 0
errors, Windows 11 + Python 3.14 only. Six read-only audits mapped each blueprint
requirement to code and tests. Status legend: ✅ implemented and tested · 🟡 implemented
but unverified · ❌ missing · ⚠️ known risk. "→ B1" points at the backlog item that closes it.

### Plan integrity, approval, policy

| Requirement | Before | Evidence / gap |
|---|---|---|
| Plan binds target, file hashes, registry digest, ops, approval classes | ✅ | `models/plan.py` `content_digest`; `test_plan_digest_binds_approval` |
| Plan binds **policy** | ❌ | a policy tightened after approval did not stop `apply` → A2 |
| `registry/policies/` inside the registry digest | ❌ | digest covered `capabilities/` only, although documented otherwise → A3 |
| Plan expiry | ❌ | `created_at` not in the digest, no TTL → A4 |
| Tampered plan refused | ⚠️ | unkeyed digest recomputable by anyone who edits the plan file; workspace record never compared → A1 |
| Invalid project policy | ⚠️ | replaced by a permissive layer (fails open) → A5 |
| Deterministic resolution for fixed inputs | 🟡 | sorted ordering, no test → A6 |
| Strictest-wins layering, score never overrides policy | ✅ | `test_strictest_layer_wins…`, `test_matching_honours_policy` |
| Approval classes for shared files / hooks / MCP | ✅ | `test_hooks_mcp.py` |
| Dependencies, cycles, conflicts | ✅ | `test_registry.py`, `test_matching.py` |

### Filesystem safety and concurrency

| Requirement | Before | Evidence / gap |
|---|---|---|
| Traversal, absolute, drive, UNC, reserved names | ✅ | `test_rejects_unsafe_relative_paths`, hypothesis fuzz |
| Symlink / junction components | ✅ | `test_symlink_escape_is_blocked`, `test_resolve_refuses_junction_component` |
| Directories created after the check | ⚠️ | parents created by `mkdir(parents=True)` without re-checking → C2 |
| Concurrent apply / rollback on one target | ❌ | no lock anywhere → C1 |
| Write-time stale check | 🟡 | code exists, never exercised → C3 |
| `.git/`, case and Unicode (NFC/NFD) aliases | ❌ | → C4 |
| `managed.json` paths in the target | ⚠️ | only `/` and `..` checked → C5 |
| Backup names | ⚠️ | never path-checked → C6 |
| Scan read bounded after walk | ⚠️ | size checked at walk time only → C7 |
| `CONIN$`, `CONOUT$`, superscript `COM¹`/`LPT¹` | ❌ | → C8 |
| Atomic per-file replace (temp + fsync + `os.replace`) | ✅ | `test_atomic_write_leaves_no_partial_file` |

### Transactions and recovery

| Requirement | Before | Evidence / gap |
|---|---|---|
| Operation journaled **before** the write | ❌ | recorded only after → B1 |
| Crash mid-apply detectable and recoverable | ❌ | `in_progress` left behind, rollback refused it, nothing reported it → B2 |
| Failure while saving the failure | ⚠️ | masked the original error → B3 |
| Backup integrity checked byte-for-byte | ⚠️ | newline-normalised hash only → B4 |
| Failed rollback visible on the original transaction | ❌ | → B5 |
| Fault injection at every apply boundary | ⚠️ | one boundary tested → B6 |
| Rollback keeps post-apply user edits; partial report | ✅ | `test_full_lifecycle_with_drift_and_rollback` |
| Docs overstate crash safety | ⚠️ | `docs/security.md` → B7 |

### Capability model, lifecycle, content security

| Requirement | Before | Evidence / gap |
|---|---|---|
| Static scan for unsafe commands, prompt injection, secrets | ❌ | → D1 |
| Pinned integrity enforced at plan time | ⚠️ | only `validate` reported a mismatch → D2 |
| `source.revision` is an immutable SHA | 🟡 | free string → D3 |
| Revoked state, replacement, report installed deprecated/revoked items | ❌ | → D4 |
| Risk rationale | ❌ | → D5 |
| Secret redaction in the audit log | ❌ | → D6 |
| Approval re-evaluated on content change (registry digest) | ✅ | `test_stale_plan_rejected_when_registry_changes` |
| Owner, tool-version compatibility, dependency version constraints | ❌ | deferred (ADR-0002: until a second version exists) → later |

### Scanner, resolver, adapters

| Requirement | Before | Evidence / gap |
|---|---|---|
| Representative fixtures with reviewed expected results; precision measured | ❌ | → E1 |
| Low-confidence detections surfaced | ⚠️ | silently dropped below 0.5 → E2 |
| Monorepo / nested manifests | ⚠️ | root or depth-1 only → E3 |
| JVM (Maven/Gradle/Spring), .NET, Go frameworks, build commands | ❌ | → E4 |
| Adapter conformance suite | ❌ | → E5 |
| User profile overrides | ❌ | → E6 |
| Path→platform mapping owned by adapters | ⚠️ | duplicated in core → E7 |
| Exclusions, secrets never opened, link-safe walk | ✅ | `test_scanner.py`, `test_junctions.py` |

### Operations, release, docs

| Requirement | Before | Evidence / gap |
|---|---|---|
| CI on supported OS × Python | ❌ | → F1 |
| Schema drift check | ❌ | manual diff only → F2 |
| SECURITY.md, CONTRIBUTING.md, policy / operations / evaluation docs, examples/ | ❌ | → F3 |
| Every exit code tested | ⚠️ | 2, 4, 8, 9, 10, 12, 13 untested → F4 |
| Single source of version | ⚠️ | pyproject + `__init__` → F5 |
| Dependency vulnerability checks | ❌ | → F1 (pip-audit, Dependabot) |
| One roadmap, stale docs | ⚠️ | five overlapping documents → F6 |
| No telemetry | ✅ | network only for git and the installer |

## Backlog

Ordered by risk reduction. Each item: change → proving test. Status reflects this repository.

| ID | Change | Proving test | Status |
|---|---|---|---|
| A1 | Approval anchored in the workspace: `approve` records the digest, `apply` refuses a plan whose digest differs from the recorded one | `test_hand_edited_and_rehashed_plan_is_refused` | done |
| A2 | `Plan.policy_digest` (effective layers) in the digest; checked at approve and apply | `test_policy_tightened_after_approval_blocks_apply` | done |
| A3 | `Registry.digest` covers `policies/` | `test_registry_digest_covers_policies` | done |
| A4 | `Plan.expires_at` (7 days) in the digest; expired plans refused | `test_expired_plan_is_refused` | done |
| A5 | Invalid project policy fails closed | `test_invalid_project_policy_fails_closed` | done |
| A6 | Determinism test over normalised plans | `test_plan_resolution_is_deterministic` | done |
| B1 | Journal each operation (pending, with backup) before writing | `test_crash_mid_apply_is_journaled_and_recoverable` | done |
| B2 | Rollback of `in_progress` / `failed` / `partial`; `validate`/`doctor`/`status` flag interrupted transactions | same + `test_interrupted_transaction_fails_validation` | done |
| B3 | Original apply error survives a failing record save | `test_original_error_survives_record_save_failure` | done |
| B4 | Byte-exact backup hash verified before restore | `test_tampered_backup_is_not_restored` | done |
| B5 | Failed rollback marks the original `recovery_required` | `test_failed_rollback_marks_recovery_required` | done |
| B6 | Fault injection at backup, write, read-back, manifest, record boundaries | `test_fault_at_every_boundary_is_recoverable` | done |
| B7 | Docs state per-file atomicity and the crash model honestly | docs review | done |
| C1 | Per-target exclusive lock around apply / rollback | `test_concurrent_apply_is_refused` | done |
| C2 | Re-check parent directories immediately before each write | `test_link_created_after_preflight_is_refused` | done |
| C3 | Exercise the write-time stale check | `test_file_changed_between_preflight_and_write` | done |
| C4 | Refuse `.git` components and case/NFC aliases of existing entries | `test_alias_of_existing_entry_is_refused` | done |
| C5 | `managed.json` entries validated with `validate_relative_path` | extended manifest test | done |
| C6 | Backup names validated | `test_backup_name_traversal_refused` | done |
| C7 | Bounded scan reads | `test_scan_read_is_bounded_when_file_grows` | done |
| C8 | More Windows reserved names | extended reserved-name test | done |
| D1 | Content-safety scan of curated assets with reviewed acknowledgements | `test_unsafe_content_is_an_error_unless_acknowledged` | done |
| D2 | Integrity mismatch rejected at plan time | `test_capability_edited_after_pinning_is_not_planned` | done |
| D3 | `source.revision` must be a 40-hex SHA | `test_revision_must_be_a_commit_sha` | done |
| D4 | `revoked` status + `replaced_by`; installed deprecated/revoked reported | `test_installed_revoked_capability_fails_validation` | done |
| D5 | `review.risk_rationale` required above low risk | `test_risk_above_low_needs_rationale` | done |
| D6 | Audit log redacts secret-looking values | `test_audit_log_redacts_tokens` | done |
| E1 | `examples/` fixtures (Java, Go, Next.js, Python, mixed monorepo) with reviewed expected profile + recommendations | `test_example_projects_match_expected` | done |
| E2 | Low-confidence detections become profile warnings | `test_low_confidence_detection_is_reported` | done |
| E3 | Nested manifests (services/*, packages/*, apps/*) | covered by E1 mixed monorepo | done |
| E4 | Maven/Gradle/Spring, Go frameworks, .NET, build commands | covered by E1 | done |
| E5 | Adapter conformance suite over every adapter | `tests/conformance/` | done |
| E6 | `.agent-forge/profile.yaml` overrides | `test_profile_override_file` | done |
| E7 | `PlatformAdapter.owns()` replaces core path→platform copies | conformance suite | done |
| F1 | CI matrix (Windows/Ubuntu/macOS × 3.11/3.14), pip-audit, Dependabot | workflow | done |
| F2 | `export_schemas.py --check` | CI step | done |
| F3 | SECURITY.md, CONTRIBUTING.md, docs/policy.md, operations.md, evaluation.md, product-vision.md | docs review | done |
| F4 | Exit-code matrix test | `test_exit_codes` | done |
| F5 | Version from one source | packaging | done |
| F6 | One roadmap; historical documents labelled | docs review | done |

## Field-test audit (2026-10-23)

Input: `agent-forge-upgrade-proposal.md` (a field test of 0.4.0 on a synthetic monorepo:
Java 17 / Spring Boot, Vert.x, Kafka, RabbitMQ, Redis, MongoDB, Elasticsearch 8, Next.js,
Playwright, Docker, Kubernetes, Terraform). Measured there: scanner recall 10/13 indicators
(Elasticsearch, Vert.x, Kubernetes missed), recommendation precision 20/21 (`ecc.jpa-patterns`
on a Spring service without JPA), architecture-need coverage 7 PASS + 3 PARTIAL + 4 FAIL / 14
(no MongoDB, Elasticsearch, Vert.x content; backend reviewer unusable on Codex). Dry-run,
apply, validate, rollback and partial rollback all passed. Those numbers describe one fixture,
not a benchmark.

| ID | Change | Proving test | Status |
|---|---|---|---|
| G1 | Scanner records `vertx`, `elasticsearch` (all ecosystems), `jpa` (never `hibernate-validator`) and `kubernetes` (manifest content, Helm chart, kustomization; not a directory name, pipeline YAML or compose) | `test_jvm_build_files_show_vertx_elasticsearch_and_persistence`, `test_kubernetes_is_detected_from_manifest_content_in_any_directory`, `test_yaml_without_kubernetes_kinds_is_not_kubernetes` | done |
| G2 | Words in README / docs / comments are never dependencies | `test_words_in_docs_and_comments_are_not_dependencies` | done |
| G3 | `ecc.jpa-patterns` gated on `jpa`, not `spring`; `ecc.kubernetes-patterns` gated on `kubernetes`, not tag-only | `test_jpa_patterns_need_a_jpa_dependency_not_only_spring`, `test_kubernetes_patterns_are_not_recommended_without_manifests` | done |
| G4 | Reviewed fixture with the field-test shape; 13/13 indicators; precision and recall measured by `scripts/matching_report.py` | `examples/jvm-platform`, `test_example_projects_match_expected` | done |
| G5 | Stack skills for MongoDB, Elasticsearch, Vert.x (on demand, identical Codex copies) | `test_stack_skills_follow_their_integrations_on_the_platform_fixture` | done |
| G6 | Backend review on platforms without subagents (`forge.skill.backend-review`, body identical to the agent); `unsupported_platform` reason names the missing kind | `test_backend_review_skill_is_the_agent_body_for_platforms_without_agents`, `test_codex_gets_the_backend_review_skill_and_a_readable_rejection_for_the_agent` | done |
| G7 | Evidence level per recommendation (`confirmed` / `probable` / `needs_confirmation`) with the evidence path and confidence in every reason; plan table and `--json` carry it | `test_recommendations_carry_an_evidence_level`, `test_confirmed_profile_entries_are_confirmed_evidence` | done |
| G8 | Per-module profiles in a monorepo (a framework found in `services/a` is today a repository-wide fact with the manifest as evidence; a capability for one module is proposed to the whole repository) | needs an ADR: module-scoped applicability and destinations | open |
| G9 | Kafka / RabbitMQ, DDD / modular-monolith and Terraform content beyond what exists (`event_driven` pack, `ecc.kubernetes-patterns`, `ecc.deployment-patterns`) | per the proposal's own rule, only with an owner, a trigger and a matching test; not written speculatively | open |
| G10 | A/B measurement of coding uplift (10 tasks x 2 arms x 3 runs) | `tools/agent-forge-eval` is ready; needs a maintainer with the tool and a budget (Gate E) | open |

## Release gates

Evidence for the production gates of [product-vision.md §11](product-vision.md#11-production-readiness-gates).
"Met" means an automated test or check proves it in this repository; anything else says why.

| Gate | Item | Status | Evidence |
|---|---|---|---|
| A Correctness | core use cases tested | met | 255 tests: `tests/unit`, `integration`, `e2e`, `security`, `conformance` |
| | deterministic resolution | met | `test_plan_resolution_is_deterministic` |
| | invalid / stale / tampered / expired plans rejected | met | `tests/security/test_plan_integrity.py`, `test_stale_plan_*`, `test_exit_codes` |
| | invalid capability metadata fails safely | met | strict models (`extra=forbid`), `test_unknown_schema_versions_are_refused`, `test_revision_must_be_a_commit_sha`, registry validator tests |
| | dependency and conflict resolution | met | `test_registry.py`, `test_matching.py`, skill-call lint (ADR-0003) |
| B Security | traversal, links, junctions | met | `test_filesystem_safety.py`, `test_junctions.py` (Windows), symlink tests (Linux/macOS CI) |
| | check/write race, concurrent apply | partial | lock + write-time re-checks tested (`test_concurrent_apply_is_refused`, `test_link_created_after_preflight_is_refused`, `test_file_changed_between_preflight_and_write`); a local process racing the final rename is a documented residual |
| | unsafe commands and permissions | met | content-safety rules + `test_each_content_rule_fires`; grants/approval classes in `test_hooks_mcp.py`, `test_policy.py` |
| | secrets not leaked | met | secret files never read (`test_scanner.py`), `test_audit_log_redacts_tokens` |
| | untrusted content never executed | met | no code path executes registry or checkout content; installer smoke runs only Agent Forge |
| | high-risk changes need approval | met | approval classes, `require_request_from_risk`, `test_risk_thresholds` |
| | security triage process | met | `SECURITY.md` |
| C Recovery | fault injection at every apply boundary | met | `test_fault_at_every_boundary_is_recoverable` (backup, write, read-back, manifest, record) |
| | interrupted transactions detected and recovered | met | `test_crash_mid_apply_is_journaled_and_recoverable`, `doctor`/`status`/`validate` |
| | rollback preserves post-apply edits; partial report | met | `test_full_lifecycle_with_drift_and_rollback` |
| | backup integrity, transaction consistency | met | `test_tampered_backup_is_not_restored`, `test_corrupted_transaction_record_is_refused` |
| D Compatibility | clean install per supported OS | met | CI `installer` job (Windows, Linux, macOS) against the checkout; releases pinned by tag |
| | adapter conformance | met | `tests/conformance/test_adapters.py`, `test_render.py` (5 adapters, ADR-0006) |
| | existing configuration preserved | met | section/JSON merge tests, `test_setup_installs_only_the_entry_skill` |
| | upgrade/downgrade documented | met | `docs/operations.md` |
| | unsupported versions fail clearly | met | unknown `schema_version` refused; tool versions detected and bounded (`tests/unit/test_tool_versions.py`, exit 15); weekly docs watch |
| E Value | representative fixture set | met | `examples/` (7 projects, incl. the 2026-10-23 field-test shape) |
| | matching precision / missed measured | met | `scripts/matching_report.py` (examples exact; `--corpus` + thresholds for anonymised real repos), CI |
| | baseline-vs-candidate evaluation | partial | harness `tools/agent-forge-eval` + 30 reviewed tasks + `review.evidence` field; no measurement run yet (needs a maintainer with the tool and a budget) |
| | evidence vs AI explanation separated | met | plans carry evidence and reasons from rules; the agent's review is a separate conversation output |
| | limitations documented | met | `docs/security.md` (known gaps, runtime boundary), `docs/evaluation.md` |
| F Release | versioning, changelog, release process | met | single version source, `CHANGELOG.md`, `release.yml` (tag check, build, SHA256SUMS, SBOM, Sigstore), `docs/operations.md#release-process` |
| | dependencies pinned, vulnerability checks | met | `uv.lock`, CI installs `--locked`, pip-audit on the locked set, Dependabot |
| | CLI output and exit codes documented | met | `docs/cli-reference.md`, `test_exit_codes` |
| | security contact, triage | met | `SECURITY.md` |
| | install, troubleshooting, recovery guides | met | `README.md`, `docs/troubleshooting.md`, `docs/operations.md` |

Not production-ready for: capability **value** claims (Gate E: harness ready, no measurement yet). The
6-month plan that follows these gates is tracked in [roadmap-2026h2.md](roadmap-2026h2.md).

### Deferred, with reasons

- **Evaluation runs:** the harness lives in `tools/agent-forge-eval` (opt-in, out of the
  core, ADR-0002); measurements are a maintainer task with a budget, see `evaluation.md`.
- ~~Dependency version constraints~~: shipped (`capability-model.md#dependency-version-constraints`).
  Tool-version ranges per adapter exist since ADR-0006.
- **Keyed (HMAC) seals:** the workspace is the trust anchor (A1). Releases are signed with
  Sigstore (keyless) by `release.yml`; a signed registry artifact waits for the public
  registry repository (plan 4.7).
- ~~Uniform JSON envelope~~: shipped (envelope v1, `cli-reference.md#json-output`).
- **Orchestration / runtime (Phase 5):** out of the core (ADR-0002, vision §3.3).
