# ADR-0003: Always-loaded context as a measured cost; skill calls must ship with the caller

Status: accepted (2026-10-20). Input: scouting report on `mattpocock/skills` (MIT), whose
`.agents/invocation.md` and `writing-for-agents` skill treat context load as a design budget
and write cross-skill calls as `Call the Skill tool with "X"`.

## Context

1. Every model-invoked skill and subagent puts its name and description into the agent's
   context on every turn; so does every rule without a `paths:` scope and every section merged
   into `CLAUDE.md` / `AGENTS.md`. Agent Forge installed these without saying what they cost.
   A real plan for a small Python backend adds ~15k characters, 11k of them from one
   capability (`ecc.rules.common`). The evaluation engine that would measure benefit is
   deferred (ADR-0002); the cost side can be measured statically today.
2. Skills increasingly compose: one skill tells the agent to call another through the Skill
   tool. If the called skill is not installed, or is user-invoked (`disable-model-invocation`,
   reachable only by the human), the instruction silently fails at runtime. Upstream fixed the
   same bug class by hand (mattpocock/skills #880). This is the skill-level twin of the broken
   relative links `validate` already catches.

## Decision

- `registry/context_load.py` computes, per capability and platform, the characters added to
  every turn: name + description of each `SKILL.md` (0 when `disable-model-invocation: true`)
  and of each `.claude/agents/*.md`; the body of `.claude/rules/**/*.md` without `paths:`;
  the full text of `append_section` destinations. Skill bodies, reference files, hooks and MCP
  configs count 0.
- Plans carry `SelectedCapability.context_chars` (part of the approval digest because it is in
  `selected`); the plan table shows a `ctx` column and the total.
- Policy gains `max_context_chars` (per capability, default `null`). Above it the verdict is
  `require_request`, like any other tightening; layers combine strictest-wins.
- `validate` errors when a curated `SKILL.md` calls a skill (`Skill tool with "x"` /
  `twice, for "x" and "y"`, fenced code ignored) that neither its capability nor its
  transitive `dependencies` ship, or that is user-invoked.

## Invariants kept

Deterministic and offline: no LLM, no tokenizer, no network; computed from registry assets
only. Approval semantics unchanged: the new field is derived from content the digest already
covers. No new install kind or write path.

## Out of scope

Token counts for a specific model; MCP tool-definition cost (unknown until the server runs);
a plan-wide budget (per-capability is enough to steer, the total is reported); measuring
whether the context pays off (still the deferred evaluation engine).
