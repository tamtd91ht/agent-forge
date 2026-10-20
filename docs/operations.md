# Operations: recovery, diagnostics, support

## Where things live

| Path | What |
|---|---|
| `~/.agent-forge/` | installed Agent Forge: `.venv/` (engine), `bin/` (launchers), workspace |
| `<workspace>/state/plans/`, `state/approvals/` | plans and the approvals `approve` recorded |
| `<workspace>/state/transactions/<tx>/` | transaction record + `backup/` of every file changed |
| `<workspace>/state/locks/` | per-project write locks (owner pid) |
| `<workspace>/state/audit.jsonl` | append-only event log (secrets redacted) |
| `<project>/.agent-forge/managed.json` | what is installed in the project; commit it |

## Diagnostics

| Question | Command |
|---|---|
| Is my setup healthy? | `agent-forge doctor` (tools, registry, pins, sign-off, policy, **unfinished transactions**) |
| Is this project consistent? | `agent-forge validate <project>` (exit 12 on errors) |
| What is installed, what changed, what is unfinished? | `agent-forge status <project>`, `agent-forge drift <project>` |
| Where is capability X installed? | `agent-forge impact <id>` |
| What happened and when? | `agent-forge audit [--event E]` |

Every command accepts `--json`; exit codes are listed in [cli-reference.md](cli-reference.md).

## Recovery

| Situation | What you see | What to do |
|---|---|---|
| Apply interrupted (crash, kill, power loss) | `status`/`doctor`/`validate`: "interrupted while applying" | `agent-forge rollback <tx>`: journaled operations are resolved from disk (still old → skipped, new → reversed) |
| Apply failed midway | transaction `partial` / `failed` | `agent-forge rollback <tx>` |
| You edited installed files, then want to undo | rollback refuses (exit 11) | review the listed files; `rollback --partial <tx>` keeps your edits and undoes the rest |
| Rollback failed midway | original transaction `recovery_required` | fix the cause (disk, permissions), run the same rollback again: it resumes |
| "another Agent Forge process is writing" | exit 10 | wait; if no such process exists, delete the lock file named in the message (a lock whose process died is taken over automatically) |
| A backup does not match its recorded hash | rollback refuses that file | restore it by hand from git; the transaction record names the file |
| `plan is stale` / `expired` / `policy changed` | exit 7 | re-run `assign`/`upgrade` (or `/agent-forge-upgrade`) |

Atomicity is per file (temp file + fsync + rename): a crash never leaves a half-written
file. It is not per transaction; recovery above is how a multi-file change is completed or
reversed. See [security.md](security.md#transactions-crashes-and-rollback).

## Supported platforms

| | Supported | Verified in CI |
|---|---|---|
| Python | 3.11 – 3.14 | 3.11, 3.14 |
| OS | Windows 10+, macOS, Linux | windows-latest, ubuntu-latest, macos-latest |
| Coding tools | Claude Code (skills, rules, agents, CLAUDE.md, hooks, MCP); Codex (skills, AGENTS.md) | adapter conformance suite (`tests/conformance/`) |
| Installer | `install.ps1` (PowerShell 5.1+), `install.sh` (POSIX sh) | windows-latest, ubuntu-latest |

Adapters record the date their conventions were last verified (`AdapterInfo.verified_on`);
newer tool versions that change file conventions need an adapter update, which the
conformance suite gates.

## Upgrade, downgrade, uninstall

- **Upgrade:** re-run the installer (or `pip install -U` + `agent-forge init --refresh-registry`
  in a development checkout). Installed projects change only through `/agent-forge-upgrade`
  or `agent-forge upgrade`, plan → approve → apply.
- **Downgrade:** install an older ref (`AGENT_FORGE_REF=<tag>`). Records carry
  `schema_version`; an older engine refuses documents with a version it does not know rather
  than misreading them.
- **Uninstall:** roll back or `remove` capabilities per project, then delete `~/.agent-forge`.

## Schema versions and migration rules

`capability`, `plan`, `transaction`, `project-profile` and `managed.json` carry
`schema_version` (`"1"`). Adding an optional field keeps the version; renaming, removing or
changing the meaning of a field bumps it and ships a migration that reads the old version.
Plans are never migrated: they are short-lived (7-day expiry) and re-planning is cheap.
`python scripts/export_schemas.py --check` (CI) fails when the published schemas drift from
the models.

## Release process

1. `CHANGELOG.md` `Unreleased` → `## x.y.z (date)`; bump `src/agent_forge/__init__.py`
   (the single version source).
2. CI green on the release commit; `agent-forge validate` clean; example report 1.00.
3. Tag `vx.y.z` and push; users pin with `AGENT_FORGE_REF=vx.y.z`.
4. A security fix gets a patch release and a GitHub security advisory (see `SECURITY.md`).
