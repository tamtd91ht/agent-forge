# agent-forge-eval

Opt-in, local evaluation of **capability value**: does a curated capability make a coding
agent better on a given kind of project? Separate package on purpose (ADR-0002): it runs
real LLM sessions, costs money, varies run to run, and must never gate curation.

## What it does

For each task in `examples/<fixture>/tasks/*.yaml` and each arm:

1. copy `examples/<fixture>/project` to a temporary directory and `git init` it;
2. **candidate** arm only: install the capability with the real engine
   (`agent-forge forge --request <id> --yes --shared-files --hooks`);
3. write the task's `setup.files` (for example a planted bug);
4. run the coding tool headless with the task prompt (`claude -p … --output-format json`
   or `codex exec --json …`), within `budget_seconds`;
5. write the task's `acceptance.files` (hidden tests) and run `acceptance.command`:
   exit 0 = pass; optionally the project's own suite as `regression_command`;
6. record pass/fail, wall time, tokens and cost when the tool reports them, files changed.

The report gives pass rates with Wilson 95% intervals per arm and per task category and a
plain verdict: `improved` (candidate's lower bound above the baseline's rate), `worse`, or
`no_evidence`. With 3 runs the intervals are wide by design; that is the honest answer.

## Install and run

```bash
pip install -e tools/agent-forge-eval            # or: uv pip install -e tools/agent-forge-eval
agent-forge-eval tasks --fixture examples/python-fastapi
agent-forge-eval run --fixture examples/python-fastapi --capability ecc.tdd-workflow \
    --tool claude --runs 3 --tool-args --permission-mode acceptEdits
```

Results land in `docs/evaluation/results/<date>-<capability>-<fixture>.{json,md}`. Copy the
summary numbers into the capability's `review.evidence` (see `docs/evaluation.md`) when a
human has read the report and decided.

`--tool scripted` runs a no-op agent to exercise the harness (tests use it). Its output is
labelled "NOT a measurement" and must never be cited as evidence.

## Writing tasks

```yaml
id: add-items-endpoint            # = file name
category: feature                 # bugfix | feature | refactor | review | docs
prompt: |
  Add GET /items returning a JSON list of item names …
budget_seconds: 600
setup:                            # optional, written before the agent runs
  files: { app/bug.py: "..." }
acceptance:
  files: { tests/test_items.py: "..." }   # hidden until judging
  command: python -m pytest -q tests/test_items.py
regression_command: python -m pytest -q  # optional
```

Tasks must reflect real work (fix a bug, add an endpoint, refactor with tests) and be
reviewed by two people before their results are cited.
