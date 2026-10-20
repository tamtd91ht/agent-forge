# Evaluation results

Reports written by `agent-forge-eval run` land here as
`results/<YYYYMMDD>-<capability>-<fixture>.json` (every run) and `.md` (summary table).
Commit both; the `.md` is what reviewers read, the `.json` is what anyone re-checks.

A report becomes evidence only after a human reads it and records an entry in the
capability's `review.evidence` (see [`../evaluation.md`](../evaluation.md) §2). The entry
points back at the `.md` file here.

Rules:

- Reports from `--tool scripted` are harness smoke tests and must not be committed here.
- Record the tool version (`claude --version`), model, and the agent-forge version in the
  report metadata; the harness does this, do not edit it.
- Never summarise a run with fewer than 3 runs per arm as a measurement.
- A negative or inconclusive result is committed like any other.

| Date | Capability | Fixture | Verdict | Report |
|---|---|---|---|---|
| _none yet_ | | | | |
