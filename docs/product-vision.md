> **Status:** accepted as the product north star (2026-10-20). It states direction and
> acceptance criteria, not tasks. Implementation tasks, the evidence audit and their status
> live in [`engineering-roadmap.md`](engineering-roadmap.md); binding decisions in
> [`adr/`](adr/) (an accepted ADR wins where they differ). Production-gate evidence:
> [`engineering-roadmap.md` § Release gates](engineering-roadmap.md#release-gates).

# Agent Forge --- Product Vision & Production Blueprint

**Repository:** https://github.com/tamtd91ht/agent-forge\
**Document type:** Product direction, target architecture and production
acceptance criteria\
**Status:** Proposed --- use as a north-star document, then validate
every item against the current codebase\
**Primary goal:** Evolve Agent Forge into a secure, reliable,
project-agnostic product that helps teams inspect, improve and govern
the capabilities of their AI coding agents across different repositories
and AI tools.

------------------------------------------------------------------------

## 1. Executive direction

Agent Forge should become a **Project-Agnostic AI Agent Capability
Manager**: a tool that understands a target project, recommends suitable
AI-agent capabilities, explains why they are needed, applies approved
changes safely, and verifies that the resulting configuration is correct
and maintainable.

It should help a team upgrade the way its existing coding agents work
without forcing the team to adopt a new LLM, a new development process,
or a specific programming language.

The product must not confuse three different responsibilities:

1.  **Capability management:** discover, curate, select, install,
    update, validate and remove skills, rules, instructions, agents,
    hooks, MCP configurations and other supported assets.
2.  **Execution governance:** define which tools and actions agents may
    perform, under what conditions, with what approvals and audit
    evidence.
3.  **AI coding orchestration:** plan and execute software tasks,
    coordinate agents, run tests and deliver changes.

Agent Forge's core should own the first responsibility and provide clear
integration points for the second. It should not absorb the third into
the core merely to appear more comprehensive. A separate runtime or
existing coding platform can own task execution and orchestration.

**Product promise:** make AI-agent capability changes explainable,
reproducible, safe, measurable and reversible.

**Non-promise:** installing a capability does not guarantee better code.
Improvement must be demonstrated through project-specific evaluation.

## 2. Product principles

1.  **Project-agnostic core:** no mandatory dependency on Java, Python,
    Go, TypeScript, a particular framework or a single AI provider.
2.  **Adapters over assumptions:** keep the core domain independent of
    Claude Code, Codex or any future coding tool's file formats and
    conventions.
3.  **Read-only first:** scanning and recommendation must not modify the
    target project.
4.  **Explicit approval:** consequential writes, permission changes and
    trust-boundary changes require policy-defined authorization.
5.  **Secure by default:** treat project files, external capability
    sources, generated instructions and tool configurations as
    potentially untrusted input.
6.  **Preserve project ownership:** never silently replace
    developer-authored instructions or configuration.
7.  **Explain every recommendation:** show evidence, reason,
    compatibility, confidence, risks and expected impact.
8.  **Reproducible plans:** a plan must identify its inputs, versions,
    policy and content digests.
9.  **Verifiable claims:** security, rollback and compatibility promises
    must have automated tests.
10. **Incremental adoption:** teams can use scan, plan, policy, apply or
    evaluation independently where supported.
11. **Model-neutral:** do not require a self-hosted LLM or a single paid
    model to use the core product.
12. **Small core, extensible edges:** add integrations through defined
    interfaces instead of growing a large set of special cases.
13. **Human control over uncertainty:** low-confidence detection,
    conflicting requirements and high-risk changes must stop for review
    rather than guess.
14. **Operational simplicity:** begin as a local CLI and library; add a
    service or hosted control plane only when a concrete multi-user
    requirement justifies it.

## 3. Target users and primary use cases

### 3.1 Target users

-   **Individual developer:** improve the AI coding setup in one
    repository.
-   **Tech lead / AI Architect:** establish reusable defaults, project
    profiles and approval policies.
-   **Platform engineering team:** curate and distribute approved
    capabilities across many repositories.
-   **Security team:** review external sources, permissions, hooks, MCP
    servers and change history.
-   **Engineering manager:** understand adoption, quality impact,
    maintenance burden and cost.

### 3.2 Core use cases

1.  Scan an existing project and produce an evidence-based profile.
2.  Recommend suitable capabilities without immediately installing them.
3.  Compare current configuration with a desired baseline and identify
    gaps or drift.
4.  Generate a reviewable plan and diff.
5.  Apply approved changes without losing local customization.
6.  Validate installed files, tool compatibility and policy compliance.
7.  Upgrade, pin, deprecate or revoke capabilities safely.
8.  Roll back changes without overwriting legitimate edits made
    afterward.
9.  Evaluate whether a capability improves task outcomes on
    representative tasks.
10. Export a machine-readable report for CI, governance or an external
    orchestration system.
11. Add support for a new coding tool through an adapter, without
    changing core business rules.

### 3.3 Explicitly out of scope for the core

-   Owning the organization's backlog, sprint, PM/BA workflow or issue
    tracker.
-   Automatically implementing every feature from requirement to
    production release.
-   Replacing Git hosting, CI/CD, code review or test infrastructure.
-   Running or training a proprietary foundation model.
-   Automatically trusting arbitrary public capability repositories.
-   Guaranteeing code quality merely because a recommended capability
    was installed.
-   Automatically committing, merging, pushing or deploying application
    changes by default.

These functions may be integrated later through separate modules or
external systems.

## 4. Product boundaries and target architecture

``` text
Developer / CI / Platform Workflow
              |
          CLI / API
              |
       Application Use Cases
              |
  +-----------+------------+----------------+
  |           |            |                |
Project    Capability    Policy &        Evaluation
Scanner    Registry      Approval        Framework
  |           |            |                |
  +-----------+------------+----------------+
              |
     Plan / Diff / Apply
              |
    Transaction Journal & Recovery
              |
   Tool Adapters + Filesystem/Git
              |
    Target Project / Agent Config
```

Optional integrations sit outside the minimum core:

``` text
External Agent Runtime / Coding Platform
              |
       Stable Integration API
              |
 Agent Forge: capabilities, policies,
 plans, validation and audit artifacts
```

### 4.1 Core domain

Owns stable domain concepts and rules:

-   Project profile and detected evidence.
-   Capability identity, version and provenance.
-   Dependencies, conflicts, compatibility and permissions.
-   Desired state and resolved capability set.
-   Plan, approval, apply operation and transaction state.
-   Policy decision and audit event.
-   Validation result and evaluation result.

Core domain must not import vendor-specific adapter code or directly
perform filesystem operations.

### 4.2 Application layer

Coordinates use cases such as:

-   `scan_project`
-   `resolve_capabilities`
-   `create_plan`
-   `validate_plan`
-   `approve_plan`
-   `apply_plan`
-   `validate_installation`
-   `detect_drift`
-   `upgrade_capability`
-   `rollback_transaction`
-   `evaluate_capability`

Use cases should be testable without requiring a real AI provider.

### 4.3 Infrastructure layer

Provides filesystem safety, Git inspection, local or remote registry
access, persistent transaction records, locks, hashing, logging and
platform-specific operations.

Infrastructure implementations must sit behind interfaces where
substitution is useful for tests or future deployment modes.

### 4.4 Adapters

Each coding-tool adapter declares:

-   Supported tool and version range.
-   Supported capability types and file formats.
-   Read, write and validation behavior.
-   Path conventions and ownership semantics.
-   Compatibility limitations.
-   Tests and conformance status.

An adapter must not bypass core approval, policy, transaction or audit
controls.

### 4.5 CLI and machine interface

The CLI is a user interface, not the owner of business logic. Provide
stable commands, clear exit codes, human-readable output and a versioned
JSON output contract for automation. Introduce a local or remote API
only when integration requirements justify it.

## 5. Capability model and lifecycle

Every capability must have a stable identity and enough metadata for
safe selection and maintenance.

Minimum conceptual fields:

  -----------------------------------------------------------------------
  Field                               Purpose
  ----------------------------------- -----------------------------------
  `id`                                Stable, unique capability
                                      identifier

  `type`                              Skill, rule, instruction, agent,
                                      hook, MCP, template or supported
                                      type

  `version`                           Immutable released version

  `source`                            Origin and repository or package
                                      reference

  `revision`                          Pinned commit, release or immutable
                                      source revision

  `content_digest`                    Integrity check for the exact
                                      content

  `license`                           License or explicit unknown status

  `owner`                             Maintainer or responsible team

  `targets`                           Supported coding tools and project
                                      contexts

  `dependencies`                      Required capabilities and version
                                      constraints

  `conflicts`                         Known incompatible capabilities or
                                      constraints

  `permissions`                       Required filesystem, process,
                                      network or tool access

  `risk_level`                        Risk classification with documented
                                      rationale

  `compatibility`                     Supported versions and known
                                      limitations

  `validation`                        Required checks and expected
                                      outcomes

  `lifecycle_status`                  Draft, candidate, approved,
                                      deprecated, revoked or archived

  `provenance`                        Who imported, reviewed, approved
                                      and released it
  -----------------------------------------------------------------------

Unknown metadata must be represented honestly. Do not silently treat
unknown license, permissions or provenance as safe.

### 5.1 Lifecycle states

``` text
DISCOVERED
    |
    v
QUARANTINED --> REJECTED
    |
    v
REVIEWED --> NEEDS_CHANGES
    |
    v
APPROVED --> DEPRECATED --> REVOKED
    |
    v
RELEASED
```

This is a conceptual lifecycle; implementation may use a more suitable
state model, but transitions and authorization must be explicit.

### 5.2 Capability lifecycle requirements

-   Pin immutable content; do not trust a mutable branch name as an
    integrity guarantee.
-   Validate schema, source, license, provenance, permissions and
    compatibility.
-   Scan for unsafe commands, secret exposure, suspicious instructions
    and excessive permissions.
-   Require additional review for hooks, MCP servers, shell execution
    and network access.
-   Re-evaluate approval when content, permissions or source revision
    changes.
-   Support deprecation, revocation and replacement without silently
    changing installed projects.
-   Provide a clear report of where a capability is installed and which
    projects may be affected.
-   Preserve historical metadata required to explain past decisions.

## 6. Project understanding and capability resolution

### 6.1 Project scanner

The scanner should identify evidence, not invent an architecture.

It should support:

-   Multiple languages and frameworks in one repository.
-   Monorepo and multi-service layouts.
-   Existing agent configuration files and their ownership.
-   Build, test, lint and format commands where discoverable.
-   Repository guidance, architecture documents and local conventions.
-   Relevant exclusions such as generated files, build output,
    dependency directories and secrets.
-   User-confirmed profile overrides.

Each detection should record the evidence source and confidence.
Ambiguous results should be shown to the user before they affect a plan.

### 6.2 Capability resolver

Resolution should consider:

-   Project profile and explicit user intent.
-   Tool and version compatibility.
-   Capability dependencies and conflicts.
-   Organization policy and project-specific policy.
-   Risk, permission requirements and lifecycle status.
-   Existing installed capabilities and local customization.
-   Evaluation evidence, if available.

The resolver must explain why a capability was selected, rejected or
left for manual review. A relevance score may help rank candidates but
must never override a security policy.

### 6.3 Profiles and policy precedence

Use an explicit precedence model, for example:

1.  Non-overridable security constraints.
2.  Organization baseline.
3.  Repository policy.
4.  Team or stack profile.
5.  User-selected preferences.

The exact precedence must be documented and deterministic. A lower layer
must not silently weaken a higher-level mandatory constraint. Conflicts
must produce a visible decision or error.

## 7. Safe plan, approval, apply and rollback

The production workflow should remain explicit:

``` text
SCAN
  -> RESOLVE
  -> PLAN
  -> REVIEW DIFF
  -> APPROVE
  -> PREFLIGHT
  -> APPLY
  -> VALIDATE
  -> RECORD RESULT
```

### 7.1 Plan integrity

A plan should bind to:

-   Project identity and relevant filesystem state.
-   Selected capability versions and content digests.
-   Registry snapshot or digest.
-   Policy version.
-   Expected file hashes and ownership.
-   Requested operations and required permissions.
-   Plan creation time and expiry policy.

Any material change to these inputs should invalidate approval or
require a new preflight decision.

### 7.2 Filesystem safety

-   Resolve all write paths within the approved project root.
-   Defend against traversal, symlinks, path aliases and check/write
    races.
-   Define behavior for case sensitivity, Unicode paths and
    Windows-specific path forms.
-   Reject unexpected file types and unsafe destinations.
-   Use atomic replacement where supported and document platform
    limitations.
-   Avoid following untrusted links during scan or apply.
-   Test concurrent execution and lock behavior.

### 7.3 Ownership and merge

Track whether each managed file is generated, user-owned or jointly
managed. Prefer structured merge or patch operations where possible. If
safe merging is not possible, stop and show the conflict.

Never replace `AGENTS.md`, `CLAUDE.md`, tool configuration or another
existing file wholesale without a clearly reviewed diff and appropriate
authorization.

### 7.4 Transaction and rollback

-   Record each operation and its preconditions.
-   Preserve recoverable backups before writes.
-   Record progress durably enough to recover from interruption.
-   Make transaction states explicit: planned, applying, applied,
    partially failed, rolled back or recovery required.
-   On rollback, verify current content before restoring an old version.
-   Never overwrite developer changes made after the original apply.
-   Provide a recovery report if automatic rollback cannot safely
    complete.
-   Test failures at every operation boundary, including process
    termination and storage errors.

Rollback should be described as best-effort where the filesystem or
external effects cannot guarantee atomic recovery. Do not claim full
atomicity unless it is demonstrated by tests.

## 8. Security and trust model

Treat all of the following as untrusted until validated:

-   External capability repositories and archives.
-   Project files and agent instructions.
-   Generated plans and serialized state.
-   Hook and MCP definitions.
-   Commands suggested by an AI model.
-   Registry metadata received from remote sources.

### 8.1 Minimum controls

-   Threat model and documented trust boundaries.
-   Least-privilege filesystem and process access.
-   No implicit execution of capability content during discovery or
    installation.
-   Explicit permission declarations for shell, network and external
    tools.
-   Secret redaction in logs and reports.
-   Safe parsing and size limits for imported content.
-   Integrity verification for registry items and transaction records.
-   Clear separation between a recommendation and an authorization
    decision.
-   Audit events for approval, policy decisions, apply, failure,
    rollback and revocation.
-   Security reporting and dependency update process.

### 8.2 Runtime boundary

Agent Forge's local file safety does not sandbox a coding agent after
installation. If an external agent runtime can execute shell commands,
access the network or read sensitive files, those actions must be
governed by the runtime, operating system, container or other
enforcement layer.

Do not present a capability manager as a complete execution sandbox.

## 9. Evaluation: prove that capabilities help

Evaluation is a first-class product area, but it should be independent
of the installation engine.

### 9.1 Evaluation workflow

1.  Define representative tasks and acceptance criteria.
2.  Capture a baseline without the candidate capability.
3.  Run candidate tasks with the capability enabled under controlled
    conditions.
4.  Apply deterministic tests and independent review criteria.
5.  Record failures, regressions, time, model/tool version and cost
    where available.
6.  Compare results and publish a report with limitations.
7.  Promote, revise or reject the candidate based on evidence.

### 9.2 Metrics

-   Task success rate.
-   Required test pass rate.
-   Regression rate.
-   Defect rate found by independent review.
-   Time to verified completion.
-   Cost or token usage per successful task.
-   Human intervention rate.
-   Failure and retry rate.
-   Capability-related security findings.
-   Compatibility failures across supported tool versions.

Do not invent a universal score threshold before establishing a
baseline. Define thresholds per task category and risk level. Separate
objective test results from subjective reviewer judgments.

### 9.3 Evaluation integrity

-   Keep task definitions and expected outcomes versioned.
-   Record model, tool, capability and environment versions.
-   Use repeat runs when model variability could change conclusions.
-   Avoid allowing the same agent that implements a change to be the
    sole judge of success.
-   Clearly mark unavailable metrics and unverified claims.
-   Do not send private project code to an external evaluation service
    without explicit authorization.

## 10. Operations, audit and maintainability

A production release should provide:

-   Structured logs with stable event names.
-   Machine-readable results and documented exit codes.
-   Transaction history and recovery diagnostics.
-   Versioned schemas and migration rules.
-   Registry and capability health checks.
-   Clear errors with safe remediation instructions.
-   CI coverage across supported operating systems and Python versions.
-   Reproducible packaging and dependency locking.
-   Changelog, release notes and rollback guidance.
-   A documented support policy for adapters and capability types.

Local-first storage is acceptable for the initial product. Do not
introduce a database server, message broker or hosted control plane
unless a real requirement---such as centralized multi-user
governance---demands it.

For multi-user governance later, add a separate control plane for
identity, role-based access, centralized policy distribution, approval
records and fleet reporting. Keep the local execution engine usable
without that service where feasible.

## 11. Production readiness gates

A release is not production-ready merely because the CLI works on one
developer machine.

### Gate A --- Correctness

-   [ ] Core domain and use cases have automated tests.
-   [ ] Plan resolution is deterministic for fixed inputs.
-   [ ] Invalid, stale or tampered plans are rejected.
-   [ ] Invalid capability metadata fails safely.
-   [ ] Dependency and conflict resolution is tested.

### Gate B --- Security

-   [ ] Path traversal and symlink tests pass.
-   [ ] Check/write race and concurrent apply tests exist.
-   [ ] Unsafe command and permission cases are tested.
-   [ ] Secrets do not leak through logs or error reports.
-   [ ] Untrusted source content is never implicitly executed.
-   [ ] High-risk changes require the configured approval.
-   [ ] Security findings have a documented triage process.

### Gate C --- Recovery

-   [ ] Fault injection covers every apply boundary.
-   [ ] Interrupted transactions can be detected and recovered.
-   [ ] Rollback preserves post-apply user changes.
-   [ ] Partial rollback produces an explicit recovery report.
-   [ ] Backup integrity and transaction consistency are tested.

### Gate D --- Compatibility

-   [ ] Clean installation works on each supported OS.
-   [ ] Adapter conformance tests run for each supported coding tool.
-   [ ] Existing project configuration is preserved.
-   [ ] Upgrade and downgrade behavior is documented.
-   [ ] Unsupported versions fail clearly rather than silently
    degrading.

### Gate E --- Value

-   [ ] A fixed representative project fixture set exists.
-   [ ] Capability matching precision and missed recommendations are
    measured.
-   [ ] Baseline-versus-candidate evaluation is reproducible.
-   [ ] Reports distinguish observed evidence from AI-generated
    explanations.
-   [ ] Known limitations are documented.

### Gate F --- Release and support

-   [ ] Versioning, changelog and release process are defined.
-   [ ] Dependencies are pinned and vulnerability checks run.
-   [ ] CLI output and exit codes are documented.
-   [ ] Security contact and issue triage process exist.
-   [ ] Installation, troubleshooting and recovery guides are available.

A failed security or recovery gate must block a production release for
the affected capability or workflow. Do not hide a critical failure
behind an overall score.

## 12. Delivery roadmap

Priorities are ordered by risk reduction and product value, not by the
number of features delivered.

### Phase 0 --- Evidence-based code audit

**Objective:** establish what already works and what remains unproven.

-   Map each production requirement to source code and tests.
-   Classify each item as `implemented and tested`,
    `implemented but unverified`, `missing`, or `known risk`.
-   Run the existing test suite and record the baseline.
-   Create focused reproductions for safety and recovery risks.
-   Avoid rewriting modules that already meet the requirement.

**Exit criteria:** an auditable gap list, repeatable baseline tests and
a prioritized implementation backlog.

### Phase 1 --- Trustworthy core

**Objective:** make existing scan/plan/approve/apply/rollback flows safe
and predictable.

-   Close P0 path, approval, transaction and recovery gaps.
-   Harden ownership and merge behavior.
-   Define capability schema, identity, digest and provenance rules.
-   Add cross-platform and fault-injection tests.
-   Document security boundaries and limitations.

**Exit criteria:** all release-blocking correctness, security and
recovery tests pass.

### Phase 2 --- Universal project support

**Objective:** work across diverse real-world repositories.

-   Improve monorepo and multi-stack scanning.
-   Add evidence and confidence to project detection.
-   Formalize adapter interfaces and conformance tests.
-   Add dependency, conflict and compatibility resolution.
-   Support stable machine-readable CLI output and CI mode.

**Exit criteria:** the fixed fixture set passes on all declared
supported platforms and adapters.

### Phase 3 --- Governance and lifecycle

**Objective:** manage capabilities across teams and time.

-   Add policy evaluation and precedence rules.
-   Add capability approval, deprecation, revocation and impact reports.
-   Improve drift detection and safe upgrades.
-   Add structured audit and registry release workflows.
-   Define organization baseline and project override behavior.

**Exit criteria:** capability changes are traceable, reviewable and
controllable under documented policy.

### Phase 4 --- Evaluation and measurable improvement

**Objective:** identify which capabilities create real value.

-   Build representative task suites and project fixtures.
-   Implement baseline-versus-candidate experiments.
-   Record quality, regression, time and cost metrics.
-   Provide evaluation reports with uncertainty and limitations.
-   Use evidence to promote, revise or retire capabilities.

**Exit criteria:** core capability recommendations have reproducible
evaluation evidence appropriate to their risk and intended use.

### Phase 5 --- Optional orchestration integration

**Objective:** integrate with coding workflows without turning the core
into a monolith.

-   Define a stable API or machine-readable contract.
-   Allow external runtimes to request scans, plans, policy decisions
    and validation.
-   Keep execution permissions enforced by the runtime and operating
    environment.
-   Add orchestration only when task state, cancellation, retry, budgets
    and agent permissions are explicitly designed.

**Exit criteria:** an external runtime can integrate without bypassing
policy, approval, audit or filesystem safety.

## 13. Product metrics

Track trends over releases instead of selecting arbitrary targets before
measuring a baseline.

  -----------------------------------------------------------------------
  Area                                Metric
  ----------------------------------- -----------------------------------
  Safety                              Unexpected overwrites; unauthorized
                                      writes; security test failures

  Reliability                         Apply success; rollback success;
                                      recovery-required transactions

  Matching                            Accepted recommendation rate;
                                      false-positive and
                                      missed-capability rate

  Compatibility                       Adapter conformance; failures by
                                      OS/tool version

  Reproducibility                     Identical plan output for fixed
                                      normalized inputs

  Operations                          Scan-to-plan time; actionable error
                                      rate; support incidents

  Capability quality                  Evaluation pass rate; regression
                                      rate; evidence coverage

  Efficiency                          Cost and time per verified
                                      successful task

  Maintainability                     Core-to-adapter coupling; schema
                                      migration failures; flaky tests
  -----------------------------------------------------------------------

Metrics must have defined calculation rules and data sources. Avoid
collecting private source code or unnecessary telemetry by default. If
telemetry is added, make it transparent, configurable and
privacy-preserving.

## 14. Repository and documentation standards

Keep the repository organized around actual responsibilities rather than
one enormous instruction file. The exact folder structure should follow
the current codebase after audit, but the conceptual documentation set
should include:

-   `README.md` --- what the product does, quick start and limitations.
-   `docs/product-vision.md` --- product boundary and long-term
    direction.
-   `docs/architecture.md` --- module boundaries and data flow.
-   `docs/security.md` --- threat model, trust boundaries and controls.
-   `docs/capability-model.md` --- schema and lifecycle.
-   `docs/policy.md` --- policy precedence, permissions and approval.
-   `docs/adapters.md` --- adapter contract and conformance
    requirements.
-   `docs/evaluation.md` --- benchmark methodology and interpretation.
-   `docs/operations.md` --- recovery, diagnostics and support.
-   `docs/cli-reference.md` --- commands, options, JSON output and exit
    codes.
-   `CONTRIBUTING.md` --- development and test process.
-   `SECURITY.md` --- vulnerability reporting.
-   `CHANGELOG.md` --- user-visible changes.
-   `examples/` --- small, reproducible project fixtures and expected
    outputs.

Do not create duplicate roadmaps that contradict one another. Treat this
document as the **product north star**. Keep implementation-level tasks,
file-specific changes and test details in a separate engineering roadmap
or issue tracker. Link the two documents and assign one as the source of
truth for each type of decision.

Documentation must be concise, use diagrams for flows and boundaries,
state limitations directly, and link claims to tests or implementation
evidence where possible.

## 15. Engineering execution rules for AI coding agents

When using an AI coding agent to implement this roadmap:

1.  Inspect the relevant code, tests, configuration and recent changes
    before proposing a rewrite.
2.  Map the requirement to existing modules; reuse working
    implementations.
3.  Separate independent tasks and define file ownership before parallel
    work.
4.  Ask for clarification when requirements conflict or when a
    security-sensitive decision is ambiguous.
5.  Write or identify a failing test before fixing a reproducible
    defect.
6.  Keep each change small enough to review and revert independently.
7.  Run targeted tests first, then the relevant regression suite.
8.  Have an independent review check correctness, security and scope.
9.  Update documentation only when behavior or supported guarantees
    change.
10. Report exactly what changed, tests run, tests not run, residual
    risks and follow-up work.
11. Do not claim production readiness without evidence for the relevant
    release gates.
12. Do not automatically commit, push, merge or deploy unless the user
    or repository workflow explicitly authorizes it.

## 16. First implementation backlog

Start with a code-evidence audit and turn the findings into small tasks.
The following sequence is a starting hypothesis, not a claim that these
functions are missing:

1.  Inventory current modules, entry points, data models and tests.
2.  Map plan approval and digest validation to tests.
3.  Audit path resolution, symlink handling and filesystem races.
4.  Test apply interruption, concurrent operations and rollback
    preservation.
5.  Verify capability provenance, content digest and approval
    invalidation.
6.  Establish representative project fixtures for Java, Go,
    TypeScript/Next.js, Python and mixed-stack repositories.
7.  Measure scanner and capability resolver behavior against manually
    reviewed expected results.
8.  Define adapter conformance tests for each currently supported tool.
9.  Define the policy decision model and precedence.
10. Design the smallest useful evaluation experiment before implementing
    a broad benchmark platform.

For every task, record: requirement, evidence in the current code,
expected behavior, tests, files likely affected, risk, acceptance
criteria and rollback plan.

## 17. Definition of done

Agent Forge can be considered ready for broad production adoption only
when all of the following are true:

-   It can inspect and recommend without modifying a project.
-   It supports a documented set of project types and coding-tool
    versions, with clear limitations.
-   Every proposed change is explainable and reviewable.
-   Approved changes are applied with verified integrity and safe
    ownership handling.
-   Failure and interruption are detectable, and recovery does not
    silently destroy newer user changes.
-   Capability sources, versions, permissions and lifecycle are
    traceable.
-   Security constraints cannot be bypassed by a relevance score or an
    AI-generated explanation.
-   Quality claims are backed by repeatable tests or evaluations.
-   CI, installation, upgrades, errors and support procedures are
    documented.
-   A new adapter or capability type can be added without rewriting the
    core.
-   The team can explain what the product does **not** guarantee.

The target is not "supports every possible project automatically." The
realistic target is **a stable, extensible core that supports a clearly
declared range of projects and tools, detects uncertainty, and fails
safely outside that range**.

------------------------------------------------------------------------

## Final decision

Build Agent Forge as a **trusted capability and governance layer for
existing AI coding agents**. First make the current core demonstrably
safe, then broaden project/tool compatibility, then add policy and
evaluation, and only afterward integrate deeper orchestration.

The measure of success is not how many capabilities Agent Forge
installs. It is whether teams can improve their AI coding setup across
repositories with less risk, repeatable changes, measurable outcomes and
a clear path to recovery.
