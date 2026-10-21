# ECC per-language rules

Source: `ecc` — `rules/<language>/`.

## Decision

**Curated in 0.4.0** as `ecc.rules.<language>` (21 packs: golang, typescript, python, java, kotlin, rust, csharp, php, ruby, swift, dart, cpp, react, vue, nuxt, angular, react-native, web, fsharp, perl, arkts). `hooks.md` of every pack stays excluded (it documents ECC's own hooks in `~/.claude/settings.json`). The original reasoning is kept below.

Deferred at first, not rejected.

## Why

Useful, but every file "extends ../common/…" and needs path globs; it has to be curated as
one capability per language with a dependency on `ecc.rules.common`.

## Revisit when

v0.2 curation; each pack must carry `paths:` frontmatter so it costs no always-loaded context
(see ADR-0003).
