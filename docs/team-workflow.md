# Agent Forge in a team

Process, not architecture: who approves what, when upgrades run, how conflicts in
`CLAUDE.md` are handled, and how CI keeps every clone at the reviewed state. Pilot teams
copy this page, replace the roles with names, and link it from their repository.

## Roles

| Role | Decides | Tools |
|---|---|---|
| Repository owner | which capabilities the repo uses, when to upgrade | `/agent-forge-upgrade`, `agent-forge forge`, `approve --export-approval` |
| Tech lead | the team policy (`policy.yaml`), hook and MCP approvals, the team registry | `agent-forge policy`, `examples/policy/team-default.yaml` |
| Security | MCP servers and hooks before they are allowed in `policy.yaml` | capability manifests (`catalog show`), `docs/security.md` |
| Every developer | runs `sync` after cloning, never edits managed files by hand | `agent-forge sync`, `check`, `drift` |

## The flow

```text
   developer machine                       git                          CI
 ┌───────────────────────┐        ┌──────────────────────┐      ┌─────────────────────────┐
 │ /agent-forge-upgrade  │        │ .claude/…, CLAUDE.md │      │ uses: …/actions/check   │
 │   scan → plan → diff  │ commit │ .agent-forge/        │ PR   │  forge --approval-file  │
 │   yes → apply         │ ─────► │   managed.json       │ ───► │  check  (exit 0 / 12 /  │
 │ approve --export-     │        │   approval.yaml      │      │         14)             │
 │   approval            │        │   policy.yaml        │      └─────────────────────────┘
 └───────────────────────┘        └──────────────────────┘
                                            │ clone
                                            ▼
                                  ┌──────────────────────┐
                                  │ new developer        │
                                  │  install once        │
                                  │  agent-forge sync .  │
                                  └──────────────────────┘
```

1. **Adopt.** The repository owner runs the installer in the project root, then
   `/agent-forge-upgrade` in Claude Code (or `agent-forge forge .`). They answer the three
   permission questions (shared files, hooks, MCP) within what `policy.yaml` allows.
2. **Record the decision.** `agent-forge approve <plan> --export-approval .agent-forge/approval.yaml`
   writes the approved ids, versions and classes. Commit it with the installed files and
   `.agent-forge/managed.json`. That commit is the review: a PR reviewer sees exactly what
   was allowed.
3. **Keep clones identical.** A developer who clones the repository installs Agent Forge
   once on their machine and runs `agent-forge sync .`. It restores any managed file that is
   missing or was edited, at the committed version, and writes nothing else. Target: under
   10 minutes from clone to a working `/agent-forge-upgrade`.
4. **Gate in CI.** `.github/actions/check` fails a pull request when a managed file drifted,
   a capability was revoked, or `managed.json` is invalid (exit 12), and when a plan would
   go beyond `approval.yaml` (exit 14). Nothing in CI ever needs a person to type yes.
5. **Upgrade on a schedule.** Once a sprint the repository owner runs `/agent-forge-upgrade`
   again, reviews the diff, re-exports the approval file and opens a PR. Capabilities marked
   deprecated or revoked show up in `agent-forge status` and `check` before that.

## Policy

Start from [`examples/policy/team-default.yaml`](../examples/policy/team-default.yaml):
medium risk at most, MCP servers off until security reviewed them, a context budget per
capability. Put it in the workspace (`~/.agent-forge/policy.yaml`) for a team-wide baseline
and in `.agent-forge/policy.yaml` for per-repository tightening. A project can never loosen
the workspace layer.

## Team registry

Capabilities the team does not want public (internal rules, a hook for a private tool) live
in a private git repository with the same layout as `registry/` (`capabilities/<id>/`).
Point the workspace at it:

```yaml
# ~/.agent-forge/agent-forge.yaml
registries:
  - { name: team, path: /path/to/agent-forge-team-registry }
```

The team registry has priority: an id defined in both layers resolves to the team's copy,
and `validate` / `doctor` report the shadowing so it is never silent. Pin integrity there
too (`scripts/pin_integrity.py --registry <path>`); `validate` checks both layers.

## Conflicts in CLAUDE.md and AGENTS.md

Agent Forge only ever writes inside `<!-- agent-forge:begin … -->` / `end` markers. Text
outside the markers is yours; text inside is replaced on upgrade and restored by `sync`.

| Situation | Resolution |
|---|---|
| Two developers edited the same managed section | `agent-forge drift .` shows it; keep your prose outside the markers, let `sync` restore the section |
| A git merge conflict inside the markers | take either side, then `agent-forge sync .` rewrites the section to the committed version |
| The team wants different wording in a managed section | adapt the capability in the team registry (new version) instead of editing the file |
| A developer needs a capability the repo does not use | `agent-forge forge . --request <id>` on a branch, update `approval.yaml` in the PR |

## Feedback

Pilot repositories record their baseline and feedback in [`docs/pilots/`](pilots/README.md).
`agent-forge stats` summarises installs, rollbacks and projects from the local audit log;
nothing is sent anywhere.
