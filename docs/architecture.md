# Architecture

```
          sources/checkouts/*        registry/capabilities/*        target project
          (untrusted git clones)     (curated, versioned, hashed)   (never modified except by apply)
                  │                          │                              │
   sources ───────┘      scripts/curate.py   │                              │
   list/clone/sync ─────────────────────────►│                              │
                                             │                              │
                           registry.loader ──┤        scanner.* ◄───────────┤ read-only
                                             ▼              ▼               │
                                   matching.rules + scoring + conflicts     │
                                             ▼                              │
                                     planner.builder  ──► state/plans/*.json│
                                             ▼                              │
                                      planner.diff      (approve binds digest)
                                             ▼                              │
                                       apply.engine ───────────────────────►│ atomic writes
                                             │        state/transactions/<tx>/{transaction.json,backup/}
                                             ▼                              │
                               validation.engine / rollback.engine ◄────────┘
```

## Packages (`src/agent_forge/`)

| Package | Responsibility | Writes to target? |
|---|---|---|
| `config` | workspace discovery and `agent-forge.yaml` | no |
| `models/` | Pydantic models: capability, project profile, plan, transaction | no |
| `sources/` | `sources.yaml`, git clone/fetch/compare, provenance checks | no (clones into workspace) |
| `registry/` | load manifests, cross-validate, catalog queries, registry digest | no |
| `scanner/` | bounded read-only walker, language/framework/type detection, agent inventory, managed-manifest validation | no |
| `adapters/` | per-platform conventions: detection, inventory, managed roots, shared files, content rules | no |
| `matching/` | hard rules, equivalence/conflict detection, scoring | no |
| `planner/` | plan construction (file operations with before/after hashes), unified diffs | no |
| `apply/` | path safety, section merge, backups, transactional apply | **yes, only here** |
| `rollback/` | conflict-aware reversal of a transaction | **yes** |
| `validation/` | registry, provenance, managed installs, config syntax, transaction integrity | no |
| `storage/` | JSON documents + SQLite index for plans/transactions | workspace only |
| `cli` | Typer commands, exit codes, JSON output | — |

## Data flow of one upgrade

1. `scan` builds a `ProjectProfile` (evidence + confidence, no secrets) and a fingerprint.
2. `assign` evaluates every curated capability for every chosen platform:
   hard rules → scoring → dependency pull-in → conflict resolution.
3. The planner turns each selected capability into `FileOperation`s with the exact content,
   `before_sha256` of the current destination and `after_sha256` of the projected result,
   then appends the `.agent-forge/managed.json` operation. The plan is saved as JSON.
4. `diff` renders unified diffs against the *current* target and flags staleness.
5. `approve` re-checks staleness and registry digest, then records the content digest.
6. `apply` runs pre-flight (approval, digest, scope, hashes, shared-file approvals), creates
   a transaction, and for each operation: backup → atomic write → read-back → record.
7. `validate` / `status` read the manifest and transaction records; `rollback` reverses only
   files that still hash to their post-apply state.

## Boundaries that must not blur

- Upstream checkouts are never read at plan/apply time; only registry assets are.
- Adapters never write. The only writers are `apply.engine` and `rollback.engine`, and both
  go through `resolve_in_root`.
- User-scoped configuration (`~/.claude`, `~/.codex`, `~/.agents`) is never touched.
