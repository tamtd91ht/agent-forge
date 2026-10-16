# Getting started

## Install (local, no global changes)

```bash
git clone <this repo> agent-forge && cd agent-forge
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
agent-forge --help
```

Requires Python 3.11+ (tested on 3.14) and git on PATH.

## Initialize the workspace

```bash
agent-forge init            # in the repo: verifies registry/, sources/, state/
agent-forge init --workspace ~/.agent-forge   # or anywhere else: seeds registry + sources.yaml
```

`init` is idempotent and never overwrites existing files. Set `AGENT_FORGE_HOME` or pass
`--workspace` to use a workspace that is not the current directory.

## Optional: clone upstream sources

```bash
agent-forge sources clone          # git clone into sources/checkouts/ (network)
agent-forge sources list
agent-forge sources sync --update  # fetch + move checkout; never touches registry or targets
```

Cloning is only needed to re-curate (`scripts/curate.py`) or to verify provenance
(`validate` reports "checkout not present" otherwise). Installing capabilities does not need
the checkouts.

## Upgrade a project (the main flow)

```bash
agent-forge scan   "/path/to/my app"               # read-only profile
agent-forge assign "/path/to/my app" --want security   # writes a plan, not the project
agent-forge diff   plan-…                          # exact changes
agent-forge approve plan-… --shared-files          # binds approval to the plan digest
agent-forge apply  plan-…                          # asks for confirmation, then writes
agent-forge validate "/path/to/my app"
agent-forge status   "/path/to/my app"
```

Useful flags:

- `--platform claude_code|codex` (repeatable) — default is what `scan` detected, else
  `claude_code`.
- `--want <tag>` — request capabilities carrying a tag (`security`, `ui`, `git`, `adr`, …).
- `--request <id>` / `--exclude <id>` — force-consider or never select a capability.
- `--include-optional` — promote optional candidates (high risk / needs permissions).
- `--json` on every command for machine-readable output.

## Undo

```bash
agent-forge rollback tx-…            # refuses if you edited installed files
agent-forge rollback tx-… --partial  # rolls back untouched files, keeps your edits
```

## Keep installed capabilities current

```bash
agent-forge upgrade "/path/to/my app"   # plan only; then diff / approve / apply as above
```
