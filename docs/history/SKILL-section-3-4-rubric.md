> Historical input (2026-10-21): the drop-in rubric for sections 3-4 of the entry skill. Incorporated, with the record format adjusted, into `forge.skill.agent-forge-upgrade` 2.1.0 (ADR-0007). Not maintained.

# Replacement for `## 3` and `## 4` of `agent-forge-upgrade/SKILL.md`

Drop-in text. Sections 0–2 and 5 stay as they are. Design intent, for the reviewer of this change:

- The developer running the skill decides; this skill's job is the most honest assessment it can
  give, not a recommendation to install.
- Reasons to SKIP are collected **before** reasons to ADD, because the model's default bias is to add.
- Every capability is assessed on the **same fixed rubric**, so the user compares columns, not prose.
- The rubric is emitted as a decision record (`decisions.json`) so `status`, `drift`, the
  golden-decision tests and the org-wide decision report can read it.
- Two inputs are optional and used only when the engine provides them: `AF lint . --json`
  (contradictions, duplicates and context totals in the existing config) and `AF usage . --json`
  (which installed skills/agents were actually invoked, from the opt-in local session hook). Engine support for `--decisions` is checklist item 1.6; until it
  lands, the file is written next to the plan and ignored by the engine.

---

## 3. Assess, capability by capability

Assess every capability the baseline plan selected, every rejected one whose category is
`equivalent_exists`, `optional`, `not_applicable` or `needs_approval`, and every capability
already installed (for UPGRADE / REMOVE).

If the project has hand-written agent config that no capability manages (`CLAUDE.md` sections,
`.claude/rules/*.md` not in `managed.json`), do not propose rewriting it. Mention once that
`AF import .` can bring it under management as `<project>.local` with the same hashing and
rollback, and move on. Leave `policy_denied` and
`policy_requires_request` as they are: policy is the user's, not yours.

Work through the steps **in this order** for each capability. Do not skip to the verdict.

### 3.1 First, look for the reason not to install it

A reason to skip counts only if it is one of the grounds below **and** carries the evidence that
ground requires. Anything else is written as `none found`, never as a skip. Do not invent a
ground to reject a capability you dislike; do not soften one you can prove.

| Ground (`grounds` value) | Required evidence |
|---|---|
| `covered` | path of an existing file that does the same job + one quoted line from it. A matching name is not coverage; open the file. |
| `conflicts` | path + quoted line of the project convention, and the line in the capability it contradicts |
| `security` | the manifest field (`permissions`, hooks, MCP network/process) + the project rule or policy line that forbids it |
| `context_cost` | `context_chars` from the catalog, always-on or on-demand, and the budget or total it would exceed |
| `stack_mismatch` | the `applicability` field vs `scan --json` (language, framework, project type) |
| `evidence_worse` | `review.evidence` verdict `worse` on a fixture of the same stack |
| `duplicate_tool` | an entry in `.mcp.json` / `settings.json` / `package.json` that already provides the tool |
| `unused` | (installed capabilities only) `AF usage` shows zero invocations over the recorded window; state the window. Not applicable to always-on rules, which are never "invoked" |

Not grounds: "the project does not need it" without a path; "too heavy for the team" unless
stated as `context_cost` or `security`; anything you cannot point at.

Only after the grounds are written down (or `none found`), continue.

### 3.2 Then, the reason to install it

4. **Gap it fills.** What does the project visibly lack that this provides? Point at the absence
   (no `rules/`, no test convention, hook-less `settings.json`, …). "It is good practice" is not a gap.

### 3.3 Cost, risk, evidence (copy from the catalog, do not estimate)

5. **Context:** `context_chars` and whether it is always-on (rule, `CLAUDE.md` section) or
   on-demand (skill, agent). Always-on is paid in every session.
6. **Risk:** permissions, hooks (run on every edit), MCP (process + network), shared-file edits.
7. **Evidence:** `review.evidence` verdict from `catalog show <id>`: `improved`, `no_evidence`,
   `worse`, with the fixture it was measured on. If the catalog has none, write `not measured`.
   Never upgrade `not measured` to "probably helps".

### 3.4 Verdict

| Verdict | Use when |
|---|---|
| **ADD** | 3.1 found nothing; 3.2 names a concrete gap; cost and risk are proportionate |
| **SKIP** | any of 3.1 holds, or evidence is `worse`, or the gap is not real |
| **UPGRADE** | already managed and outdated; if `drift` shows user edits, say so and leave it to the user |
| **REMOVE** | already managed and `unused` holds, or a ground from 3.1 now holds that did not at install time (the project grew its own coverage). Propose only; the user decides |
| **ASK** | hooks, MCP servers, `CLAUDE.md`/`AGENTS.md` sections, `risk: high`, or you cannot decide between two equivalents. Present both sides; do not lean |

Attach a **confidence**: `high` (every answer above has a path or a quote), `medium` (one answer
is inferred), `low` (you are guessing; say what you would need to look at).

Rules of thumb:

- Fewer is better. Prefer the on-demand form when both exist (`ecc.coding-standards` over
  `ecc.rules.common`).
- `equivalent_exists` is a name match, not a judgement; `not_applicable` may be overridden with
  `--request <id>` only for a stated reason.
- "The project needs nothing" is a valid and complete result. Say it plainly.
- Install to serve the project, not to use the catalog.

## 4. Report before anything is written

### 4.1 The assessment table

One row per capability, same columns, no prose between rows:

```
capability            | verdict | conf | ctx (on/off) | covered by / contradicts     | gap                     | evidence
ecc.security-review   | SKIP    | high | 3.1k on-demand | .claude/rules/critical/sec.md | —                       | not measured
mattpocock.tdd        | ADD     | med  | 2.4k on-demand | none found                    | no test convention in CLAUDE.md | improved (python-fastapi)
forge.hook.guard-secrets-python | ASK | high | 0 | none found | no pre-commit secret check | not measured
```

Below the table:

- **Always-loaded context:** before → after, and against the policy budget if one is set.
- **Open questions:** anything `low` confidence or `ASK`, one line each, phrased so the user
  can answer yes/no.

### 4.2 The decision record

Write the same assessment as JSON to `.agent-forge/decisions/<plan-id>.json`, one object per
capability with exactly these fields (`scope` is `install`, `upgrade` or `remove`):

```json
{
  "capability_id": "ecc.security-review",
  "verdict": "SKIP",
  "grounds": ["covered"],
  "scope": "install",
  "confidence": "high",
  "covered_by": [".claude/rules/critical/sec.md"],
  "contradicts": [],
  "gap": null,
  "context_chars": 3100,
  "always_on": false,
  "risk": [],
  "evidence": "not_measured",
  "reason": "Project rule sec.md already mandates the same checklist (lines 4-19).",
  "assessed_by": "<model name/version>",
  "assessed_at": "<ISO date>"
}
```

Paths in `covered_by` and `contradicts` must exist in the project and quotes must be real
substrings; `agent-forge decisions verify` checks this and downgrades an unprovable SKIP to ASK.
`drift` uses the same paths to tell the user when the basis of a decision has disappeared. Nothing else in `.agent-forge/` is written
by this skill.

### 4.3 The command

Then the exact command your verdicts produce:

```bash
~/.agent-forge/bin/agent-forge forge --dry-run . \
  [--exclude <id>]... [--request <id>]... [--want <tag>]... \
  [--shared-files] [--hooks] [--mcp]
```

Run it, show the operation count, the files it would create or replace, and anything still
listed as `needs_approval`. If the baseline plan and your table disagree, name each difference
and your reason; do not silently pick one. Then ask: apply?
