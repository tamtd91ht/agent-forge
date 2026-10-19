# CLI reference

All commands accept `--workspace/-w PATH` and most accept `--json`. Paths with spaces and
non-ASCII characters are supported everywhere.

| Command | Modifies target? | Purpose |
|---|---|---|
| `init [--workspace P] [--refresh-registry]` | no | Create or verify a workspace; seeds registry and `sources.yaml` when empty. Safe to re-run. `--refresh-registry` re-copies the packaged registry into an existing workspace (seed capabilities replaced, your own kept); no-op when the workspace registry is the packaged seed itself. |
| `sources list [--fetch]` | no | Registered sources, checkout HEAD, recorded revision, drift. `--fetch` contacts the remote. |
| `sources clone [ID]` | no | Clone approved sources into `sources/checkouts/`. No scripts executed. |
| `sources sync [ID] [--update]` | no | Fetch upstream, report changed files; `--update` moves the checkout (refuses if dirty or pinned). |
| `catalog [--category --platform --project-type --status --source --kind]` | no | List capabilities. |
| `catalog show ID` | no | Full metadata, provenance, destinations, equivalents, review rationale. |
| `forge PATH [--platform] [--want TAG] [--request ID] [--exclude ID] [--include-optional] [--shared-files] [--hooks] [--mcp] [--yes] [--dry-run] [--show-diff]` | **yes** (after confirmation) | One-shot: scan → upgrade managed capabilities → add recommended ones → diff → one confirmation → approve + apply → validate. Only project-relevant capabilities are selected (a backend-only project gets no UI/UX items). Approval classes not granted (`--shared-files`, `--hooks`, `--mcp`) are asked for interactively, or left out of the plan with `--yes`; those capabilities are reported as `needs_approval`. `--dry-run` saves plans and writes nothing. |
| `scan PATH [--report FILE]` | no | Read-only profile. Report goes to `state/reports/` unless `--report` (never inside the target). |
| `assign PATH [--platform] [--want TAG] [--request ID] [--exclude ID] [--include-optional]` | no | Recommend and write a plan. |
| `upgrade PATH [--platform]` | no | Compare managed capabilities with the registry; write a plan. |
| `plans [--target P]` | no | List saved plans. |
| `diff PLAN_ID [--full]` | no | Unified diffs against the current target; flags stale files and shared-file ops. |
| `approve PLAN_ID [--shared-files] [--hooks] [--mcp] [--by NAME] [--revoke]` | no | Bind approval to the plan digest. Refuses stale plans. Each approval class must be granted explicitly: `--shared-files` (CLAUDE.md/AGENTS.md sections), `--hooks` (entries merged into `.claude/settings.json`, they run commands), `--mcp` (servers merged into `.mcp.json`, they launch processes). |
| `apply PLAN_ID [--yes]` | **yes** | Pre-flight, confirm, transactional write. `--yes` skips only the prompt. |
| `validate [PATH] [--no-provenance]` | no | Registry/provenance checks; with PATH also managed files, config syntax, duplicates, transactions. |
| `status PATH` | no | Managed capabilities, drift, outdated versions, conflicts, recent transactions and plans. |
| `rollback TX_ID [--partial] [--yes]` | **yes** | Reverse a transaction; never overwrites user-modified files. |
| `remove PATH ID... [--keep-modified]` | no (plan) | Plan removal of managed capabilities: managed files, CLAUDE.md/AGENTS.md sections, merged hook/MCP entries, manifest. Refuses files you edited unless `--keep-modified` (they become user-owned) and refuses when other managed capabilities depend on them. Approve + apply as usual. |
| `drift PATH` | no | Expected vs actual for every managed file (hash), section (present?) and merged entry (present?). |
| `repair PATH [--strategy restore\|unmanage] [--capability ID]` | no (plan) | `restore` rewrites drifted files from the registry at the installed version (your edits are replaced, backups kept); `unmanage` drops the capability from the manifest and leaves files alone. |
| `policy [PATH]` | no | Effective policy layers (default → workspace `policy.yaml` → project `.agent-forge/policy.yaml`) and the allow / require_request / deny verdict per capability and platform. |
| `audit [--event E] [--limit N]` | no | Append-only log of plans created/approved/revoked, transactions and rollbacks (`state/audit.jsonl`). |
| `doctor` | no | Environment and workspace health: python/git/node/npx/claude/codex on PATH, registry validity, integrity pins, human sign-off count, policy layers, audit log. |
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
