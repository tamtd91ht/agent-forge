"""agent-forge-eval: opt-in capability value evaluation (ADR-0002, docs/evaluation.md).

Runs the same task set on a fixture project with and without a capability, using the
user's own coding tool locally (`claude -p`, `codex exec`), judges each run with the task's
acceptance command, and reports pass rates with confidence intervals. Never a curation gate.
"""

__version__ = "0.1.0"
