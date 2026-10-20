# Agent Forge — instructions for coding agents working on this repository

This repo is a Python CLI (`src/agent_forge`) with a curated capability registry
(`registry/`). Read `docs/architecture.md` and `docs/adr/0001-architecture-decisions.md`
before changing engine code.

## Rules

- Docs precedence: accepted ADRs (`docs/adr/`) decide; `docs/product-vision.md` is direction;
  `docs/engineering-roadmap.md` is the task list and audit status. Files under
  `docs/history/` are historical input.
- Never execute anything under `sources/checkouts/` (untrusted upstream clones). Read only.
- The only modules allowed to write into a target project are `apply/engine.py` and
  `rollback/engine.py`, and only through `apply/filesystem_safety` (`resolve_in_root`,
  `safe_write_bytes`), under the per-project lock (`storage/locks.py`).
- Do not add dependencies without a reason; stack is Typer, Rich, Pydantic, PyYAML (+ pytest,
  ruff, hypothesis, jsonschema for dev). Python ≥ 3.11.
- Keep commands read-only unless they are `apply`/`rollback`. New write paths need tests in
  `tests/security/` and `tests/integration/`.
- Shared files (`CLAUDE.md`, `AGENTS.md`, settings) are only ever touched inside
  `<!-- agent-forge:begin … -->` / `<!-- agent-forge:end … -->` markers.
- Plans are immutable after approval; anything that changes plan content must change
  `Plan.content_digest()` inputs deliberately and update tests.
- After editing models run `python scripts/export_schemas.py` and commit the schemas.
- After changing curated assets bump the capability `version` and keep `source.revision`
  truthful (a real commit SHA from the checkout).

## Commands

```bash
.venv/Scripts/ruff check src tests scripts tools && .venv/Scripts/ruff format src tests scripts tools
.venv/Scripts/python -m pytest -q
agent-forge validate
```

## Layout

- `src/agent_forge/{config,errors,util,cli}.py` — entry points and shared helpers
- `models/`, `registry/`, `sources/`, `scanner/`, `adapters/`, `matching/`, `planner/`,
  `apply/`, `validation/`, `rollback/`, `storage/` — see `docs/architecture.md`
- `registry/capabilities/<id>/{capability.yaml,assets/}` — curated content
- `scripts/curate.py` — reproducible copy from pinned checkouts; `scripts/export_schemas.py`
- `tests/{unit,security,integration,e2e}` — fixtures are built in `tests/conftest.py`
- `state/` — runtime state, git-ignored
