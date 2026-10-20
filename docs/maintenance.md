# Maintenance

## Day to day

```bash
.venv/Scripts/ruff check src tests scripts && .venv/Scripts/ruff format --check src tests scripts
.venv/Scripts/python -m pytest -q            # ~270 tests, ~2 min
agent-forge validate                          # registry + provenance
python scripts/export_schemas.py              # after changing models (commit the result)
```

## Updating upstream sources

1. `agent-forge sources sync` — shows how many commits behind and which files changed.
2. `agent-forge sources sync --update` — moves the checkout (refused if dirty or pinned).
3. `python scripts/curate.py --allow-revision-drift` — re-copies the explicit file list.
4. `git diff registry/` — read every change; decide per capability.
5. Bump `version` and `source.revision` in each affected `capability.yaml`.
6. `agent-forge validate`; `pytest`.
7. Users pick changes up with `agent-forge upgrade <target>`.

A curated capability's `version` is the packaging version, independent of upstream tags.

## Adding a capability

See `docs/capability-model.md`. Keep `equivalents` precise, prefer tags over `always` unless
the guidance is universally applicable, and mark anything with shell/network access via
`permissions`/`network` so it becomes optional.

## Workspace state

| Path | Contents | Safe to delete? |
|---|---|---|
| `state/plans/` | plan JSON documents | yes (plans are re-creatable) |
| `state/transactions/<tx>/` | transaction record + backups | **no** while you may still roll back |
| `state/reports/` | scan reports | yes |
| `state/cache/sources-state.json` | recorded source revisions | yes (re-run `sources clone`) |
| `state/agent-forge.sqlite3` | index | yes (`agent-forge reindex`) |

## Releasing

Update `CHANGELOG.md`, bump `agent_forge.__version__` and `pyproject.toml`, run the suite,
build with `python -m pip wheel . -w dist/` (hatchling bundles `registry/` and
`sources/sources.yaml` into the wheel so `init` can seed a fresh workspace).
