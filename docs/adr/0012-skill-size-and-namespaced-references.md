# ADR-0012: SKILL.md size against post-compaction truncation; namespaced skill references

Status: accepted (2026-10-23). Input: scouting report on `obra/superpowers` (MIT, v7.0.1),
whose `tests/skill-size/test-skill-size.sh` and release notes (upstream issue #2481) record
the truncation, and whose skills refer to each other as `superpowers:<skill>`. Extends the
skill-call check of ADR-0003.

## Context

1. After a compaction, Claude Code re-attaches each invoked skill cut off at 20,000
   characters; anything past the cut is gone for the rest of the session unless the agent
   re-reads the file. Upstream reports a session that lost a "five fix rounds" limit this way
   and ran 18. The figure comes from upstream observation, not from Claude Code
   documentation. `ecc.tdd-workflow/SKILL.md` is 21,596 bytes today.
2. Plugin-packaged skills name each other with the plugin namespace (`superpowers:x`). A
   project-scoped install has no namespace, so the reference resolves to nothing, silently;
   ADR-0003's check only recognises the `Skill tool with "x"` form.

## Decision

- `validate` warns when a curated `SKILL.md` is at or above 20,000 bytes (bytes are stricter
  than characters). The remedy is moving content needed only sometimes into reference files,
  which the link check already covers. A warning, not an error: the limit is one platform's
  observed behaviour and the content still works before compaction.
- `validate` errors on a `ns:name` token in a curated `SKILL.md` (fenced code ignored) when
  `ns` is the capability's own `source.source_id` or `name` is a skill shipped anywhere in
  the registry. Module specifiers such as `bun:test` match neither and pass.

## Invariants kept

Deterministic and offline; computed from registry assets only. No new install kind, write
path or plan field; approval digests are unchanged.

## Out of scope

Size limits of other harnesses; rewriting upstream text automatically (adaptation stays a
reviewed entry in `scripts/curate.py`).

## Follow-up (2026-10-23)

Nine ECC skills were over the cut. They are optimised, not shortened: `scripts/curate.py`
gains `Split` entries (`ECC_SPLITS`) that move situational sections - topic-specific
examples, cheat sheets, sources - verbatim into `references/`, keep the heading with a
"Read references/x.md when ..." pointer, and re-point in-document anchor links. A heading
missing upstream fails the run. Every upstream line is still shipped; the capabilities are
`adapted` at 1.1.0 and all `SKILL.md` files are under 17,500 bytes.
`test_real_registry_is_valid` now fails on any size warning.
