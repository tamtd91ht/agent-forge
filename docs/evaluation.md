# Evaluation

Two different questions, answered separately:

1. **Does Agent Forge recommend the right capabilities for a project?** (resolver quality)
2. **Does a capability make the coding agent better on this kind of project?** (value)

Both have tooling now. The second runs real LLM sessions, so it stays opt-in, local and
outside the core package (ADR-0002); its results are evidence for a human decision and never
an automatic gate.

## 1. Resolver quality (implemented)

`examples/<name>/project/` holds small representative projects (Java/Spring, Go/Gin,
Next.js/TypeScript, Python/FastAPI, ASP.NET Core, and a mixed monorepo). Each
`expected.json` records the reviewed profile and the reviewed recommended and optional sets.

```bash
python scripts/matching_report.py                     # per example + micro-averaged aggregate; exit 1 on drift
python scripts/matching_report.py --json
python scripts/matching_report.py --corpus /path/to/reviewed-repos --min-precision 0.9 --min-recall 0.85
```

Precision = recommended ∩ expected / recommended; recall = recommended ∩ expected / expected.
The `examples/` set must stay exact (a difference means the registry or the resolver
changed and the review must be redone). `--corpus` adds a directory with the same layout
holding **anonymised real repositories** (dependency manifests, directory skeleton and the
agent configuration only; no application source), each with a reviewed `expected.json`;
the aggregate over examples + corpus is compared with the thresholds. Target for phase 3 of
the plan: ≥ 20 corpus projects, thresholds in CI. The corpus is kept outside this repository
(it describes real projects); CI reads it from a private artifact when configured.

**Limits, stated plainly.** The `examples/` expectations were reviewed against the resolver's
own output when the fixtures were created, so 1.00 there means "no regression from a reviewed
baseline". Only the corpus measures agreement with an independent ground truth.

## 2. Capability value (harness implemented; measurements pending)

[`tools/agent-forge-eval`](../tools/agent-forge-eval/README.md) runs the experiment designed
here; the design is unchanged:

1. **Task set:** `examples/<name>/tasks/*.yaml`, five per fixture today (feature, bugfix,
   refactor, review, docs), each with a prompt, optional planted files, hidden acceptance
   tests and an acceptance command, plus the project's own suite as regression check.
2. **Arms:** baseline (fixture as is) vs candidate (fixture after
   `agent-forge forge --request <capability>`, by the real engine), same commit, model, tool
   version and prompt.
3. **Runs:** ≥ 3 per arm and task; the harness records wall time, tokens and cost when the
   tool reports them, files changed, timeouts.
4. **Judging:** the acceptance command decides; regressions are the project's suite.
   Subjective review is recorded separately, never by the producing agent.
5. **Report:** pass rate with Wilson 95% intervals per arm and category; verdict
   `improved` only when the candidate's lower bound is above the baseline's rate, otherwise
   `no_evidence` (or `worse`). Unavailable metrics are n/a, not estimated.
6. **Decision:** a human reads the report and records an entry in the capability's
   `review.evidence` (date, fixture, tool, runs, tasks, both pass rates, the candidate CI,
   verdict, report path, who decided). `catalog show` prints the evidence table, or says
   "none (value not measured)". A capability whose evidence says `no_evidence` or `worse`
   twice is a candidate for revision or removal; the decision is recorded in `review.notes`.

```bash
pip install -e tools/agent-forge-eval
agent-forge-eval run --fixture examples/python-fastapi --capability ecc.tdd-workflow --tool claude --runs 3
```

### Measurement plan for the five core skills (phase 3)

| Capability | Fixtures | Why these |
|---|---|---|
| `ecc.security-review` | python-fastapi, go-gin, nextjs-ts | the `review-*` tasks plant an injection / traversal / XSS bug |
| `ecc.tdd-workflow` | python-fastapi, go-gin | feature and bugfix tasks judged by hidden tests |
| `ecc.agent.planner` | mixed-monorepo, java-spring | multi-step feature tasks across modules |
| `mattpocock.two-axis-review` (code review) | nextjs-ts, dotnet-webapi | review and refactor tasks |
| `forge.hook.guard-dangerous-git` | any | hooks change behaviour, not pass rate: measured by `changed_files` and regressions |

Status: **no measurement has been run yet.** Running it needs a maintainer with the tool
installed and a budget (3 runs × 2 arms × 5 tasks ≈ 30 sessions per fixture). Results go in
`docs/evaluation/results/` (see its README); until then every capability's evidence is
empty and `catalog show` says so.

### Always-loaded context cost

Every plan shows each capability's always-loaded context (`ctx`) and the total. Policy
`max_context_chars` gates a single capability (ADR-0003); `max_total_context_chars` sets a
budget for the whole plan: when exceeded, the plan carries a note and a decision line for
the approver (the plan is not blocked; dropping a capability or raising the budget is a
human call).
