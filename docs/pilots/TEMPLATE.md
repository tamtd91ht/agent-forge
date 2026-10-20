# Pilot: <repository name>

- **Stack:** <Node / Python / Go / Java / .NET>
- **Owner (commits to answer within a day):** <name>
- **Tech lead reviewing approvals:** <name>
- **Started:** YYYY-MM-DD · **Retrospective due:** YYYY-MM-DD

## Baseline (before the first install)

| Measure | Value | How measured |
|---|---|---|
| Existing AI configuration | <e.g. CLAUDE.md 120 lines, 2 skills, 0 hooks> | `agent-forge scan . --json` → assets |
| Onboarding time (clone → working agent) | <min> | stopwatch, one new developer |
| Hand edits to CLAUDE.md / .claude in the last 30 days | <n> | `git log --since=30.days --oneline -- CLAUDE.md .claude \| wc -l` |
| Policy in force | <none / team-default> | `agent-forge policy .` |

## Installed

| Date | Capabilities (ids @ versions) | Classes granted | Approved by | Approval file commit |
|---|---|---|---|---|
| | | | | |

## Weekly log

| Week | `check` status | Rollbacks (why) | Manual edits to managed files | Declined proposals | Time spent on AF |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |

## Feedback (free text, dated)

- YYYY-MM-DD — <who>: <what helped, what got in the way, what was confusing>

## After (fill in at the retrospective)

| Measure | Baseline | After |
|---|---|---|
| Onboarding time | | |
| Hand edits / 30 days | | |
| Rollbacks that failed | – | |
| Capabilities used at least weekly | – | |

Decision proposal (keep / drop / standardise): <two paragraphs, feeds docs/adr/0007-pilot-decision.md>
