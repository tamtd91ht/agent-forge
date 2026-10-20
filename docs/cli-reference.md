# CLI reference

All commands accept `--workspace/-w PATH` and most accept `--json`. `--platform` values:
`claude_code`, `codex`, `cursor`, `copilot`, `gemini` (default: detected). Paths with spaces and
non-ASCII characters are supported everywhere.

| Command | Modifies target? | Purpose |
|---|---|---|
| `init [--workspace P] [--refresh-registry]` | no | Create or verify a workspace; seeds registry and `sources.yaml` when empty. Safe to re-run. `--refresh-registry` re-copies the packaged registry into an existing workspace (seed capabilities replaced, your own kept); no-op when the workspace registry is the packaged seed itself. |
| `sources list [--fetch]` | no | Registered sources, checkout HEAD, recorded revision, drift. `--fetch` contacts the remote. |
| `sources clone [ID]` | no | Clone approved sources into `sources/checkouts/`. No scripts executed. |
| `sources sync [ID] [--update]` | no | Fetch upstream, report changed files; `--update` moves the checkout (refuses if dirty or pinned). |
| `catalog [--category --platform --project-type --status --source --kind]` | no | List capabilities. |
| `catalog show ID` | no | Full metadata, provenance, destinations, equivalents, review rationale. |
| `forge PATH [--platform] [--want TAG] [--request ID] [--exclude ID] [--include-optional] [--shared-files] [--hooks] [--mcp] [--yes] [--dry-run] [--show-diff] [--approval-file F]` | **yes** (after confirmation) | One-shot: scan → upgrade managed capabilities → add recommended ones → diff → one confirmation → approve + apply → validate. Only project-relevant capabilities are selected (a backend-only project gets no UI/UX items). Approval classes not granted (`--shared-files`, `--hooks`, `--mcp`) are asked for interactively, or left out of the plan with `--yes`; those capabilities are reported as `needs_approval`. `--dry-run` saves plans and writes nothing. |
| `setup [PATH] [--platform]` | **yes** | Install or update only the `/agent-forge-upgrade` entry skill (`forge.skill.agent-forge-upgrade`) into the project (default: current directory) through a saved plan, an approval recorded as `agent-forge setup` and a transaction. Run by `install.ps1` / `install.sh` (ADR-0004); other managed capabilities are left untouched. |
| `scan PATH [--report FILE]` | no | Read-only profile. Report goes to `state/reports/` unless `--report` (never inside the target). |
| `assign PATH [--platform] [--want TAG] [--request ID] [--exclude ID] [--include-optional]` | no | Recommend and write a plan. |
| `upgrade PATH [--platform]` | no | Compare managed capabilities with the registry; write a plan. |
| `plans [--target P]` | no | List saved plans. |
| `diff PLAN_ID [--full]` | no | Unified diffs against the current target; flags stale files and shared-file ops. |
| `approve PLAN_ID [--shared-files] [--hooks] [--mcp] [--by NAME] [--revoke] [--approval-file F] [--export-approval F]` | no | Bind approval to the plan digest. Refuses stale plans. `--approval-file` approves non-interactively from a committed file (ids, versions, classes) and refuses with exit 14 when the plan goes beyond it; `--export-approval` writes such a file covering exactly this plan. Each approval class must be granted explicitly: `--shared-files` (CLAUDE.md/AGENTS.md sections), `--hooks` (entries merged into `.claude/settings.json`, they run commands), `--mcp` (servers merged into `.mcp.json`, they launch processes). |
| `apply PLAN_ID [--yes]` | **yes** | Pre-flight, confirm, transactional write. `--yes` skips only the prompt. |
| `validate [PATH] [--no-provenance]` | no | Registry checks (schema, digests and pins, links, skill-to-skill calls, content safety, risk rationale, provenance); with PATH also managed files, deprecated/revoked installs, config syntax, duplicates, transactions (tampered, invalid backup references, **unfinished transactions**). |
| `status PATH` | no | Managed capabilities, drift, outdated versions, conflicts, recent transactions and plans. |
| `rollback TX_ID [--partial] [--yes]` | **yes** | Reverse a transaction; never overwrites user-modified files. |
| `remove PATH ID... [--keep-modified]` | no (plan) | Plan removal of managed capabilities: managed files, CLAUDE.md/AGENTS.md sections, merged hook/MCP entries, manifest. Refuses files you edited unless `--keep-modified` (they become user-owned) and refuses when other managed capabilities depend on them. Approve + apply as usual. |
| `drift PATH` | no | Expected vs actual for every managed file (hash), section (present?) and merged entry (present?). |
| `repair PATH [--strategy restore\|unmanage] [--capability ID]` | no (plan) | `restore` rewrites drifted files from the registry at the installed version (your edits are replaced, backups kept); `unmanage` drops the capability from the manifest and leaves files alone. |
| `policy [PATH]` | no | Effective policy layers (default → workspace `policy.yaml` → project `.agent-forge/policy.yaml`) and the allow / require_request / deny verdict per capability and platform. |
| `audit [--event E] [--limit N]` | no | Append-only log of plans created/approved/revoked, transactions and rollbacks (`state/audit.jsonl`); credential-looking values are redacted. |
| `impact ID` | no | Projects this workspace installed `ID` into (read from each project's `managed.json`), installed version, outdated or not; registry status and `replaced_by`. |
| `doctor` | no | Environment and workspace health: python/git/node/npx/claude/codex on PATH, registry validity, integrity pins, human sign-off count, policy layers, unfinished transactions, audit log. |
| `check PATH` | no | CI gate: one exit code (0 clean, 12 problems) for drift, missing or revoked capabilities, invalid `managed.json`, unfinished transactions, config syntax; `outdated` listed for information. Used by `.github/actions/check`. |
| `sync [PATH] [--yes] [--dry-run]` | **yes** | Fresh clone: restore managed files and sections that are missing or modified, at the versions `.agent-forge/managed.json` pinned (a `repair --strategy restore` plan, approved as `agent-forge sync`, journaled transaction). Chooses nothing new. Refuses when the workspace registry lacks a pinned version. |
| `stats [--since DAYS]` | no | Installs, rollbacks and projects per capability from the local audit log. Nothing leaves the machine. |
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
| 14 | plan not covered by the approval file (`--approval-file`): a capability, version or approval class outside the committed file |
| 15 | the installed coding tool is outside the version range the adapter was verified for (`doctor` shows both) |
| 130 | interrupted (Ctrl+C); run `agent-forge status` / `doctor` to see if a transaction needs recovery |

Exit codes 2–15 are each produced by a real CLI path in `tests/e2e/test_exit_codes.py` (15 with a stubbed tool).

## JSON output

`--json` prints machine-readable output on stdout (human messages go to stderr). Documents
that are also stored (plans, transactions, profiles, capabilities) carry `schema_version`
and match `registry/schema/*.schema.json`; list-style outputs (`catalog`, `status`, `audit`,
`policy`, `doctor`, `validate`, `impact`) are stable within a minor version. A uniform
versioned envelope for every command is planned for the first versioned release.

## Side effects

- `init`: writes `agent-forge.yaml`, directories, `.gitignore` in the workspace only.
- `sources clone/sync --update`: writes under `sources/checkouts/` and `state/cache/`.
- `scan/assign/upgrade/diff/approve/validate/status`: write only under `state/`.
- `apply/rollback/setup/forge`: write to the target (approved paths only) and under `state/transactions/`.
- `install.ps1` / `install.sh`: write only under `~/.agent-forge/` (venv, launchers, workspace), then run `setup` in the current directory.

## Approval files

A plan is bound to one machine (canonical path, file hashes), so a recorded approval cannot
travel to CI. An approval file records the *content* decision instead and is committed with
the project (`.agent-forge/approval.yaml`, written by `approve --export-approval`):

```yaml
version: 1
approved_by: tech-lead
approved_at: "2026-10-20T09:00:00+00:00"
note: exported from plan plan-20261020-090000-abcdef
registry_digest: null            # set it to also pin the registry state
classes: [shared_file]           # of shared_file, hook, mcp
capabilities:
  ecc.security-review: 1.2.0     # exact version, or "*"
  karpathy.principles: 1.0.0
```

`approve --approval-file` and `forge --approval-file` accept a plan only when every selected
capability is listed at that version (or `*`), every approval class the plan needs is granted,
and the registry digest matches when set. Anything else is exit 14 and nothing is written.
