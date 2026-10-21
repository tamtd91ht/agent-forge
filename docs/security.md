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
  `sources clone` / `sources sync`, and the installer's download of Agent Forge itself
  (`pip install` of the GitHub archive into `~/.agent-forge/.venv`, ADR-0004).
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
| `.git` in any case, alternate data streams | `.git/hooks/x`, `a.md:stream` |
| a name equal to an existing entry up to case or Unicode normalisation | `.Claude/` next to `.claude/`, NFD `é` next to NFC `é` |
| a resolved path outside the resolved root | always re-checked after resolution |

Writes go through `safe_write_bytes`: missing directories are created one at a time and the
whole chain is re-checked immediately before the atomic rename. **Residual limit:** a local
process that can write to the project could still swap a directory in the instant between
that last check and the rename; the per-target lock only excludes other Agent Forge
processes. Agent Forge is not a sandbox (see *Runtime boundary*).

Planner and apply additionally require every path to be inside the adapter's managed roots
(`CLAUDE.md`, `.claude/`, `.mcp.json`, `AGENTS.md`, `.agents/skills/`, `.codex/`,
`.agent-forge/`). The scanner never follows symlinks or junctions and reads at most
`max_file_bytes` per file.

## Plan integrity

A plan's digest covers the target identity, every operation (path, content hash, before and
after hashes, approval class), the selected capabilities, the registry digest (manifests,
assets **and shipped policies**), the effective **policy digest**, and `created_at` /
`expires_at`. Apply refuses a plan when any of these no longer holds:

- **Approval is anchored in the workspace.** `approve` writes the digest to
  `state/approvals/<plan>.json`; apply requires the plan's current digest to equal it. The
  digest is plain SHA-256, so an edited plan could be re-hashed by hand: the anchor means it
  still needs a fresh `approve`, which the audit log records. (An attacker who can write the
  workspace itself is out of scope: the workspace is the trust anchor.)
- Every operation stores `before_sha256`; apply refuses if the file changed since planning,
  and re-checks each file again immediately before writing it.
- Registry or policy changed since planning → stale. A project `policy.yaml` that is invalid
  stops planning (fails closed) instead of being ignored.
- Plans expire 7 days after creation (`expires_at`, inside the digest).
- Shared-file, hook and MCP operations need their approval class.
- `--yes` only skips the terminal prompt; it cannot bypass any of the above.

## Transactions, crashes and rollback

- Apply and rollback hold an exclusive per-target lock (`state/locks/`, O_EXCL, owner pid).
  A second process gets a clear error; a lock left by a dead process is taken over.
- Per operation: re-check hash → back up prior bytes (`state/transactions/<tx>/backup/`,
  with their exact sha256) → **journal** (record saved with the intended hash) → re-check the
  path → atomic write (temp file, fsync, rename) → read back → mark applied.
- **Atomicity is per file, not per transaction.** A crash leaves each file either old or
  new, never partial; the transaction may stop `in_progress` with its last write journaled
  but unconfirmed. `validate`, `doctor` and `status` report such transactions, and
  `agent-forge rollback <tx>` recovers them: a journaled operation whose file still has its
  before hash is skipped, one at its intended hash is reversed, anything else is a conflict.
- If saving the failure record itself fails, the original error is still reported; the
  journal on disk is what rollback uses.
- A rollback that fails midway marks the original `recovery_required`; running rollback
  again resumes it (already-restored files are skipped).
- Transaction records are sealed with a hash; rollback refuses tampered records. Backups are
  restored only when their bytes match the recorded sha256, and backup names are validated.
- Rollback restores only files whose current hash equals the recorded post-apply hash. Files
  the user changed afterwards are kept (strict mode refuses everything; `--partial` rolls
  back the untouched files). For shared files, only the managed section is removed when the
  rest of the file changed.

## Policy (deterministic, layered, tighten-only)

Three YAML layers are merged with "strictest verdict wins": `registry/policies/default.yaml`
(part of the registry digest), `<workspace>/policy.yaml`, and the untrusted
`<target>/.agent-forge/policy.yaml` (validated; an invalid file stops planning: it fails
closed, because ignoring it would drop the restrictions it was written to add). Each capability gets one verdict before scoring:

| Verdict | Effect |
|---|---|
| `allow` | normal rules and ranking |
| `require_request` | planned only with `--request <id>` / `--want <tag>` |
| `deny` | rejected as `policy_denied`; dependants of a denied capability are rejected too |

Rules available: `max_risk`, `require_request_from_risk`, `capabilities.{deny,require_request,allow_only,deny_tags}` (id globs), `grants.{process_execute,network_access,secrets_read}`, `classes.{shared_file,hook,mcp}` (switch a class off), `platforms`, `require_signoff`, `max_context_chars` (always-loaded context budget per capability, see ADR-0003).
Policy never *grants* anything: approval classes are still enforced by `approve`/`apply`.

Every curated entry pins `integrity.assets_sha256`; `validate` fails if installed content
in the registry was edited without re-pinning. `review.signed_off_by` records the human who
approved the curation; `doctor` counts them and `require_signoff: true` makes it mandatory.

## Approval classes

Every operation carries an `approval_class`; `approve` (and `forge`) must grant each class
explicitly, and `apply` refuses operations whose class was not granted:

| Class | Where it writes | Why it is separate | Flag |
|---|---|---|---|
| `standard` | new files under `.claude/skills`, `.claude/rules`, `.claude/agents`, `.agents/skills` | isolated, no execution | (always) |
| `shared_file` | marker section in `CLAUDE.md` / `AGENTS.md` | touches a file the user owns | `--shared-files` |
| `hook` | JSON fragment merged into `.claude/settings.json` (+ a script under `.claude/hooks/agent-forge/`) | hooks **execute commands** in every session | `--hooks` |
| `mcp` | JSON fragment merged into `.mcp.json` | MCP servers **launch processes** and use the network; Claude Code also asks the user to trust project servers | `--mcp` |

Fragments are merged, never overwritten: other hooks, settings and servers are preserved;
an existing MCP server with the same name but a different config is a planning error.
Rollback removes exactly the merged entries, even if the user added their own afterwards.
Curated hooks are dependency-free scripts (Python or Node) that only ever act on the single
file the agent just edited, never download anything, and exit 0 when their tool is absent.

## Curated content

- Only `status: curated` capabilities with `license.redistribution_ok: true` can be
  installed; manifests record source URL, commit SHA and upstream paths, and `validate`
  checks that the SHA and paths exist in the checkout.
- Upstream hooks and installers are excluded from the registry; the hooks Agent Forge ships
  are workspace-authored and reviewed line by line. Capabilities that need a runtime are
  `native_plugin`: recommended with install hints, never executed.
- Installed assets carry the upstream MIT notice (`LICENSE-*.txt`) or an attribution footer.

## Reports and logs

Scan reports go to `state/reports/` (never inside the target unless `--report` points
there, which is refused when it resolves inside the target). Profiles contain file names,
hashes and headings, not file contents or secret values. `state/` and `sources/checkouts/`
are git-ignored.

## Runtime boundary

Agent Forge decides what is written into a project and records it. It does not sandbox the
coding agent afterwards: what an installed hook, MCP server or the agent itself may execute
is governed by Claude Code / Codex permissions, the operating system or a container.

## Local data, no telemetry

`lint`, `usage`, `decisions` and `stats` read only the project and the workspace; nothing
is sent anywhere. The usage log (`forge.hook.usage-log`, opt-in) records skill / subagent
ids, timestamps and a short session id, never prompts, file contents or paths. A decision
record is the agent's own file; `decisions verify` reads cited files only through
`filesystem_safety`, so a citation cannot make the engine read outside the project. The
installer contacts GitHub only to resolve and download a release; `doctor` does so only with
`--check-latest`.

## Known gaps

- Symlink tests skip on Windows without the symlink privilege (junction tests run instead).
- `validate` does not run project test commands; it only lists them.
- Hooks and MCP servers are Claude Code only; Codex hooks/MCP live in `.codex/*` (trusted
  projects, per-hash hook trust) and are not managed.
