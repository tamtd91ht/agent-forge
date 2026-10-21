# Contributing a capability

The catalog must not depend on one person's taste. This is the process a capability goes
through from a pull request to `curated`, and what CI checks automatically so reviewers can
spend their time on judgement.

## Before you open the PR

1. Read [source-curation.md](source-curation.md) (what is curated and why),
   [capability-model.md](capability-model.md) (the manifest) and
   [rejections/](rejections/README.md) (what was already declined, with reasons).
2. Check the licence allows redistribution and keep the upstream notice file in `assets/`
   (`license.notice_file`). CI fails when the notice is missing.
3. Author the content in the canonical formats (Claude Code layout, [ADR-0006](adr/0006-canonical-format-and-adapters.md))
   and point every platform that can express it at the same asset.

## What the PR contains

```
registry/capabilities/<id>/capability.yaml     status: under_review (curated only after review)
registry/capabilities/<id>/assets/...          content + licence notice
docs/rejections/<id>.md                        only if you looked at a sibling and left it out
CHANGELOG.md                                   one line under "Added (source: <name>)"
```

Use the PR template (`.github/PULL_REQUEST_TEMPLATE.md`). Run locally:

```bash
.venv/Scripts/python scripts/pin_integrity.py            # pins assets_sha256
.venv/Scripts/agent-forge validate                        # schema, links, content safety, licence notice, deps
.venv/Scripts/python -m pytest -q tests/conformance       # every destination renders for its platform
```

Line endings: `.gitattributes` stores every text file as LF, and the pinned digest is
computed from those bytes. On Windows set `git config core.autocrlf false` in this clone (or
keep the default and never pin from a CRLF working copy: `pin_integrity.py` refuses one).
If `git ls-files --eol registry | grep crlf` prints anything, run
`git add --renormalize . && git checkout -- registry` before pinning.

## What CI checks (no reviewer time)

| Check | Where | Fails when |
|---|---|---|
| Manifest schema, `extra: forbid`, id = directory, semver | `validate` | any field is unknown or malformed |
| `source.revision` is a 40-hex SHA; provenance | `validate` (local, with checkouts) | revision or paths are not in the checkout |
| Content safety (pipe-to-shell, broad deletes, sudo, credentials, instruction overrides) | `validate` | a finding is not acknowledged with a reason |
| Licence notice present, `redistribution_ok: true` for curated | `validate` | notice file missing |
| Relative links, skill-to-skill calls, dependency cycles and version constraints | `validate` | any broken |
| Integrity pin matches assets | `validate`, `pin_integrity.py --check` (own CI job) | assets changed after pinning |
| Registry files are LF | `registry-integrity` job | a CRLF file is committed (the pin would match no clone) |
| Risk rationale above `low` | `validate` | missing |
| Every destination renders and passes its adapter's rules | `tests/conformance` | a platform cannot express the kind |
| Example projects still match their reviewed expectations | `scripts/matching_report.py` | the resolver's choices changed |

## Review (two humans)

CODEOWNERS requires two reviewers for `registry/`. Reviewers check what CI cannot:

- Is the content genuinely useful for the kind of project `applicability` targets, and is
  `benefit_score` honest?
- Does it duplicate an existing entry (declare `conflicts` / `equivalents`)?
- Is the always-loaded context (`ctx` in a dry-run plan) worth it?
- Do `risk`, `grants` and `permissions` describe what the content can make the agent do?
- Is `review.rationale` something a reader a year from now can understand?

One reviewer sets `status: curated`, `review.signed_off_by` and `signed_off_at` in the final
commit. Evidence of value ([evaluation.md](evaluation.md)) is welcome but not required for
`curated`; without it, `catalog show` says the value was not measured.

## After merge

- A new source gets a row in `sources/sources.yaml` and a `docs/source-curation.md` section.
- Deprecation and revocation follow [deprecation-policy.md](deprecation-policy.md).
