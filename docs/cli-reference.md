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
| `forge PATH [--platform] [--want TAG] [--request ID] [--exclude ID] [--include-optional] [--shared-files] [--hooks] [--mcp] [--yes] [--dry-run] [--show-diff] [--approval-file F] [--no-self-update]` | **yes** (after confirmation) | One-shot: scan → upgrade managed capabilities → add recommended ones → diff → one confirmation → approve + apply → validate. Only project-relevant capabilities are selected (a backend-only project gets no UI/UX items). Approval classes not granted (`--shared-files`, `--hooks`, `--mcp`) are asked for interactively, or left out of the plan with `--yes`; those capabilities are reported as `needs_approval`. `--dry-run` saves plans and writes nothing. `--decisions F` verifies the agent's decision record first, turns effective SKIP / REMOVE into exclusions and effective ADD into requests, refuses a real run while an ASK is unanswered (`--exclude` / `--request` answer per id, exit 6) and binds the record's digest to the plan (`decisions_digest`). |
| `setup [PATH] [--platform]` | **yes** | Install or update only the `/agent-forge-upgrade` entry skill (`forge.skill.agent-forge-upgrade`) into the project (default: current directory) through a saved plan, an approval recorded as `agent-forge setup` and a transaction. Run by `install.ps1` / `install.sh` (ADR-0004); other managed capabilities are left untouched. |
| `scan PATH [--report FILE]` | no | Read-only profile. Report goes to `state/reports/` unless `--report` (never inside the target). |
| `assign PATH [--platform] [--want TAG] [--request ID] [--exclude ID] [--include-optional]` | no | Recommend and write a plan. |
| `import PATH [--kind K] [--path P] [--yes]` | no (plan); **yes** with `--yes` | Record the project's hand-written skills, subagents, rules and commands in `.agent-forge/managed.json` as `local.<kind>.<name>` entries, in place (ADR-0011): files are never copied or rewritten, only their hashes are recorded, so `status`, `usage`, `drift`, `remove` and decision records see them. The plan's only operation is the manifest write; `--yes` approves and applies it. Re-run after edits to refresh hashes; `repair --strategy unmanage` stops tracking. |
| `upgrade PATH [--platform] [--no-self-update]` | no | Compare managed capabilities with the registry; write a plan. Checks for a newer Agent Forge release first: when one exists and the command was started by the installer's launcher (`~/.agent-forge/bin/agent-forge[.cmd]`), the tag is left in `~/.agent-forge/UPDATE_TO` and the command exits 16; the launcher runs the verified installer for that tag and re-runs the command once with `--no-self-update`, so the plan compares with the current catalog. `--no-self-update` or `AGENT_FORGE_NO_SELF_UPDATE=1` plans with the installed version; offline, pipx / uvx and development installs are skipped with a note. `forge` does the same on a real run and only reports on `--dry-run`. |
| `self-update [--check] [--release vX.Y.Z]` | `~/.agent-forge` only (via the launcher) | Update Agent Forge itself (engine + packaged catalog) to the latest release: the same exit-16 handshake with the launcher, which runs the verified installer. Installs nothing when already current. `--check` compares only (`--json`: `installed`, `latest`, `available`, `note`). A branch or a checkout (development) is installed with the installer and `AGENT_FORGE_REF` / `AGENT_FORGE_SOURCE` instead. |
| `plans [--target P]` | no | List saved plans. |
| `diff PLAN_ID [--full]` | no | Unified diffs against the current target; flags stale files and shared-file ops. |
| `approve PLAN_ID [--shared-files] [--hooks] [--mcp] [--by NAME] [--revoke] [--approval-file F] [--export-approval F]` | no | Bind approval to the plan digest. Refuses stale plans. `--approval-file` approves non-interactively from a committed file (ids, versions, classes) and refuses with exit 14 when the plan goes beyond it; `--export-approval` writes such a file covering exactly this plan. Each approval class must be granted explicitly: `--shared-files` (CLAUDE.md/AGENTS.md sections), `--hooks` (entries merged into `.claude/settings.json`, they run commands), `--mcp` (servers merged into `.mcp.json`, they launch processes). |
| `apply PLAN_ID [--yes]` | **yes** | Pre-flight, confirm, transactional write. `--yes` skips only the prompt. |
| `validate [PATH] [--no-provenance]` | no | Registry checks (schema, digests and pins, links, skill-to-skill calls, content safety, risk rationale, provenance); with PATH also managed files, deprecated/revoked installs, config syntax, duplicates, transactions (tampered, invalid backup references, **unfinished transactions**). |
| `status PATH` | no | Managed capabilities, drift, outdated versions, conflicts, recent transactions and plans; what is absent by decision (latest record, grounds and basis); `unused` hints when a usage log exists. |
| `rollback TX_ID [--partial] [--yes]` | **yes** | Reverse a transaction; never overwrites user-modified files. |
| `remove PATH ID... [--keep-modified]` | no (plan) | Plan removal of managed capabilities: managed files, CLAUDE.md/AGENTS.md sections, merged hook/MCP entries, manifest. Refuses files you edited unless `--keep-modified` (they become user-owned) and refuses when other managed capabilities depend on them. Approve + apply as usual. |
| `drift PATH` | no | Expected vs actual for every managed file (hash), section (present?) and merged entry (present?); plus `decision_basis`: cited files or quoted lines of the latest decision record that no longer exist. |
| `repair PATH [--strategy restore\|unmanage] [--capability ID]` | no (plan) | `restore` rewrites drifted files from the registry at the installed version (your edits are replaced, backups kept); `unmanage` drops the capability from the manifest and leaves files alone. |
| `policy [PATH]` | no | Effective policy layers (default → workspace `policy.yaml` → project `.agent-forge/policy.yaml`) and the allow / require_request / deny verdict per capability and platform. |
| `audit [--event E] [--limit N]` | no | Append-only log of plans created/approved/revoked, transactions and rollbacks (`state/audit.jsonl`); credential-looking values are redacted. |
| `impact ID` | no | Projects this workspace installed `ID` into (read from each project's `managed.json`), installed version, outdated or not; registry status and `replaced_by`. |
| `doctor [--check-latest]` | no | Environment and workspace health: python/git/node/npx/claude/codex on PATH, registry validity, integrity pins, human sign-off count, policy layers, unfinished transactions, audit log. |
| `check PATH` | no | CI gate: one exit code (0 clean, 12 problems) for drift, missing or revoked capabilities, invalid `managed.json`, unfinished transactions, config syntax, a policy-`required` capability that is not installed (`required_missing`), a SKIP / REMOVE in the latest decision record that no longer verifies (its cited file or quote is gone), and an applied plan whose `decisions_digest` matches no record under `.agent-forge/decisions/` (`decisions` in the JSON); `outdated` listed for information. Used by `.github/actions/check`. |
| `sync [PATH] [--yes] [--dry-run]` | **yes** | Fresh clone: restore managed files and sections that are missing or modified, at the versions `.agent-forge/managed.json` pinned (a `repair --strategy restore` plan, approved as `agent-forge sync`, journaled transaction). Chooses nothing new. Refuses when the workspace registry lacks a pinned version. |
| `stats [--since DAYS]` | no | Installs, rollbacks and projects per capability from the local audit log. Nothing leaves the machine. |
| `lint PATH [--max-context N]` | no | Score the agent configuration a project already has (ADR-0007): always-loaded context per file and in total, duplicate paragraphs / near-duplicate rule files, credentials in agent files and MCP configs, hooks whose commands trip the content-safety rules, MCP servers defined but disabled; and, as warnings, references to skills / agents / commands / rules / `@imports` that do not exist (`deadref`), counts in instructions larger than the disk holds (`index_drift`), two skills or agents whose descriptions overlap (`overlap`), skills or agents without `name` / `description` frontmatter (`schema`), hook scripts that write to stdout only, which the model never sees (`hook_output`). No workspace, no catalog, no LLM; proposes nothing. Exit 12 on an error finding or when `--max-context` is exceeded. |
| `usage PATH [--since DAYS]` | no | Invocations per installed skill / subagent from `.agent-forge/usage.jsonl` (written by the opt-in `forge.hook.usage-log`); `unused` after ≥ 14 observed days with zero calls. Rules are always-on and never "invoked". |
| `decisions verify PATH [--plan ID \| --file F] [--platform P]` | no | Check the agent's decision record (`.agent-forge/decisions/<plan-id>.json`): cited paths exist inside the project, quotes are real, `context_chars` / `evidence` match the catalog, every ground carries its evidence, policy is respected. A SKIP / REMOVE that fails becomes ASK (effective verdict); exit 12 when any check failed. |
| `decisions diff PATH [--old F --new F]` | no | Only the decisions that changed between two records (default: the two newest), with the old and the new reason. |
| `decisions explain PATH ID` | no | Why a capability is or is not in the project, from the latest record. |
| `decisions report DIR...` | no | Organisation-wide table capability × verdict × ground over every repository's latest record under the directories, with threshold suggestions for the catalog review (ADR-0008). |
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
| 16 | a newer Agent Forge release was requested (`~/.agent-forge/UPDATE_TO`): the launcher installs it and re-runs the command; seen directly only when the engine is run without the launcher |
| 130 | interrupted (Ctrl+C); run `agent-forge status` / `doctor` to see if a transaction needs recovery |

Exit codes 2–15 are each produced by a real CLI path in `tests/e2e/test_exit_codes.py` (15 with a stubbed tool).

### Pre-flight problem codes (`apply`, `forge`, `sync`)

Before any write, `apply` re-checks the approved plan. Each finding is a `Problem` with a
code (`apply/engine.py`, `ProblemCode`); the code picks the exception and the exit code, and
the message is for people. Stale beats approval beats everything else, so a plan that is both
outdated and unapproved says "re-plan" first.

| Code | Meaning | Exit | What to do |
|---|---|---|---|
| `expired` | past `expires_at` (7 days) | 7 | re-plan |
| `policy_changed` | effective policy digest differs | 7 | re-plan under the new policy |
| `registry_changed` | registry digest differs (assets edited, Agent Forge upgraded) | 7 | re-plan |
| `file_changed` | a destination differs from what the plan expected | 7 | re-plan (or `drift` / `sync` first) |
| `not_approved` | plan status is not `approved` | 8 | `approve` |
| `approval_mismatch` | approval digest != plan content (plan edited) | 8 | `approve --revoke`, re-plan |
| `approval_not_recorded` | this workspace never recorded the approval | 8 | `approve` here |
| `extra_approval_required` | shared-file / hook / MCP class not granted | 8 | `approve --shared-files` / `--hooks` / `--mcp` |
| `target_missing` | project directory is gone | 10 | restore the project |
| `unsafe_path` | destination fails the path safety checks | 10 | report it; nothing is written |
| `projection_failed` | section or JSON merge cannot be computed on the current file | 10 | fix or restore the file, re-plan |
| `outside_managed_roots` | destination outside the adapter's roots | 10 | plan corrupted; re-plan |
| `content_hash_mismatch` | operation content != its recorded hash | 10 | plan corrupted; re-plan |

## JSON output

`--json` prints machine-readable output on stdout (human messages go to stderr), always as
**JSON envelope v1** (`registry/schema/envelope.schema.json`):

```json
{
  "envelope": 1,
  "command": "agent-forge forge",
  "agent_forge": "0.2.0",
  "generated_at": "2026-10-20T10:00:00+00:00",
  "ok": true,
  "data": { "...": "the command's document" }
}
```

`data` is the command's document: stored documents (plans, transactions, profiles,
capabilities) carry their own `schema_version` and match `registry/schema/*.schema.json`;
list-style outputs are stable within a minor version. `ok` is false only for commands that
report findings and exit non-zero (`validate`, `check`, `doctor`). Errors never print JSON on
stdout. Automation reads `envelope` first and refuses an unknown value.

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
