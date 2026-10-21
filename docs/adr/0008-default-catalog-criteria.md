# ADR-0008: What earns a place in the default catalog

Status: **proposed** (2026-10-21). Becomes accepted when the evaluation harness has run on
the five core capabilities (`docs/evaluation.md`) and the first pilot decision records exist.
Input: ADR-0007 (decision records, usage log), ADR-0002 (evaluation stays opt-in),
`docs/history/agent-forge-upgrade-checklist.md` §3.1.

## Context

The default catalog is what `forge` proposes to a project that asks for nothing in
particular. Today 34 curated capabilities qualify by review alone; none has evaluation
evidence (`review.evidence`), and nothing measures whether the agent, given the rubric of
ADR-0007, keeps skipping an entry for the same reason in most projects. A catalog that only
grows loses the positioning "the smallest measured collection".

## Decision (proposed)

A capability is in the **default** set (planned without `--want` / `--request`) only when all
of the following hold; otherwise it is `experimental`: still installable by request, never
proposed by itself.

1. **Evidence:** at least one `review.evidence` entry with verdict `improved` on a fixture of
   the same stack, from the harness in `tools/agent-forge-eval` (≥ 3 runs per arm). Two
   measurements ending in `no_evidence` demote the entry to `experimental`.
2. **Context:** always-loaded `context_chars` below the catalog threshold (proposal: 2,000;
   the team policy template sets 4,000 per capability).
3. **No conflict** with another default capability of the same profile (declared
   `conflicts`, or both covering the same gap).
4. **Owner:** `review.signed_off_by` is a person, with a date.
5. **Falsifiable:** the manifest lists, in `review.notes`, which rubric ground would make the
   agent skip it (for example `covered` by a project's own review rule), so a decision record
   can contradict it.
6. **Used:** across the organisation's decision records (`decisions report`), it is not
   skipped as `covered` in ≥ 70% of the repositories that assessed it, and, where the usage
   log exists, not `unused` in most of the repositories that installed it.

Target size of the default set: **≤ 15** capabilities. Review quarterly, with the
`decisions report --org` table and the evaluation results as the only inputs.

## Consequences (when accepted)

- `validate` warns for a `curated` capability that fails a criterion; `catalog` gets a
  `--default` filter; `forge` reports `experimental` entries under their own category.
- Curation PRs carry the evidence link; a capability can leave the default set without
  leaving the catalog.
- `docs/pilots/` records the decision as part of the pilot retrospective (ADR-0009).
