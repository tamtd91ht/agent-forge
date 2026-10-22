# ADR-0011: `import` adopts hand-written agent assets in place

Status: accepted (2026-10-22; owner delegated, see ADR-0010). Input: `roadmap-decision-layer.md`
5.3 ("wrap hand-written config as `<project>.local` in a project-level registry layer;
needs a decision on where that layer lives"), ADR-0001 (the engine is the only writer),
ADR-0004 (the entry skill drives read-only commands), ADR-0007 (decision records, usage log).

## Context

The scouted production configuration has 290 agent assets and no `managed.json`. Nothing
Agent Forge offers after installation (`status`, `drift`, `usage`, `remove`, the `unused`
ground, `decisions report --org`) can see a file it did not install, which in a real team is
most of them. The 5.3 design sketch, a project-level registry layer holding wrapped copies,
would duplicate every file inside the repository, give the scanner a second copy of each
asset to find, and create a new drift (registry copy vs live file) to explain. The team also
edits those files daily; any mechanism that treats such an edit as "drift" would fail
`check` on every PR.

## Decisions

1. **Adopt in place; no registry object, no copy.** `agent-forge import PATH` records each
   hand-written skill, subagent, rule or command in `.agent-forge/managed.json` as a
   `local.<kind>.<name>` entry (version `0.0.0`) with the current hashes of its files. One
   logical asset present on several platforms (`.claude/skills/x` and `.agents/skills/x`)
   is one record. Files whose name starts with `_` (routing tables, templates) are not
   assets and are skipped. Instruction files, settings, hooks and MCP entries are not
   imported: they are shared files or entries, not assets, and the engine already treats
   them as the user's.
2. **The engine writes it, like everything else.** `import` builds a plan whose **only
   operation is the manifest write** (`OperationKind.MANIFEST`, path `.agent-forge/managed.json`);
   `approve`, `apply`, the transaction journal and `rollback` are the ordinary ones. Rolling
   back an import restores the previous manifest and touches no adopted file. `--yes`
   approves and applies in one step, as `setup` and `sync` do, because the single operation
   needs no class beyond `standard`. No new write path, no new operation kind.
3. **A local record is tracked, not installed.** Every code path that resolves a record
   against the registry treats `local.*` honestly: `upgrade` skips it (no source), `sync` /
   `repair --strategy restore` refuse it (nothing to restore from), `validate` reports it as
   information, `status` shows `local`, `check` never fails on it. `remove` deletes its
   files through the normal plan, and `repair --strategy unmanage` stops tracking them
   without touching them.
4. **The team's own edits are not drift.** `drift_report` (hence `check` and `sync`) ignores
   local records; `status` shows an edited file as "edited since import"; **re-running
   `import` refreshes the recorded hashes** through the same manifest write, drops records
   whose files are all gone, and adds files that appeared. The hash is a bookmark for
   `usage` and decisions, not a promise the engine enforces.
5. **Hashes are of normalised text everywhere.** The scanner's manifest check now
   normalises newlines before hashing, like the planner, the validator and `drift_report`
   already did; a CRLF file adopted on Windows is not drift on Linux.
6. **What becomes visible.** `usage` attributes invocations of adopted skills and subagents
   to their `local.*` id, so `unused` can propose removing a hand-written skill nobody calls;
   `decisions verify` accepts a `REMOVE` of a local id on the `unused` ground; `impact` and
   `decisions report --org` count adopted content; the matching engine still refuses to
   write over an adopted file (it is user-owned either way).

## Consequences

- An existing project is under management in one command, with nothing copied and nothing
  rewritten; the catalog and the team's own content appear in one `status` table.
- A `local.*` id is meaningful only inside its project; two projects may both have
  `local.skill.tdd`. Organisation-wide reports group them by id, which is the intended
  question ("how many projects wrote their own TDD skill?").
- `managed.json` grows by one line per adopted asset (290 for the scouted project); it is
  committed, so a reviewer sees adoption as a diff.
- Not done here: adopting instruction files or hook entries; a registry layer generated from
  adopted content (that is `docs/registries.md`, by hand, when content is meant to be shared).
