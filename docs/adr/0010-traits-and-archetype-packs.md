# ADR-0010: Traits — content for projects that share a characteristic, not only a stack

Status: accepted (2026-10-22; the owner delegated the design after scouting a production
Claude Code configuration, see Context). Input: ADR-0003 (context cost), ADR-0007 (decision
records, lint), ADR-0008 (default-catalog criteria, proposed), product vision §6.1 (evidence
and confidence per detection) and §6.3 (profiles).

## Context

A real, hand-built Claude Code configuration for a multi-tenant CRM + VOIP platform (9
always-on rules, 167 skills, 23 subagents, 11 hooks, 340 commits) was scouted for Agent Forge.
Three kinds of content were found:

1. **Universal:** right for any backend (a credential-literal guard, a changelog gate, graceful
   shutdown, webhook signature verification). Ordinary catalog entries.
2. **Characteristic-bound:** right for every project that shares a *domain* characteristic,
   whatever its stack: tenant isolation for multi-tenant services, idempotency and locking for
   money, encryption tiers for PII, consumer safety for event-driven services, dialplan and CDR
   rules for telephony. The catalog had nothing of this kind: `applicability` knew languages,
   frameworks, project types and files, which are stack facts a manifest can show. "This
   project is multi-tenant" is not in any manifest.
3. **Product-specific:** module trees, cluster slots, environment-variable naming, internal
   review commands. A team registry (`docs/registries.md`), never the public catalog.

The second kind is the valuable one and the dangerous one. Valuable because a multi-tenant
leak or a double-charged wallet is the most expensive bug those projects ship, and the rules
that prevent them are the same everywhere. Dangerous because without a gate it would be
proposed to a CLI tool that has no tenants, and because a pack copied from one product carries
that product's identifiers unless it is deliberately generalised.

The owner's proposal was to keep this content as documentation the model reads to decide
whether a target project "looks like" the source project. That would put the decision back
into prose, which ADR-0007 removed: unverifiable, unrepeatable, silently drifting with the
model.

## Decisions

1. **A trait is a detected fact, like a framework.** `ProjectProfile.traits` lists domain
   characteristics with confidence and evidence (`models/project.py`). The scanner derives
   them from what the source shows: the share of sampled source files that mention a trait's
   identifiers (`tenantId` / `tenant_id` / `organizationId` …, `wallet` / `ledger` / `refund`
   …, `nationalId` / `dateOfBirth` / `gdpr` …, `SIP` / `dialplan` / `CDR` …), or an integration
   already detected as a framework (Kafka, RabbitMQ, Celery → `event_driven`). Thresholds are
   conservative; a single file is never a trait. Below 0.5 a trait is a warning for the team
   to confirm, exactly like a low-confidence language. The known traits are `multi_tenant`,
   `money`, `pii`, `event_driven`, `telephony` (`scanner/project_profile.py: TRAIT_NAMES`).
2. **The team has the last word, in a file.** `.agent-forge/profile.yaml` gains `traits:`
   (confirmed at confidence 1.0, with the file as evidence) and accepts trait names in
   `ignore:`. An unknown trait name is reported, not silently dropped. The agent running
   `/agent-forge-upgrade` does not assert traits in its decision record; if the scan missed
   one, it asks the user to confirm it in the profile. One source of truth, checkable.
3. **`applicability.traits` is one more dimension.** A capability listing traits applies when
   at least one of them is present (the same any-of semantics as `languages` and
   `frameworks`), and is `not_applicable` otherwise, with a reason that names the missing
   trait and the profile file. `decisions verify` therefore treats a trait-gated capability
   on a project without the trait as `stack_mismatch` without any new code. Trait-gated
   capabilities are never `always`, so ADR-0008's default set is untouched by them.
4. **A trait appearing or disappearing stales a plan.** The profile fingerprint includes the
   trait names when any are present; projects without traits keep the fingerprints they had.
5. **No bundle object.** "The multi-tenant pack" is the set of capabilities whose
   applicability names `multi_tenant`; `catalog` and the plan show them individually, each
   with its own evidence and cost. A bundle manifest would be a second thing to keep in sync
   for no decision it enables. Revisit when a pack needs ordering or shared dependencies.
6. **Generalise before curating.** A capability derived from a product configuration is
   curated only after every product identifier, module name, storage layout and internal
   process is removed, and its `review.rationale` says so. Evidence stays honest: "in daily
   use in one production codebase" is `review.notes`, not `review.evidence`; the harness
   decides `improved`.
7. **The first two packs ship with the mechanism**, so it is exercised end to end:
   `forge.skill.tenant-isolation` (`multi_tenant`) and `forge.skill.money-safety` (`money`),
   both on-demand skills, both with identical Codex copies, both proposed to a fixture only
   when its source shows the trait (`tests/unit/test_trait_packs.py`). Candidates for the next
   round, in order of the catalog gap they close: event-driven consumer safety and retry /
   DLQ (`event_driven`), PII encryption tiers and erasure (`pii`), telephony provisioning
   and CDR (`telephony`).

## Consequences

- A capability can now say "for multi-tenant services" and mean it; the engine, not the
  reader, decides whether a project is one, with the files that show it.
- The scanner reads up to 300 source files per scan (bounded by the existing walker limits);
  scans of large repositories grow by that read, measured in tens of milliseconds on the
  example fixtures.
- Trait detection is heuristic and documented as such (`docs/traits.md`). A wrong detection
  is cheap to fix (`profile.yaml`) and visible in every plan (`traits:` line, `not_applicable`
  reasons); a missed one costs an unproposed skill, not a wrong install.
- The scouted configuration's product-specific content stays where it belongs: it is the
  motivating case for a team registry (`roadmap-2026h2.md` 2.5) and for `agent-forge import`
  (`roadmap-decision-layer.md` 5.3), not catalog material.
- The same scouting produced three universal improvements that needed no new mechanism and
  shipped alongside: four `lint` checks (dead references, overclaimed counts, overlapping
  descriptions, missing frontmatter), the credential-literal hook, and the hook-authoring
  notes in `contributing-capabilities.md`.
