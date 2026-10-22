# Traits: domain characteristics the catalog can target

Languages, frameworks and project types say what a project is built with. A **trait** says
what the project *does*: serves several tenants, moves money, stores personal data, reacts to
messages, runs telephony. Some capabilities are right for every project with a trait and
wrong for every project without it, whatever the stack, so `applicability.traits` gates them
(ADR-0010).

## The traits

| Trait | What the scanner looks for | Capabilities gated by it |
|---|---|---|
| `multi_tenant` | identifiers such as `tenantId`, `tenant_id`, `organizationId`, `workspaceId` across sampled source files | `forge.skill.tenant-isolation` |
| `money` | `wallet`, `ledger`, `invoice`, `refund`, `payout`, `chargeback`, `settlement`, `billing`, `*MinorUnits` | `forge.skill.money-safety` |
| `pii` | `nationalId`, `dateOfBirth`, `passportNumber`, `ssn`, `gdpr`, `pii`, `personalData` | `forge.skill.pii-protection` |
| `event_driven` | a detected broker integration: Kafka, RabbitMQ, Celery | `forge.skill.event-consumer-safety`, `forge.skill.event-contract` |
| `telephony` | `SIP`, `dialplan`, `FreeSWITCH`, `FusionPBX`, `Asterisk`, `CDR`, `IVR`, `ringGroup`, `callerId` | (next round) |

`agent-forge scan` prints a `traits:` line when any is detected, with confidence and the
files that show it; `--json` carries them under `data.traits` like frameworks.

## How confidence is computed

The scanner reads up to 300 source files, spread round-robin across top-level directories so
a large first directory cannot hide the rest (bounded by the usual walker limits, secret-looking
files never read) and counts, per trait, how many mention one of its identifiers. The
**share** of files decides the confidence; thresholds are conservative on purpose:

| Trait | 0.8 at | 0.6 at | 0.4 (warning only) at |
|---|---|---|---|
| `multi_tenant` | ≥ 15 % | ≥ 6 % | ≥ 2 % |
| `money` | ≥ 8 % | ≥ 3 % | ≥ 1 % |
| `pii` | ≥ 6 % | ≥ 2 % | ≥ 0.5 % |
| `telephony` | ≥ 5 % | ≥ 2 % | ≥ 0.5 % |

A single matching file is never more than 0.4. `event_driven` is 0.85 when the broker
dependency is in a manifest. Below 0.5 a trait is reported as a warning ("confirm it in
`.agent-forge/profile.yaml`") and **not** used for recommendations, the same rule as a
low-confidence language.

This is a heuristic. A CLI that happens to name a variable `tenant_id` in four of its ten
files will be called multi-tenant; a multi-tenant service whose tenant column is named
`account_ref` will not. Both cases are visible (the `traits:` line, the `not_applicable`
reason naming the trait) and both are fixed in one file:

## Confirming or ruling out a trait

```yaml
# .agent-forge/profile.yaml
traits: [multi_tenant, money]     # confirmed: confidence 1.0, this file is the evidence
ignore: [telephony]               # ruled out: the detection is dropped
```

Unknown trait names are reported in the scan warnings and ignored. The agent running
`/agent-forge-upgrade` never asserts a trait on its own: if it believes the scan missed one,
it asks you to add it here, so that the profile stays the single, checkable source.

## For capability authors

```yaml
applicability:
  traits: [multi_tenant]          # applies when at least one listed trait is present
  tags: [multi-tenant, saas]      # still requestable with --want when the trait is absent
```

- Never combine `traits` with `always`; a trait-gated capability is by definition not for
  every project, and ADR-0008's default set excludes it.
- Content derived from one product must be generalised first (ADR-0010 decision 6): no
  module names, storage layouts, environment-variable schemes or internal commands. Say in
  `review.rationale` what was removed.
- Keep it on demand (a skill, or a rule with `paths:`): the trait says the project needs the
  rule, not that every session must pay for it.
- "Used in production at X" goes in `review.notes`; `review.evidence` is for the harness.

## What is not a trait

- A stack fact a manifest shows (a framework, a database driver): that is a `frameworks`
  entry, and the scanner records integrations there already.
- A team convention ("we review every PR"): that is the project's own instruction file, which
  the entry skill reads and cites as `covered`.
- Product-specific knowledge (module trees, cluster names, internal commands): a team
  registry layer (`docs/registries.md`), never the public catalog.
