# mattpocock/skills setup skill and the skills that need it

Source: `mattpocock` — `setup-matt-pocock-skills`, `to-spec`, `to-tickets`, `triage`,
`wayfinder`, `implement`, `implement-spec`, `ask-matt`.

## Decision

Not curated.

## Why

`setup-matt-pocock-skills` writes an `## Agent skills` block into `CLAUDE.md` / `AGENTS.md`
outside Agent Forge markers, writes `docs/agents/*.md`, and runs `gh label create` /
`glab label create` (network, remote side effects). The other skills hard-depend on that
configuration (upstream ADR 0001) and publish to the issue tracker. `ask-matt` is a router
over the upstream set and would point at skills that are not installed.

## Revisit when

Agent Forge can express "per-project configuration a skill needs" as a reviewed,
marker-delimited section; then the setup step becomes a `section_merge` capability.
