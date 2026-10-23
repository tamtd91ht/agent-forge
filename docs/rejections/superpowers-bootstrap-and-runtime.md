# obra/superpowers bootstrap hook, brainstorming companion and session diagnosis

Source: `superpowers` (tag v7.0.1) — `hooks/` (`session-start`, `run-hook.cmd`,
`hooks.json`), `skills/using-superpowers`, `skills/brainstorming` (+ `scripts/server.cjs`),
`skills/diagnosing-superpowers`, `skills/writing-skills`, the per-harness plugin manifests.

## Decision

Not curated.

## Why

- **Bootstrap:** the SessionStart hook runs an upstream bash script (through a cmd/bash
  polyglot) and injects the whole of `using-superpowers` into every session and after every
  compaction. Upstream hook scripts are excluded (ADR-0001 D13), and the injected text is
  ~3.2 KB of always-loaded context whose rule ("1% chance a skill applies → you MUST invoke
  it") is a cost ADR-0003 asks to measure, not to force. `using-superpowers` also routes to
  skills that are not curated.
- **brainstorming:** the optional visual companion is a Node server that loads a logo from
  primeradiant.com by default as usage telemetry (opt-out env vars). The skill text depends
  on it and on `writing-plans`.
- **diagnosing-superpowers:** reads session transcripts outside the project and drafts or
  files issues on `obra/superpowers` with `gh`/`curl`; it diagnoses Superpowers itself.
- **writing-skills:** for skill authors, not projects; `references/anthropic-best-practices.md`
  has unverified origin and `CLAUDE_MD_TESTING.md` targets `~/.claude/skills/`.
- **Plugin manifests:** replaced by Agent Forge packaging.

## Revisit when

The bootstrap: never as a hook; a project that wants a skill-first rule can get a reviewed,
marker-delimited `section_merge`. Brainstorming: when the companion is optional in the skill
text and telemetry is off by default.
