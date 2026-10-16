# CLI reference

All commands accept `--workspace/-w PATH` and most accept `--json`. Paths with spaces and
non-ASCII characters are supported everywhere.

| Command | Modifies target? | Purpose |
|---|---|---|
| `init [--workspace P]` | no | Create or verify a workspace; seeds registry and `sources.yaml` when empty. Safe to re-run. |
| `sources list [--fetch]` | no | Registered sources, checkout HEAD, recorded revision, drift. `--fetch` contacts the remote. |
| `sources clone [ID]` | no | Clone approved sources into `sources/checkouts/`. No scripts executed. |
| `sources sync [ID] [--update]` | no | Fetch upstream, report changed files; `--update` moves the checkout (refuses if dirty or pinned). |
| `catalog [--category --platform --project-type --status --source --kind]` | no | List capabilities. |
| `catalog show ID` | no | Full metadata, provenance, destinations, equivalents, review rationale. |
| `scan PATH [--report FILE]` | no | Read-only profile. Report goes to `state/reports/` unless `--report` (never inside the target). |
| `assign PATH [--platform] [--want TAG] [--request ID] [--exclude ID] [--include-optional]` | no | Recommend and write a plan. |
| `upgrade PATH [--platform]` | no | Compare managed capabilities with the registry; write a plan. |
| `plans [--target P]` | no | List saved plans. |
| `diff PLAN_ID [--full]` | no | Unified diffs against the current target; flags stale files and shared-file ops. |
| `approve PLAN_ID [--shared-files] [--by NAME] [--revoke]` | no | Bind approval to the plan digest. Refuses stale plans. |
| `apply PLAN_ID [--yes]` | **yes** | Pre-flight, confirm, transactional write. `--yes` skips only the prompt. |
| `validate [PATH] [--no-provenance]` | no | Registry/provenance checks; with PATH also managed files, config syntax, duplicates, transactions. |
| `status PATH` | no | Managed capabilities, drift, outdated versions, conflicts, recent transactions and plans. |
| `rollback TX_ID [--partial] [--yes]` | **yes** | Reverse a transaction; never overwrites user-modified files. |
| `reindex` | no | Rebuild the SQLite index from JSON documents. |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | generic error / cancelled |
| 2 | usage error |
| 3 | workspace missing or invalid |
| 4 | registry/manifest error |
| 5 | scan error (target missing, not a directory) |
| 6 | plan error (missing, wrong state, shared files not approved, no TTY) |
| 7 | stale plan (target or registry changed since planning) |
| 8 | approval missing or digest mismatch |
| 9 | filesystem safety violation |
| 10 | apply failed (transaction record explains) |
| 11 | rollback conflict (user modified files after apply) |
| 12 | validation found errors |
| 13 | source/git error |

## Side effects

- `init`: writes `agent-forge.yaml`, directories, `.gitignore` in the workspace only.
- `sources clone/sync --update`: writes under `sources/checkouts/` and `state/cache/`.
- `scan/assign/upgrade/diff/approve/validate/status`: write only under `state/`.
- `apply/rollback`: write to the target (approved paths only) and under `state/transactions/`.
