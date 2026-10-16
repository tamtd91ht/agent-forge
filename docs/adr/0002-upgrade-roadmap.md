# ADR-0002: Response to the upgrade proposal (governance first, no runtime)

Status: accepted (2026-10-16). Input: `AGENT_FORGE_UPGRADE_PROPOSAL.md` (review written from
README/docs, not from the code). This ADR records what was adopted, what already existed,
and what is rejected, so the proposal is not re-litigated.

## Adopted and implemented

| Proposal item | Decision | Implementation |
|---|---|---|
| P0 Policy engine | adopted | `policy/engine.py`: layered YAML (`registry/policies/default.yaml` → `<workspace>/policy.yaml` → `<target>/.agent-forge/policy.yaml`), strictest verdict wins, evaluated after applicability and before scoring. Verdicts: allow / require_request / deny. `agent-forge policy [PATH]` shows layers and per-capability verdicts. |
| P0 Permission model | adopted | `Capability.grants` (process_execute, network_access, secrets_read, filesystem_write) with kind-derived defaults (`effective_grants`); policy `grants:` rules act on them. Free-form `permissions` tags stay for reports. |
| P1 Registry as addressable artifact | adopted (minimal) | `integrity.assets_sha256` pinned per capability by `scripts/pin_integrity.py`; `validate` errors on mismatch. Registry digest already covered everything. |
| P1 Trust / sign-off | adopted (minimal) | `review.signed_off_by` / `signed_off_at`; policy `require_signoff: true` denies unsigned entries; `doctor` reports the count. No new lifecycle states: the existing five plus sign-off are sufficient. |
| P1 Transaction state | adopted (minimal) | transactions now record `registry_digest` and `profile_fingerprint`. The existing six states already cover the proposed machine. |
| P1 Drift management | adopted | `drift` (expected/actual per file, section, merged entry) and `repair --strategy restore\|unmanage`, both plan-based with approval. |
| P1 Event model | adopted (local) | append-only `state/audit.jsonl` (`storage/audit.py`): PlanCreated/Approved/Revoked, TransactionCompleted, RollbackCompleted. `agent-forge audit` reads it. No broker. |
| P2 Lifecycle `remove` | adopted | `remove PATH ID...`: plan that deletes managed files, sections and merged entries; refuses modified files unless `--keep-modified`; refuses when dependants remain. |
| P3 CLI `doctor` | adopted | tools on PATH, workspace, registry, pins, sign-off, policy layers, audit log. |

Also fixed while implementing: dependencies rejected by policy (or any hard rule) can no
longer be pulled back in by a dependant; `remove`/`repair` operations carry a platform so
pre-flight scope checks apply to them.

## Already present (proposal under-credited the code)

Dependency graph with cycle detection and transitive resolution; symmetric conflicts;
equivalents; hash-bound approvals; atomic writes with backups; section- and entry-aware
rollback; hooks and MCP behind separate approval classes (ADR D13); project-aware matching.

## Rejected or deferred

- **Runtime Plane (agent, session, context builder, memory, LLM provider, tool sandbox):**
  rejected for this repository. The master prompt fixes Agent Forge as a capability /
  governance tool with a deterministic core; a runtime would double the attack surface and
  the dependency set. If one is ever built it consumes the registry from a separate package.
- **Evaluation engine:** deferred. Measuring "did the capability improve the agent" needs
  real LLM sessions (cost, non-determinism). When added it will be opt-in, local-only, driving
  `claude -p` / Codex CLI on benchmark repos, and never a gate for curation.
- **Version constraints / optional dependencies:** deferred until a second version of any
  capability exists.
- **Remote / enterprise registry, Web UI, marketplace, OpenTelemetry:** deferred; local-first
  is the product. JSON audit log is the hook for later exporters.
- **Six-state trust ladder:** rejected in favour of `signed_off_by` + policy
  `require_signoff`.

## Consequences

- A project can now say "no hooks, no MCP, deny `rea.*`" in a 5-line YAML and every plan
  honours it, including `forge --yes`.
- Curated content is tamper-evident (pins) and auditable (log), without any service.
- Human sign-off is visible (0/20 today) and can be made mandatory per organisation.
