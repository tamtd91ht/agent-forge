# Deprecation, revocation and replacement

How a curated capability leaves the catalog, and what users see. The engine already knows the
states (`deprecated`, `revoked`, `replaced_by`, ADR-0005 §5); this page is the human process.

| State | Meaning | New installs | Installed copies | Shown by |
|---|---|---|---|---|
| `curated` | reviewed, installable | yes | — | — |
| `deprecated` | superseded or no longer maintained; `replaced_by` names the successor when there is one | no | keep working; `upgrade` does not touch them | `status` (yellow line), `check` warning, `validate` warning |
| `revoked` | withdrawn for cause (security, licence, harmful content) | no | reported as an **error**; CI `check` fails | `status` (red line), `check` failure, `validate` error |
| `rejected` | never curated | no | n/a | catalog only |

## Notice periods

- **Deprecation:** announced in `CHANGELOG.md` and in the manifest (`status: deprecated`,
  `replaced_by`, a `review.notes` entry with the reason and date) at least **one minor
  release (≥ 30 days)** before the directory is removed from the registry. During that
  period `catalog show` still works and `remove` plans still resolve.
- **Revocation:** immediate. The manifest flips to `revoked` with the reason in
  `review.notes`; a security revocation also gets a GitHub security advisory
  (`SECURITY.md`). Installed projects see an error on the next `status`, `check` or
  `validate`; the fix is `agent-forge remove . <id>` (or installing `replaced_by`).
- **Replacement:** a new id, not a new version, when the content, source or licence changes
  materially. The old entry is deprecated with `replaced_by: <new id>`; `status` prints the
  hint, and `forge` offers the successor through the usual matching.

## Who decides

A maintainer opens a PR that changes the manifest status and the changelog; a second
maintainer approves (CODEOWNERS). Revocations may be merged by one maintainer and reviewed
after the fact when the cause is a security problem.

## What users do

```bash
agent-forge status .            # deprecated / revoked lines name the replacement
agent-forge remove . <id>       # plan the removal, then approve + apply
agent-forge forge . --request <replaced_by>   # install the successor
```

`sync` and `check` never silently remove or replace anything; a revoked capability makes
`check` fail until a human runs `remove`.
