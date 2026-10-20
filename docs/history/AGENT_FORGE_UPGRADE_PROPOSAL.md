> **Status: historical input (2026-10-16).** Decisions on it are recorded in
> [ADR-0002](../adr/0002-upgrade-roadmap.md); current direction is
> [docs/product-vision.md](../product-vision.md), current tasks
> [docs/engineering-roadmap.md](../engineering-roadmap.md).

# Agent Forge — Review & Upgrade Proposal

> **Repository:** `tamtd91ht/agent-forge`  
> **Review basis:** repository structure, README and architecture documentation reviewed on 2026-10-16.  
> **Goal:** define a practical upgrade path without rewriting the existing core.

---

## 1. Executive Summary

Agent Forge currently has a strong foundation as a **local-first, approval-first capability management platform for AI coding agents**.

Its strongest architectural decisions are:

- Explicit lifecycle: `SCAN → ASSIGN → PLAN → DIFF → APPROVE → APPLY → VALIDATE → ROLLBACK`
- Registry-based and versioned capabilities
- Project-aware matching
- Explainable recommendations
- Hash-bound approvals
- Atomic writes, backups and rollback
- Clear separation between read-only components and the write boundary
- Platform adapters for Claude Code and OpenAI Codex

The main limitation is **scope**: the current architecture is substantially stronger as a **Capability Manager / Governance Layer** than as a complete Agent Platform.

The recommended strategy is therefore:

> **Do not rewrite the existing core. Evolve Agent Forge into a Capability + Governance + Evaluation platform, and introduce Runtime capabilities as a separate layer.**

Target architecture:

```text
                    AGENT FORGE
                         |
       +-----------------+-----------------+
       |                 |                 |
       v                 v                 v
 Capability Plane    Runtime Plane    Governance Plane
       |                 |                 |
 Skills              Agent            Policy
 Rules               Session          Approval
 Agents              Context          Audit
 MCP                 Tools            Risk
 Hooks               Memory           Provenance
 Instructions        LLM              Rollback
       |                 |                 |
       +-----------------+-----------------+
                         |
                         v
                  Evaluation Engine
                         |
                         v
                 Continuous Improvement
```

---

# 2. Current Architecture Assessment

The current architecture intentionally separates source checkouts, curated registry assets and target projects.

```text
sources/checkouts/*       registry/capabilities/*       target project
       |                         |                         |
       |      curate              |                         |
       +------------------------->|                         |
                                 |                         |
                          registry.loader                  |
                                 |                         |
                                 v                         |
                         scanner / matching                |
                                 |                         |
                                 v                         |
                              planner                      |
                                 |                         |
                                 v                         |
                                diff                        |
                                 |                         |
                                 v                         |
                              approve                      |
                                 |                         |
                                 v                         |
                               apply --------------------->|
                                 |                         |
                                 v                         |
                         validation / rollback <-----------+
```

The repository also explicitly keeps target writes inside `apply` and `rollback`, while adapters remain non-writing. This boundary should be preserved.

---

# 3. Main Problems Identified

## P0 — Product scope is ambiguous

### Problem

The name "Agent Forge" suggests an Agent Runtime / Agent Framework, but the current implementation primarily manages:

- skills
- rules
- agents
- instructions
- hooks
- MCP
- shared configuration
- capability installation

It is therefore closer to:

> **AI Agent Capability Manager + Governance**

than a full Agent Runtime.

### Risk

Without a clear product boundary, future features can become fragmented:

```text
installer
+ agent runtime
+ MCP manager
+ prompt manager
+ memory
+ orchestration
+ evaluation
```

This can cause architectural coupling.

### Recommendation

Explicitly define three planes:

1. **Capability Plane**
2. **Governance Plane**
3. **Runtime Plane**

The current implementation remains the foundation of the first two. Runtime should be introduced as an isolated extension.

---

# 4. P0 — Missing Policy Engine

## Problem

Risk and approval are currently represented in capability metadata and command-level approval flows, but policy should become a first-class subsystem.

A mature platform needs deterministic rules such as:

```yaml
policy:
  hooks:
    require_approval: true

  mcp:
    network: deny

  capability:
    high_risk:
      action: require_approval

  shared_files:
    require_approval: true
```

## Proposed architecture

```text
Capability
    |
    v
Policy Engine
    |
    +--> ALLOW
    +--> DENY
    +--> REQUIRE_APPROVAL
    +--> REQUIRE_REVIEW
```

## Policy evaluation order

```text
Hard Security Constraints
        ↓
Platform Compatibility
        ↓
Organization Policy
        ↓
Project Policy
        ↓
Dependency / Conflict Resolution
        ↓
Capability Score
        ↓
Recommendation
```

**Important:** scoring must never override a security or policy denial.

---

# 5. P0 — No real Evaluation Layer

## Problem

Current validation primarily answers:

> "Was the capability installed correctly?"

It does not answer:

> "Did the capability actually improve the agent?"

These are different concerns.

## Proposed lifecycle

```text
Capability
    ↓
Install
    ↓
Execute benchmark
    ↓
Collect metrics
    ↓
Compare baseline
    ↓
Evaluate
    ↓
Promote / Reject
```

Example:

```text
Capability: tdd-workflow

Baseline:
  task_success = 71%
  tokens        = 100%

After:
  task_success = 84%
  tokens        = 112%

Evaluation:
  quality       = +13%
  token_cost    = +12%

Decision:
  PROMOTE
```

## Metrics

At minimum:

- task success rate
- regression rate
- execution time
- token usage
- tool-call count
- failure rate
- human approval rate
- rollback rate

---

# 6. P1 — Capability Dependency Resolution Needs to Mature

The current model already contains useful concepts such as dependencies, conflicts and equivalents.

The next step should be a deterministic dependency graph.

```text
Capability A
   |
   +--> Dependency B
   |       |
   |       +--> Dependency C
   |
   +--> Conflict D
   |
   +--> Equivalent E
```

Implement:

- dependency graph
- cycle detection
- version constraints
- transitive dependency resolution
- conflict resolution
- capability replacement
- optional dependencies
- platform-specific dependencies

Suggested model:

```yaml
dependencies:
  - id: security-baseline
    version: ">=1.2,<2.0"
    required: true

conflicts:
  - id: legacy-security

equivalents:
  - id: alternative-security
    preference: 0.8
```

---

# 7. P1 — Registry Should Become a First-Class Artifact System

Current registry-based curation is a good foundation.

Upgrade the registry into an immutable, addressable artifact model.

Suggested identity:

```yaml
id: ecc.tdd-workflow
version: 1.4.0

source:
  provider: github
  repository: owner/repository
  commit: <sha>
  paths:
    - skills/tdd

integrity:
  sha256: <digest>

compatibility:
  platforms:
    - claude_code
    - codex

security:
  risk: medium
  network: false
  execution: false
```

Benefits:

- reproducibility
- deterministic installation
- easier rollback
- cacheability
- auditability
- future remote registry support

---

# 8. P1 — Provenance and Trust Model Should Be Stronger

Every capability should have a trust state.

Suggested states:

```text
UNTRUSTED
    ↓
DISCOVERED
    ↓
REVIEWED
    ↓
CURATED
    ↓
VERIFIED
    ↓
TRUSTED
```

Trust should consider:

- source repository
- commit SHA
- content digest
- license
- maintainer
- review status
- security scan
- capability permissions
- network requirements
- executable hooks
- MCP process requirements

Do not equate "popular GitHub repository" with "trusted capability."

---

# 9. P1 — Capability Permissions Need Explicit Modeling

A capability should declare what it can do.

Example:

```yaml
permissions:
  filesystem:
    read:
      - project
    write:
      - project/.claude

  process:
    execute: false

  network:
    access: false

  secrets:
    read: false
```

For MCP / hooks:

```yaml
permissions:
  process:
    execute: true

  network:
    access: true
```

This gives Policy Engine enough information to make deterministic decisions.

---

# 10. P1 — Transaction System Should Evolve Into a State Machine

The existing transaction + hash + backup model is good and should be retained.

Formalize transaction state:

```text
CREATED
  ↓
PREPARED
  ↓
APPLYING
  ↓
APPLIED
  ↓
VALIDATED
```

Failure:

```text
APPLYING
   ↓
FAILED
   ↓
ROLLING_BACK
   ↓
ROLLED_BACK
```

Each transaction should contain:

```yaml
transaction_id:
plan_digest:
registry_digest:
project_fingerprint:
status:
started_at:
completed_at:

operations:
  - path:
    before_sha256:
    after_sha256:
    backup:
    status:
```

This makes crash recovery and auditing much easier.

---

# 11. P1 — Drift Detection Should Become Continuous

Current hash-based drift detection is a good starting point.

Expand it to distinguish:

```text
EXPECTED
ACTUAL
DRIFT
```

Example:

```text
Managed capability:
  expected = abc123

Current file:
  actual   = def456

Result:
  DRIFTED
```

Then expose:

```bash
agent-forge status
agent-forge drift
agent-forge repair
```

Possible repair strategies:

```text
restore
reapply
merge
ignore
unmanage
```

Never silently overwrite user changes.

---

# 12. P1 — Introduce an Event Model

The platform currently has a sequential command flow.

Introduce domain events:

```text
ProjectScanned
CapabilitiesMatched
PlanCreated
PlanApproved
TransactionStarted
FileApplied
ValidationCompleted
RollbackStarted
RollbackCompleted
CapabilityEvaluated
```

Example:

```json
{
  "event": "PlanApproved",
  "timestamp": "...",
  "project": "...",
  "plan_digest": "...",
  "registry_digest": "..."
}
```

Benefits:

- audit
- observability
- debugging
- future UI
- analytics
- automation
- plugin integrations

The event model should not require a message broker initially. Start with append-only local storage and define an abstraction for future backends.

---

# 13. P2 — Introduce Agent Runtime as a Separate Layer

Do not mix Agent Runtime responsibilities into the current installer packages.

Proposed packages:

```text
src/agent_forge/
    capability/
    registry/
    matching/
    planner/
    policy/
    apply/
    rollback/
    validation/
    evaluation/

    runtime/
        agent.py
        session.py
        context.py
        execution.py
        tools.py
        events.py
```

Runtime responsibilities:

```text
Agent
 ├── Session
 ├── Context
 ├── Tool Registry
 ├── LLM Provider
 ├── Execution Policy
 ├── Memory
 └── Event Stream
```

The runtime should consume capabilities; it should not own capability installation.

---

# 14. P2 — Context and Memory Should Be Explicit

Future runtime should distinguish:

```text
System Instructions
Project Context
Task Context
Conversation Context
Tool Results
Long-term Memory
Working Memory
```

Do not concatenate everything into one giant prompt.

Suggested:

```text
ContextBuilder
    |
    +--> system
    +--> project
    +--> task
    +--> conversation
    +--> memory
    +--> tools
```

Each component should have a token budget.

---

# 15. P2 — LLM Provider Abstraction

Avoid coupling the platform to one model provider.

Suggested interface:

```text
LLMProvider
    |
    +-- Claude
    +-- OpenAI
    +-- Gemini
    +-- Local Model
```

The provider should expose:

- chat
- streaming
- tool calling
- structured output
- token usage
- latency
- retry
- model metadata

Keep provider-specific behavior outside Agent Runtime core.

---

# 16. P2 — Tool Execution Needs a Security Boundary

If Agent Forge later executes tools, never let an Agent directly execute arbitrary host commands.

Use:

```text
Agent
  ↓
Tool Request
  ↓
Policy Engine
  ↓
Permission Check
  ↓
Sandbox / Executor
  ↓
Tool Result
```

For high-risk operations:

```text
Agent
  ↓
Tool
  ↓
REQUIRE_APPROVAL
  ↓
Human
  ↓
Execute
```

This is especially important for:

- shell commands
- filesystem writes
- network access
- package installation
- Git operations
- MCP servers

---

# 17. P2 — Add Evaluation / Benchmark Framework

Create:

```text
evaluation/
    benchmark.py
    runner.py
    metrics.py
    scorer.py
    report.py
```

A benchmark should be reproducible:

```yaml
id: backend-api-001

task:
  repository: ...
  prompt: ...

constraints:
  max_tokens:
  max_time:
  allowed_tools:

metrics:
  - task_success
  - tests_passed
  - regression
  - token_usage
  - latency
```

This enables capability A/B testing.

---

# 18. P2 — Capability Lifecycle

Every capability should support:

```text
DISCOVER
   ↓
REVIEW
   ↓
CURATE
   ↓
INSTALL
   ↓
USE
   ↓
EVALUATE
   ↓
UPDATE
   ↓
DEPRECATE
   ↓
REMOVE
```

Suggested commands:

```bash
agent-forge search
agent-forge inspect
agent-forge install
agent-forge upgrade
agent-forge evaluate
agent-forge status
agent-forge drift
agent-forge remove
agent-forge rollback
```

---

# 19. P2 — Upgrade Semantics

Capability upgrade should be explicit.

```text
Installed:
  ecc.tdd-workflow@1.2.0

Registry:
  ecc.tdd-workflow@1.4.0

Upgrade
   ↓
Compatibility check
   ↓
Diff
   ↓
Risk analysis
   ↓
Approval
   ↓
Apply
   ↓
Validate
```

Never make upgrades equivalent to blind replacement.

---

# 20. P3 — Add Remote Registry Later

Do not start with a centralized SaaS service.

First make the local registry deterministic.

Later support:

```text
Local Registry
     +
Remote Registry
     +
Private Enterprise Registry
```

Potential architecture:

```text
RegistryProvider
    |
    +-- LocalFilesystem
    +-- Git
    +-- HTTP
    +-- Enterprise Registry
```

The core should only depend on the provider abstraction.

---

# 21. P3 — Observability

Add structured telemetry without requiring a hosted service.

Recommended metrics:

```text
scan.duration
match.count
plan.duration
approval.count
apply.duration
apply.failure
rollback.count
validation.failure

capability.install.count
capability.upgrade.count
capability.drift.count

evaluation.success_rate
evaluation.regression_rate
llm.tokens
llm.latency
```

Support:

- JSON logs
- local metrics
- optional OpenTelemetry later

---

# 22. P3 — CLI UX

The current CLI workflow is strong but can become more operational.

Suggested UX:

```bash
agent-forge doctor

agent-forge scan
agent-forge recommend

agent-forge plan
agent-forge diff

agent-forge approve
agent-forge apply

agent-forge status
agent-forge drift
agent-forge rollback

agent-forge evaluate
```

For automation:

```bash
agent-forge plan --json
agent-forge diff --json
agent-forge apply --non-interactive
```

Human-readable output and machine-readable output should be first-class.

---

# 23. Proposed Package Structure

```text
src/agent_forge/
│
├── cli/
│
├── config/
│
├── models/
│
├── registry/
│
├── sources/
│
├── scanner/
│
├── adapters/
│
├── matching/
│
├── planner/
│
├── policy/              # NEW
│   ├── engine.py
│   ├── rules.py
│   └── permissions.py
│
├── apply/
├── rollback/
├── validation/
│
├── evaluation/          # NEW
│   ├── benchmark.py
│   ├── runner.py
│   ├── metrics.py
│   └── scorer.py
│
├── runtime/             # NEW / isolated
│   ├── agent.py
│   ├── session.py
│   ├── context.py
│   ├── execution.py
│   ├── tools.py
│   └── events.py
│
├── storage/
│
└── observability/       # NEW
    ├── logging.py
    ├── metrics.py
    └── tracing.py
```

---

# 24. Target Architecture

```text
                         ┌──────────────────────┐
                         │      CLI / API       │
                         └──────────┬───────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │       Orchestration Layer      │
                    └───────────────┬───────────────┘
                                    │
          ┌─────────────────────────┼─────────────────────────┐
          │                         │                         │
          ▼                         ▼                         ▼
   Capability Plane          Governance Plane          Runtime Plane
          │                         │                         │
   ┌──────┴──────┐           ┌──────┴──────┐           ┌──────┴──────┐
   │ Registry    │           │ Policy      │           │ Agent       │
   │ Scanner     │           │ Approval    │           │ Session     │
   │ Matching    │           │ Risk        │           │ Context     │
   │ Planner     │           │ Audit       │           │ Tools       │
   │ Adapters    │           │ Provenance  │           │ LLM         │
   └──────┬──────┘           └──────┬──────┘           └──────┬──────┘
          │                         │                         │
          └─────────────────────────┼─────────────────────────┘
                                    │
                             ┌──────▼──────┐
                             │ Transaction │
                             │   Engine    │
                             └──────┬──────┘
                                    │
                             ┌──────▼──────┐
                             │  Evaluation │
                             │    Engine   │
                             └──────┬──────┘
                                    │
                             ┌──────▼──────┐
                             │ Improvement │
                             └─────────────┘
```

---

# 25. Implementation Roadmap

## Phase 1 — Harden Current Core

**Priority: P0**

1. Formalize policy engine
2. Formalize transaction state machine
3. Strengthen dependency/conflict resolver
4. Strengthen permission model
5. Improve drift detection
6. Add comprehensive security tests
7. Add failure/recovery tests

Expected result:

> Stable and deterministic Capability Management Core.

---

## Phase 2 — Capability Intelligence

**Priority: P1**

1. Immutable capability identity
2. Provenance/trust states
3. Dependency graph
4. Capability versioning
5. Upgrade planner
6. Better registry APIs
7. Capability lifecycle

Expected result:

> Agent Forge becomes a real capability package manager.

---

## Phase 3 — Evaluation

**Priority: P1**

1. Benchmark model
2. Evaluation runner
3. Baseline comparison
4. Metrics
5. A/B capability testing
6. Regression detection
7. Promotion/deprecation workflow

Expected result:

> Agent Forge can measure whether a capability actually improves an Agent.

---

## Phase 4 — Runtime

**Priority: P2**

1. Agent abstraction
2. Session lifecycle
3. Context management
4. Tool execution
5. LLM provider abstraction
6. Execution policy
7. Event system
8. Memory abstraction

Expected result:

> Agent Forge becomes an Agent Platform without contaminating the existing capability core.

---

## Phase 5 — Enterprise / Ecosystem

**Priority: P3**

1. Remote registry
2. Private registry
3. Organization policies
4. Team-level governance
5. Central audit
6. OpenTelemetry
7. Web UI
8. Capability marketplace

Expected result:

> Multi-project / multi-team Agent Governance Platform.

---

# 26. What NOT to Do

## Do not rewrite the existing architecture

The current separation between:

```text
scanner
matching
planner
apply
rollback
validation
```

is valuable.

Refactor incrementally.

## Do not make LLM responsible for security decisions

Bad:

```text
LLM → decide whether capability is safe
```

Good:

```text
LLM recommendation
       ↓
deterministic Policy Engine
       ↓
approval
```

## Do not let upstream repositories execute installers

Continue the current principle:

```text
upstream source
      ↓
curation
      ↓
registry
      ↓
plan
      ↓
approval
      ↓
apply
```

## Do not automatically overwrite user-owned configuration

Continue hash-based and section-aware merge semantics.

---

# 27. Recommended Priority Matrix

| Feature | Priority | Impact | Complexity |
|---|---|---:|---:|
| Policy Engine | P0 | Very High | Medium |
| Transaction State Machine | P0 | High | Medium |
| Permission Model | P0 | Very High | Medium |
| Dependency Resolver | P1 | High | Medium |
| Capability Versioning | P1 | High | Medium |
| Drift Management | P1 | High | Medium |
| Evaluation Engine | P1 | Very High | High |
| Event Model | P2 | High | Medium |
| Agent Runtime | P2 | Very High | Very High |
| Memory | P2 | High | High |
| Remote Registry | P3 | Medium | High |
| Web UI | P3 | Medium | High |
| Marketplace | P3 | Medium | Very High |

---

# 28. Final Recommendation

The strongest direction for Agent Forge is not to become another generic Agent Framework.

Instead, position it as:

> **A capability, governance and lifecycle platform for AI coding agents.**

The differentiating architecture should be:

```text
CAPABILITY
    +
GOVERNANCE
    +
EVALUATION
    +
RUNTIME
```

with the first three layers forming the core value proposition.

The existing repository already provides a strong foundation for:

```text
Safety
Reproducibility
Explainability
Approval
Rollback
Platform adaptation
```

The next major milestone should therefore be:

```text
Current
Capability Installer
       ↓
Capability Manager
       ↓
Capability Governance
       ↓
Capability Evaluation
       ↓
Agent Platform
```

**Recommended immediate implementation order:**

```text
1. Policy Engine
2. Permission Model
3. Transaction State Machine
4. Dependency/Conflict Resolver
5. Capability Versioning
6. Drift/Upgrade Engine
7. Evaluation Engine
8. Event Model
9. Runtime abstraction
10. Memory / Multi-Agent
```

This preserves the current architecture while creating a clear path from a local CLI tool into a serious AI-agent infrastructure platform.
