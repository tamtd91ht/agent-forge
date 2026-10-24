# ADR-0013: Per-platform copies of an upstream asset must be byte-identical

Status: accepted (2026-10-24). Input: scouting report on `dietrichgebert/ponytail` (MIT,
v5.3.2), whose `scripts/check-rule-copies.js` byte-compares the seven host-specific copies of
its ruleset against `AGENTS.md` and pins a list of load-bearing phrases that must survive in
every copy.

## Context

A curated skill is shipped once per platform directory (`assets/claude_code/<name>/SKILL.md`,
`assets/codex/<name>/SKILL.md`, ...). For a `provenance: upstream` capability both copies are
by definition the upstream file, so they must agree byte for byte; today 220 such pairs do,
but nothing checks it. A hand edit to one copy, or a `scripts/curate.py` run interrupted
between platforms, would ship two different "verbatim" files and `validate` would stay green.
The two pairs that differ on purpose (`forge.managed-notice`, `uiux.guidelines`) are
workspace-authored or adapted per platform.

## Decision

- `validate` errors when an `upstream` capability has the same relative path under two
  platform directories with different bytes. Adapted and workspace capabilities are not
  checked: their per-platform differences are the adaptation.
- No manifest field: the provenance already says whether copies may differ. Upstream's
  phrase canary is not adopted; `provenance: upstream` plus the integrity pin already fixes the
  text, and an adapted capability records its edits in `scripts/curate.py`.

## Invariants kept

Deterministic and offline; computed from registry assets only. No new install kind, write
path or plan field; approval digests are unchanged.

## Out of scope

Copies across capabilities (a skill whose body mirrors a subagent's); comparing a copy with the
upstream checkout (`scripts/curate.py` + `git diff registry/` does that).
