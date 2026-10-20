# Contributing

Submitting a capability to the catalog: [docs/contributing-capabilities.md](docs/contributing-capabilities.md).
Maintainer roster and merge rules: [MAINTAINERS.md](MAINTAINERS.md).

Agent rules for coding agents working here are in [AGENTS.md](AGENTS.md); they apply to
humans too.

## Set up

```bash
git clone https://github.com/tamtd91ht/agent-forge.git && cd agent-forge
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"        # macOS/Linux: .venv/bin/pip
```

## Before every pull request

```bash
.venv/Scripts/ruff check src tests scripts tools && .venv/Scripts/ruff format --check src tests scripts tools
.venv/Scripts/python -m pytest -q
.venv/Scripts/agent-forge validate
python scripts/export_schemas.py --check
python scripts/matching_report.py
```

CI runs the same on Windows, Linux and macOS.

## What a change needs

| Change | Also required |
|---|---|
| Engine behaviour | a failing test first; docs updated only when a guarantee changes |
| New write path into a project | goes through `apply/engine.py` or `rollback/engine.py` and `filesystem_safety`; tests in `tests/security/` and `tests/integration/` |
| Model fields | `python scripts/export_schemas.py`; plan digest inputs changed deliberately |
| Curated assets | bump the capability `version`, real `source.revision` SHA, `scripts/pin_integrity.py`, content-safety findings acknowledged with a reason |
| Risk above low | `review.risk_rationale` |
| Registry change that alters recommendations | re-review `examples/*/expected.json` in the same change |
| New adapter | passes `tests/conformance/` unchanged |
| Architecture decision | an ADR in `docs/adr/` |

## Where things are decided

- Direction: [docs/product-vision.md](docs/product-vision.md)
- Decisions: [docs/adr/](docs/adr/) (an accepted ADR wins over the vision)
- Tasks and audit status: [docs/engineering-roadmap.md](docs/engineering-roadmap.md)
- Curation and rejections: [docs/source-curation.md](docs/source-curation.md),
  [docs/rejections/](docs/rejections/README.md)

Security issues: see [SECURITY.md](SECURITY.md), not the public tracker.
