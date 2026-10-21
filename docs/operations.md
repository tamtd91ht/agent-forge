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
| Coding tools | Claude Code ≥ 2.0 (skills, rules, agents, CLAUDE.md, hooks, MCP); Codex (skills, AGENTS.md); Cursor (rules, instructions, MCP); GitHub Copilot (skills, path instructions, repository instructions); Gemini CLI (skills, GEMINI.md, MCP) | adapter conformance suite (`tests/conformance/`), `doctor` tool-version check, weekly docs watch |
| Installer | `install.ps1` (PowerShell 5.1+), `install.sh` (POSIX sh); installs the latest GitHub Release after verifying the wheel's SHA-256 against `SHA256SUMS` (and its Sigstore bundle when `cosign` is present); `AGENT_FORGE_VERSION` pins one; stops with exit 1 when no release can be resolved (never falls back to `main`); writes `~/.agent-forge/VERSION` (`ref`, `verified`, `installed_at`) that `doctor` reports | windows-latest, ubuntu-latest, macos-latest (install from a checkout, and the "unverifiable release is not installed" path) |

Adapters record the date their conventions were last verified (`AdapterInfo.verified_on`)
and the tool version range (`min_version`/`max_version`); a tool outside the range is
refused at planning time (exit 15). The weekly `docs-watch` workflow opens an issue when a
verified documentation page changes; the adapter update is gated by the conformance suite.

## Distribution

| Channel | Command | Notes |
|---|---|---|
| Installer (recommended) | `install.ps1` / `install.sh` in a project root | latest release, checksum (+ Sigstore with `cosign`) verified, venv in `~/.agent-forge`, launcher, `VERSION`, `setup`; `AGENT_FORGE_REF=<branch>` installs an **unverified** archive for development only |
| uvx | `uvx --from "git+https://github.com/tamtd91ht/agent-forge@vX.Y.Z" agent-forge …` | no Python management by the team; run `init --workspace` once |
| pipx | `pipx install "git+https://github.com/tamtd91ht/agent-forge@vX.Y.Z"` | same |
| CI | `.github/actions/check` | installs a release into the runner, runs `check` (and `forge --approval-file`) |
| Wheel / sdist | attached to every GitHub Release with `SHA256SUMS` and Sigstore bundles | `pip install agent_forge-X.Y.Z-py3-none-any.whl` |

A standalone binary (PyInstaller) is not shipped yet: the Rich/Typer/Pydantic stack builds
cleanly, but the launcher and workspace layout the entry skill relies on would need a second
code path, so it waits for pilot feedback.

## Upgrade, downgrade, uninstall

- **Upgrade:** re-run the installer (or `pip install -U` + `agent-forge init --refresh-registry`
  in a development checkout). Installed projects change only through `/agent-forge-upgrade`
  or `agent-forge upgrade`, plan → approve → apply.
- **Downgrade:** install an older release (`AGENT_FORGE_VERSION=<tag>`). Records carry
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

One page, so a second maintainer can do it without the first.

1. **Prepare the commit.** `CHANGELOG.md`: move `Unreleased` into `## x.y.z — YYYY-MM-DD`
   (the release workflow refuses a tag without that heading). Bump `__version__` in
   `src/agent_forge/__init__.py` (single source) and run `uv lock` so `uv.lock` records the
   new version. Semver: breaking CLI/JSON change → major (after 1.0) or minor (before),
   new command or capability → minor, fix → patch.
2. **Verify locally.** `/verify` in Claude Code, or `ruff`, `pytest`, `agent-forge validate`,
   `scripts/export_schemas.py --check`, `scripts/matching_report.py`. CI must be green on
   the commit.
3. **Tag and push.** `git tag -a vx.y.z -m "agent-forge vx.y.z" && git push origin vx.y.z`.
   `.github/workflows/release.yml` then: checks the tag against the package version and the
   changelog; re-runs the verification from `uv.lock`; builds sdist and wheel; writes
   `SHA256SUMS`; generates a CycloneDX SBOM; signs every file with Sigstore (keyless, the
   workflow's OIDC identity); publishes the GitHub Release with the changelog section as
   notes. Installers resolve this release as "latest" from then on.
4. **Check the release page.** Files: `agent_forge-x.y.z.tar.gz`, `agent_forge-x.y.z-py3-none-any.whl`,
   `install.sh`, `install.ps1`, `uv.lock`, `SHA256SUMS`, `*.cdx.json`, and one `.sigstore.json`
   bundle per file. Run the installer on a clean machine with `AGENT_FORGE_VERSION=vx.y.z`.
5. **Security fix:** patch release plus a GitHub security advisory (`SECURITY.md`).

Repository metadata (once, by a maintainer with admin rights):

```bash
gh repo edit tamtd91ht/agent-forge --description "Reviewed skills, rules, hooks and MCP servers for Claude Code, Codex and other coding agents: scan, plan, approve, apply, roll back."   --add-topic claude-code --add-topic codex --add-topic ai-coding --add-topic mcp --add-topic developer-tools --add-topic cursor --add-topic copilot
```

## Verifying a release

```bash
# 1. checksums
sha256sum -c SHA256SUMS
# 2. Sigstore signature of any file (identity = this repository's release workflow)
pipx run sigstore verify github install.sh   --bundle install.sh.sigstore.json   --repository tamtd91ht/agent-forge   --ref refs/tags/vx.y.z
# 3. pin the installer to that release
AGENT_FORGE_VERSION=vx.y.z sh install.sh
```

A release whose signature does not verify, or whose `SHA256SUMS` does not match, must not be
installed; report it through `SECURITY.md`.
