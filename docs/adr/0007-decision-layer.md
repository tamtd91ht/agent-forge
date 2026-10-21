# ADR-0007: The decision layer — evidence-checked assessments, lint, usage, required policy

Status: accepted (2026-10-21). Input: the owner's upgrade checklist and the negative-first
rubric for the entry skill (`docs/history/agent-forge-upgrade-checklist.md`,
`docs/history/SKILL-section-3-4-rubric.md`), ADR-0003 (context cost), ADR-0004 (the skill is
the entry point), ADR-0005 (deterministic safety, no LLM decides it).

## Context

Since ADR-0004 the product is "the project's own agent reviews the project and drives the
engine". The engine was fully auditable (plans, digests, transactions) but the review was
not: the agent's SKIP / ADD reasoning lived only in the conversation, could cite files that
do not exist or quote lines that were never there, and nothing recorded why a capability is
absent, whether that reason still holds a month later, or whether the model changed its mind
on an unchanged project. The installer could also silently fall back to an unpinned branch
when no release resolved, which cost trust before the review even started. Finally,
"fewer is better" had no measurement: once installed, nothing said whether a skill was ever
used.

The positioning behind this ADR: Agent Forge is not the largest collection but the **smallest
measured one**, plus an agent that gives an independent, checkable assessment per project.
Every decision is recorded, reproducible for an unchanged project, and reversible.

## Decisions

1. **The assessment is data, not prose.** The entry skill assesses every capability on one
   fixed rubric, grounds-to-skip first (`covered`, `conflicts`, `security`, `context_cost`,
   `stack_mismatch`, `evidence_worse`, `duplicate_tool`, `unused`), each ground with the
   evidence it requires, then the gap, then cost / risk / evidence copied from the catalog.
   It writes `<project>/.agent-forge/decisions/<plan-id>.json` (`models/decision.py`,
   `registry/schema/decisions.schema.json`). This is the one file the skill writes; the
   engine never produces or edits it, so the "engine is the only writer" invariant of
   ADR-0001 is unchanged: the record is the agent's own output, like the conversation.
2. **The engine verifies what a program can verify, and downgrades what it cannot.**
   `agent-forge decisions verify` checks that cited paths exist inside the project (through
   `filesystem_safety`, so a citation can never read outside it), that quotes are real
   substrings, that `context_chars` and `evidence` match the catalog, that each ground
   carries its evidence (a `security` ground needs declared permissions, a `stack_mismatch`
   needs applicability to fail, an `unused` ground needs the usage log), and that policy is
   respected. A SKIP or REMOVE that fails becomes **ASK** ("the agent wanted to leave X out
   but could not prove why"); a SKIP of a `required` capability becomes ADD; an ADD of a
   denied one becomes SKIP. Recorded and effective verdicts are both reported; nothing is
   rewritten.
3. **Plans bind to the record.** `forge --decisions FILE` runs the verification, turns
   effective SKIP / REMOVE into exclusions and effective ADD into requests, refuses a real
   run while an ASK is unanswered (the user answers with `--exclude` / `--request`, which
   win per id), and stores the record's digest in the plan (`Plan.decisions_digest`, part of
   the content digest when present). `status` lists what is absent by decision and why;
   `drift` reports a decision whose cited file or line disappeared; `decisions diff` shows
   only the verdicts that changed between two records, with the old and the new reason.
4. **Policy has three levels.** `capabilities.required` (always planned when installable,
   never excludable by flag or by the agent, `check` fails when missing), the default
   (recommended: the developer wins), and `capabilities.forbidden` (an alias of `deny`).
   Changing a required entry is a reviewed policy change, not a conversation.
5. **`agent-forge lint` is the frictionless entry.** Read-only, no workspace, no catalog, no
   LLM: always-loaded context per file and in total, duplicate paragraphs and near-duplicate
   rule files, credentials in agent files and MCP configs, hooks whose commands trip the
   content-safety rules, MCP servers defined but disabled. It proposes no capability.
   Contradictions between rules need judgement and stay with the skill's `conflicts` ground.
6. **Usage is measured locally, opt-in.** `forge.hook.usage-log` (Claude Code `PostToolUse`
   on Skill / Agent) appends id, kind, timestamp and a short session id to
   `.agent-forge/usage.jsonl`; nothing else is recorded and nothing leaves the machine.
   `agent-forge usage` and the `unused` hint in `status` read it; a capability counts as
   unused only after 14 observed days with zero invocations. Rules and sections are
   always-on and never "invoked".
7. **The installer is safe by default.** It installs a GitHub Release, verifies the wheel's
   SHA-256 against the release's `SHA256SUMS` (and its Sigstore bundle when `cosign` is
   present), writes `~/.agent-forge/VERSION`, and stops with exit 1 when no release can be
   resolved. `AGENT_FORGE_REF` installs an unverified archive for development only and says
   so. A separate CI job keeps the registry LF and its pins true, because a pin computed from
   a CRLF working copy matches no clone.

## Consequences

- An outsider can run `lint` on any repository and get a true finding without installing
  anything; the catalog earns trust before it proposes.
- `decisions verify` measures the model's fabrication rate directly: the share of SKIPs
  downgraded to ASK is a KPI for the pilots and for every change to the skill's prompt.
- Decision records across repositories feed `decisions report --org` and the catalog review
  of ADR-0008; the default catalog shrinks by data, not opinion.
- The skill grew from 6.5k to 13k characters, all on demand (user-invoked, zero always-on
  context); its Codex copy stays byte-identical.
- Out of scope here: `agent-forge import` (bringing hand-written config under management),
  behaviour probes after install, canary rollouts; see `docs/roadmap-decision-layer.md`.
