# Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `No Agent Forge workspace found` (exit 3) | not inside a workspace and no `AGENT_FORGE_HOME` | `agent-forge init`, or pass `--workspace`, or set `AGENT_FORGE_HOME` |
| `plan is stale; target files changed since planning` (exit 7) | a destination changed after `assign` | re-run `assign`/`upgrade`, then `diff`, `approve` |
| `registry changed since planning` (exit 7) | curated assets edited (e.g. after `curate.py`) | re-run `assign` |
| `plan modifies shared files` (exit 6) | plan touches `CLAUDE.md`/`AGENTS.md`/settings | review `diff`, then `approve --shared-files` |
| `interactive confirmation required (no TTY)` (exit 6) | `apply`/`rollback` without a terminal | use `--yes` after reviewing `diff` |
| `approval digest does not match` (exit 8) | plan file edited after approval | `approve --revoke`, re-run `assign`; never hand-edit plans |
| `destination exists and is user-owned` | an unmanaged file sits where a capability installs | remove/rename it, or `--exclude` the capability |
| `files changed independently after apply` (exit 11) | you edited installed files | keep them: `rollback --partial`; or revert your edits first |
| `transaction … already exists` | a plan is applied at most once | create a new plan |
| `symlink or reparse point in path` (exit 9) | `.claude/` or a parent is a symlink/junction | replace it with a real directory; Agent Forge will not follow links |
| `.agent-forge/managed.json is present but invalid` | hand-edited or corrupted manifest | restore from git, or delete it and re-`assign` (orphaned files remain user-owned) |
| `UnicodeEncodeError` on Windows | legacy console code page | fixed in CLI (`main()` forces UTF-8); if running the module directly set `PYTHONUTF8=1` |
| Scan shows wrong language/framework | evidence-based detection only reads manifests at depth ≤1 | check `--json` evidence; pass `--request`/`--exclude` to steer `assign` |
| `catalog` table truncates ids | narrow terminal | widen, or use `--json` |
| Symlink tests skipped | Windows without symlink privilege | enable Developer Mode, or rely on the junction tests |
