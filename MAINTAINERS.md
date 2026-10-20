# Maintainers

Agent Forge is opened to teams outside its author only when **at least two people** can
merge and release independently (6-month plan, phase 4; the single biggest risk in the
plan is bus factor = 1). This file is the roster and the rules; `.github/CODEOWNERS` mirrors
it.

| Role | Person | Since | Can |
|---|---|---|---|
| Maintainer (author) | @tamtd91ht | 2026-10 | merge, release, curate, revoke |
| Maintainer 2 | _open_ | | merge, release, curate, revoke |
| Maintainer 3 | _open_ | | merge, release, curate |

## Rules

- **Merging:** every PR needs one approval from a maintainer who did not write it;
  `registry/` and `src/agent_forge/{apply,rollback,adapters}/` need two.
- **Releasing:** any maintainer may tag; the release after a maintainer joins is made by
  that maintainer (the process in `docs/operations.md#release-process` must work for them
  without help).
- **Revocation:** one maintainer may revoke for a security cause and open the advisory; a
  second reviews within a week.
- **Issue duty:** weekly rotation; the person on duty triages new issues, answers the
  `docs-watch` issue and the Dependabot PRs.
- **Stepping down:** open a PR removing yourself here and from CODEOWNERS; the remaining
  maintainers must still number two, otherwise the catalog is frozen (no new `curated`
  entries) until a replacement joins.

## Becoming a maintainer

Three merged contributions (capability submissions or engine changes) reviewed by the
current maintainers, then a PR adding yourself here and to CODEOWNERS, approved by every
current maintainer.
