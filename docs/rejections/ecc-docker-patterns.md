# ECC `skills/docker-patterns`

Source: `ecc` — `skills/docker-patterns/SKILL.md`.

## Decision

Rejected (0.4.0 stack curation).

## Why

Most of the skill is sound Docker / Compose guidance, but one section is ECC-specific
operations: it installs the Codex CLI globally inside a harness image, runs ECC's own
`codex-auth-relay.js` from `/ecc/docker/`, and stores a credential copy in the container's
`~/.codex/auth.json`. Two `global-config-write` content-safety findings point exactly there.
Curating it would mean either acknowledging a login procedure for someone else's
infrastructure or cutting a large block by hand; `ecc.deployment-patterns` covers Docker
and CI/CD for projects that have a Dockerfile.

## Revisit when

Upstream splits the ECC harness operations out of the general Docker skill.
