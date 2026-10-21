# Pilot repositories

Phase 1 of the [6-month plan](../roadmap-2026h2.md): Agent Forge goes into three real team
repositories with three different stacks. This directory records the baseline before, the
feedback during, and the go / no-go decision after. Numbers here feed the KPIs in the plan.

Each pilot is one file: copy [`TEMPLATE.md`](TEMPLATE.md) to `<repo-name>.md`.

## Baseline (fill in before the first install)

| Pilot | Stack | Owner | Existing AI config | Onboarding time (clone → working agent) | Hand edits to CLAUDE.md last 30 days | Date |
|---|---|---|---|---|---|---|
| _repo-1_ | _Node / Next.js_ | _name_ | _CLAUDE.md 120 lines, 2 skills_ | _min_ | _n_ | _YYYY-MM-DD_ |
| _repo-2_ | _Python / FastAPI_ | | | | | |
| _repo-3_ | _Go / Java / .NET_ | | | | | |

How to measure:

- **Onboarding time:** a developer who has never set up the repo, from `git clone` to the
  first successful `/agent-forge-upgrade` (or, before Agent Forge, to a working `CLAUDE.md`
  and skills). Stopwatch, once per pilot, recorded by the owner.
- **Hand edits:** `git log --since=30.days --oneline -- CLAUDE.md .claude | wc -l`.
- **Existing config:** `agent-forge scan <repo> --json` → `assets` (count by kind) before
  the pilot starts; keep the report file.

## During the pilot (weekly, 5 minutes)

```bash
agent-forge status .          # installed, drift, outdated, absent by decision, unused hints
agent-forge check .           # what CI sees (incl. missing `required` capabilities)
agent-forge usage .           # invocations per installed skill / subagent (needs the hook below)
agent-forge stats --since 7   # installs / rollbacks this week (local audit log)
```

On day one of each pilot enable the local usage log so the 30-day window starts early:
`agent-forge forge . --want usage --hooks` installs `forge.hook.usage-log` (opt-in, offline,
ids and timestamps only). Commit every `.agent-forge/decisions/<plan-id>.json` the skill
writes: they are the first real data for the rubric (ADR-0007) and for
`agent-forge decisions report` across the pilots.

Record in the pilot file: what was rolled back and why, every manual edit to a managed
file, every `needs_approval` the owner declined, time spent on Agent Forge itself.

## Retrospective (end of week 6)

Two pages, numbers first, then the decision recorded as an ADR (`docs/adr/0009-pilot-decision.md`;
0007 and 0008 were taken by the decision layer and the catalog criteria):

1. Baseline vs. after for each KPI in the table above.
2. Rollbacks that failed in practice (target: 0) and why.
3. Capabilities nobody used (`agent-forge usage`, candidates for removal) and capabilities
   people asked for; the share of SKIPs that `decisions verify` downgraded to ASK (how often
   the model claimed coverage it could not prove).
4. Keep / drop / standardise: what becomes the team default policy, what goes in the team
   registry, what is removed from the catalog.
5. Go / no-go for the rest of the team, with the conditions.
