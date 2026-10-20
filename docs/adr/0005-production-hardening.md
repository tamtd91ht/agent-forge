# ADR-0005: Production hardening of the core (vision Phase 0-1)

Status: accepted (2026-10-20). Input: [product-vision.md](../product-vision.md) and the
evidence audit in [engineering-roadmap.md](../engineering-roadmap.md).

## Context

The audit found the scan → plan → approve → apply → rollback core sound on the happy path but
unproven or weak where production use hurts: a crash mid-apply left an unrecoverable
transaction, two processes could write one project, an approval could be re-hashed by hand,
policy and plan age were not bound to approvals, curated content was never scanned, and
nothing measured whether recommendations stay right.

## Decisions

1. **Approval anchored in the workspace.** `approve` records the plan digest in
   `state/approvals/`; `apply` requires the plan's digest to equal it. The workspace is the
   trust anchor; keyed signatures are deferred until there is key management.
2. **Plans bind policy and age.** `policy_digest` (effective layers), `created_at` and
   `expires_at` (7 days) are digest inputs; the registry digest includes shipped policies.
   An invalid project policy fails closed.
3. **Journaled, locked writes.** One O_EXCL lock per project (owner pid, stale takeover)
   around apply and rollback. Each operation is journaled (before hash, exact backup hash,
   intended hash) before its write; rollback accepts interrupted/failed/partial transactions
   and resolves journaled operations from disk; a failed rollback marks the original
   `recovery_required` and can be resumed. Atomicity is documented as per file.
4. **Path hardening at write time.** Directories are created one by one and the chain is
   re-checked immediately before the rename; `.git`, case/Unicode aliases of existing
   entries, more Windows device names and malformed backup references are refused.
5. **Curated content is scanned and gated.** A deterministic content-safety scan runs in
   `validate`; findings are errors unless acknowledged with a reason. Integrity mismatches
   are rejected at plan time. `revoked` status, `replaced_by`, `risk_rationale` (above low)
   and SHA-only revisions are enforced; `agent-forge impact` traces installations.
6. **Measured resolver quality.** Reviewed example projects with expected profiles and
   recommendations; CI fails on drift. Adapters pass one conformance suite.
7. **Operational baseline.** CI matrix (Windows/Linux/macOS × Python 3.11/3.14), installer
   smoke tests, pip-audit, Dependabot, schema drift check, every exit code tested, unknown
   `schema_version`s refused, secrets redacted in the audit log, one version source.

## Invariants kept

Agent Forge remains the only writer into a project, through `apply`/`rollback` and
`filesystem_safety`. No LLM decides safety; the content scan and policy are deterministic.
Nothing writes outside the project and the workspace.

## Out of scope / deferred

HMAC or signed approvals and releases; a dependency lock file for the installer; the
capability value evaluation (designed in [evaluation.md](../evaluation.md)); dependency
version constraints and per-adapter tool-version ranges (ADR-0002); a uniform JSON envelope
for every `--json` command (breaking; planned for the first versioned release).
