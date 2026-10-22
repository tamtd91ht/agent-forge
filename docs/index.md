# Agent Forge

Set up Claude Code, Codex, Cursor, GitHub Copilot or Gemini CLI for a project with reviewed
skills, rules, subagents, hooks and MCP servers, chosen for the code and installed only after
you say yes. Every install is a plan with a digest-bound approval and a journaled transaction
that `rollback` can undo.

- **Install:** run the one-line installer in a project root, then `/agent-forge-upgrade`
  ([getting started](getting-started.md), quickstarts for [Node](quickstart/node.md),
  [Python](quickstart/python.md), [Go](quickstart/go.md), [Java](quickstart/java.md)).
- **Teams:** `sync` for fresh clones, `check` as a CI gate, committed approval files, a team
  registry and policy ([team workflow](team-workflow.md)).
- **Platforms:** one canonical content, rendered per tool ([adapters](adapters.md),
  [ADR-0006](adr/0006-canonical-format-and-adapters.md),
  [ADR-0007](adr/0007-decision-layer.md); [ADR-0008](adr/0008-default-catalog-criteria.md) is proposed).
  The decision layer's tracked checklist: [roadmap-decision-layer.md](roadmap-decision-layer.md).
- **Traits:** capabilities for what a project *does* (multi-tenant, money, PII, event-driven,
  telephony), gated by what its source shows ([traits](traits.md),
  [ADR-0010](adr/0010-traits-and-archetype-packs.md)).
- **Evidence:** the opt-in evaluation harness and what has (not yet) been measured
  ([evaluation](evaluation.md)).
- **Direction:** the [6-month plan](roadmap-2026h2.md) and its status.

Source, releases and issues: [github.com/tamtd91ht/agent-forge](https://github.com/tamtd91ht/agent-forge).
