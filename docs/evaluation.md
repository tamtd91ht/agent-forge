# Evaluation

Two different questions, answered separately:

1. **Does Agent Forge recommend the right capabilities for a project?** (resolver quality)
2. **Does a capability make the coding agent better on this kind of project?** (value)

Only the first is measured today. The second is designed below and deliberately not built
into the core (ADR-0002): it needs real LLM sessions, which cost money, vary run to run, and
must never gate curation automatically.

## 1. Resolver quality (implemented)

`examples/<name>/project/` holds small representative projects (Java/Spring, Go/Gin,
Next.js/TypeScript, Python/FastAPI, ASP.NET Core, and a mixed monorepo with a Next.js app, a
FastAPI service and a Go worker). Each `expected.json` records the reviewed profile
(languages, frameworks, project types, test commands) and the reviewed recommended and
optional capability sets, with a note explaining the review.

```bash
python scripts/matching_report.py          # precision / recall per example; exit 1 on any drift
python scripts/matching_report.py --json
```

Precision = recommended ∩ expected / recommended; recall = recommended ∩ expected / expected.
CI runs it, and `tests/e2e/test_examples.py` fails on any difference.

**Limits, stated plainly.** The expectations were reviewed against the resolver's own output
when the fixtures were created, so 1.00 means "no regression from a reviewed baseline", not
agreement with an independent ground truth. The fixtures are small and synthetic. When the
registry changes, a difference is expected: re-review the example, update `expected.json`
and its note in the same change, so the review stays visible in the diff.

## 2. Capability value (design, not implemented)

The smallest experiment that can show a capability helps:

1. **Task set:** 5–10 versioned tasks per project type (`examples/<name>/tasks/*.yaml`),
   each with a deterministic acceptance command (tests that must pass) and a time budget.
2. **Arms:** baseline (project without the capability) vs candidate (after `apply`), same
   commit, same model and tool version, same prompt.
3. **Runs:** at least 3 runs per arm and task (model variance); record model, tool and
   capability versions, wall time, tokens/cost where the tool reports them, retries, and
   human interventions.
4. **Judging:** objective first: the acceptance command decides success; regressions are
   the project's full test suite. Subjective review (code quality) is recorded separately and
   never by the agent that produced the change.
5. **Report:** per task category: success rate, regression rate, time and cost per verified
   success, with run counts and spread; unavailable metrics are marked, not estimated.
6. **Decision:** promote / revise / retire is a human decision recorded in the capability's
   `review.notes`; no score threshold is fixed before a baseline exists.

Runs use the user's own tools (`claude -p`, `codex exec`) locally and opt-in; no project
code is sent to an evaluation service. This stays outside `agent-forge` until a concrete
task set and budget exist.
