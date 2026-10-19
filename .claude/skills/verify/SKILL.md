---
name: verify
description: Run Agent Forge's verification loop (ruff, pytest, registry validate, schema and capability-version checks, diff hygiene) and report pass/fail with evidence. Use after any change to src/, tests/, scripts/, or registry/, and before saying a task is done.
---

# Verify

Run each step from the repo root and stop at the first failure: fix it, then restart the loop.
Report the actual command output for anything that failed or was skipped.

1. **Lint and format**
   `.venv/Scripts/ruff check src tests scripts` then `.venv/Scripts/ruff format --check src tests scripts`.
   If only formatting fails, run `ruff format` on the files *you* changed — not the whole tree.

2. **Tests** — `.venv/Scripts/python -m pytest -q`.
   For a quick inner loop, run the relevant `tests/<suite>/` first, but always finish with the
   full suite.

3. **Registry** — `.venv/Scripts/agent-forge validate`.

4. **Conditional checks** (inspect `git status --porcelain` and `git diff --stat`):
   - `src/agent_forge/models/` changed → run `.venv/Scripts/python scripts/export_schemas.py`;
     the resulting schema diff must be intended.
   - `registry/capabilities/<id>/assets/` changed → that capability's `version` is bumped and
     `source.revision` is a real commit SHA.
   - New code writing into a target project → it lives in `apply/engine.py` or
     `rollback/engine.py`, goes through `filesystem_safety.resolve_in_root`, and has new tests
     in both `tests/security/` and `tests/integration/`.
   - Planner changes → if plan content changed, `Plan.content_digest()` inputs and their tests
     were updated deliberately.

5. **Diff hygiene** — read `git diff`. Every hunk must trace to the request: no unrelated
   reformatting, no stray debug output, no edits under `sources/checkouts/`, no orphaned
   imports left by this change.

Summarize as a short checklist: each step ✅ / ❌ / skipped (with reason).
