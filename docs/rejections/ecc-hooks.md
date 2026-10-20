# ECC hooks and hook scripts

Source: `ecc` — `hooks/`, `scripts/hooks/*.js`.

## Decision

Not curated. Agent Forge ships its own workspace-authored hooks instead (`forge.hook.*`).

## Why

They execute `node -e` bootstraps, run `npx tsc` and formatters, probe HTTP endpoints, write
session state under `~/.claude`, and gate edits. Each of these breaks an ADR-0001 invariant
(no global writes, no upstream code at runtime) or needs a runtime Agent Forge does not own.

## Revisit when

Never as upstream code. A single behaviour can be re-implemented as a stdlib, single-file
hook (see ADR-0001 D13).
