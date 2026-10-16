# Security model

Threat model: the target project, the upstream repositories and the plan/transaction files
on disk are all **untrusted inputs**. Agent Forge must not let any of them execute code,
read secrets, or write outside the approved scope.

## What Agent Forge never does

- Run project scripts, upstream installers, hooks, or downloaded executables.
- Install dependencies into a target.
- Modify `~/.claude`, `~/.codex`, `~/.agents`, or any directory outside the target root and
  its own workspace.
- Upload anything. The only network calls are `git clone/fetch` when you run
  `sources clone` / `sources sync`.
- Read files that look like secrets (`.env*`, `*.pem`, `id_rsa`, `credentials*`…); they are
  listed by name in the profile and never opened.

## Filesystem boundaries (`apply/filesystem_safety.py`)

Every destination path is validated and resolved by `resolve_in_root`:

| Rejected | Example |
|---|---|
| absolute paths, drive letters, UNC | `/etc/x`, `C:\x`, `\\srv\share` |
| traversal | `../x`, `a/../../b` |
| control / reserved characters, trailing dot or space, Windows device names | `CON`, `a<b`, `x. ` |
| any existing component that is a symlink **or a reparse point (junction)** | `.claude -> /elsewhere` |
| a resolved path outside the resolved root | always re-checked after resolution |

Planner and apply additionally require every path to be inside the adapter's managed roots
(`CLAUDE.md`, `.claude/`, `.mcp.json`, `AGENTS.md`, `.agents/skills/`, `.codex/`,
`.agent-forge/`). The scanner never follows symlinks or junctions and reads at most
`max_file_bytes` per file.

## Plan integrity

- Approval records `sha256(plan content)`; any edit to the plan file invalidates it.
- Every operation stores `before_sha256`; apply refuses if the file changed since planning.
- The registry digest is stored; apply refuses if curated content changed.
- Shared-file operations (`CLAUDE.md`, `AGENTS.md`, settings) need `approve --shared-files`.
- `--yes` only skips the terminal prompt; it cannot bypass any of the above.

## Transactions and rollback

- Each operation backs up the prior content under `state/transactions/<tx>/backup/`,
  writes atomically (temp file + rename), reads back and verifies the hash, then persists the
  transaction record. A crash leaves either the old or the new file, never a partial one.
- Transaction records are sealed with a hash; rollback refuses tampered records.
- Rollback restores only files whose current hash equals the recorded post-apply hash. Files
  the user changed afterwards are kept (strict mode refuses everything; `--partial` rolls
  back the untouched files). For shared files, only the managed section is removed when the
  rest of the file changed.

## Curated content

- Only `status: curated` capabilities with `license.redistribution_ok: true` can be
  installed; manifests record source URL, commit SHA and upstream paths, and `validate`
  checks that the SHA and paths exist in the checkout.
- Upstream hooks, MCP declarations, scripts and installers are excluded from the registry
  in v0.1. Capabilities that need a runtime are `native_plugin`: recommended with install
  hints, never executed.
- Installed assets carry the upstream MIT notice (`LICENSE-*.txt`) or an attribution footer.

## Reports and logs

Scan reports go to `state/reports/` (never inside the target unless `--report` points
there, which is refused when it resolves inside the target). Profiles contain file names,
hashes and headings, not file contents or secret values. `state/` and `sources/checkouts/`
are git-ignored.

## Known gaps

- Symlink tests skip on Windows without the symlink privilege (junction tests run instead).
- `validate` does not run project test commands; it only lists them.
- Hooks/MCP installation is deferred to a later release with its own approval class.
