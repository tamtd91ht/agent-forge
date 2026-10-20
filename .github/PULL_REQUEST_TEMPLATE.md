<!-- Delete the section that does not apply. -->

## Engine / docs change

- What changed and why (link the ADR or roadmap item):
- Proving test (a failing test first for engine behaviour):
- [ ] `/verify` (ruff, pytest, validate, schema check, matching report) is green
- [ ] CHANGELOG.md updated under `Unreleased`
- [ ] Any new write path lives in `apply/engine.py` or `rollback/engine.py` and has tests in `tests/security/` and `tests/integration/`

## Capability submission (`registry/capabilities/<id>`)

See [docs/contributing-capabilities.md](../docs/contributing-capabilities.md).

- Capability id and kind:
- Upstream source, commit SHA and licence:
- Why it belongs in the catalog (one paragraph; this becomes `review.rationale`):
- Platforms it targets and the destination for each:
- [ ] `status: under_review` (a reviewer sets `curated` + `signed_off_by`)
- [ ] `scripts/pin_integrity.py` run; `agent-forge validate` clean (content safety, licence notice, links)
- [ ] `tests/conformance` green (every destination renders for its platform)
- [ ] Siblings that were looked at and left out have a record in `docs/rejections/`
- [ ] CHANGELOG line under `Added (source: …)`

Two reviewers from CODEOWNERS are required for `registry/`.
