# ECC per-language rules

Source: `ecc` — `rules/<language>/`.

## Decision

Deferred, not rejected.

## Why

Useful, but every file "extends ../common/…" and needs path globs; it has to be curated as
one capability per language with a dependency on `ecc.rules.common`.

## Revisit when

v0.2 curation; each pack must carry `paths:` frontmatter so it costs no always-loaded context
(see ADR-0003).
