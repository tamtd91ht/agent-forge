# Capability model and authoring guide

A capability is a directory under `registry/capabilities/<id>/`:

```
registry/capabilities/ecc.tdd-workflow/
├── capability.yaml          # metadata (this document)
└── assets/
    ├── claude_code/tdd-workflow/SKILL.md        # content per platform
    ├── claude_code/tdd-workflow/LICENSE-ECC.txt
    └── codex/tdd-workflow/{SKILL.md,LICENSE-ECC.txt}
```

The directory name must equal `id`. JSON Schema: `registry/schema/capability.schema.json`
(generated from `agent_forge.models.capability.Capability`; regenerate with
`python scripts/export_schemas.py`). Unknown fields are rejected.

## Fields

| Field | Meaning |
|---|---|
| `id` | lowercase segments joined by `.` (`source.name`), e.g. `ecc.tdd-workflow` |
| `version` | semver of *this curated packaging*, bumped when assets or destinations change |
| `kind` | `skill` \| `rule` \| `agent` \| `instruction` \| `hook` \| `mcp` \| `reference` |
| `status` | `discovered` → `under_review` → `curated` (installable) / `deprecated` / `rejected` |
| `provenance` | `upstream` (byte-identical) \| `adapted` \| `workspace` \| `generated` |
| `source` | `source_id` from `sources.yaml` (or `workspace`), repository URL, 40-char commit SHA, upstream paths |
| `license` | SPDX id, attribution line, optional `notice_file` (relative to `assets/`), `redistribution_ok` (required true for curated) |
| `review` | date, reviewer, rationale (required for curated), notes |
| `applicability` | `always`, `project_types`, `languages`, `frameworks`, `any_of_files`, `tags`. Non-empty lists are ANDed; `tags` only match `--want`. Tag-only capabilities are installed on request only. |
| `platforms` | `claude_code`, `codex` |
| `install_strategy` | `file_copy` \| `section_merge` \| `native_plugin` \| `reference_only` |
| `destinations` | per platform: `source` (file or dir under `assets/`), `dest` (relative to target), `merge` (`create_only` \| `replace_managed` \| `append_section` + `section_id`) |
| `dependencies` / `conflicts` | capability ids; conflicts should be declared symmetrically |
| `equivalents` | signals that the project already has this: asset `kind`, `name_patterns`, `content_patterns` (matched against headings + description) |
| `permissions` / `network` / `runtime_requirements` | surfaced in reports; permissions make a candidate optional unless requested |
| `risk` | `low` \| `medium` \| `high` (high ⇒ optional unless requested) |
| `benefit_score` / `maintenance_cost` | 0–10, used only for ranking survivors |
| `validation` | declared checks shown in the plan (`file_exists`, `frontmatter`, …) |
| `removal` | `delete_managed_files` \| `remove_section` |

## Authoring checklist

1. Add the source to `sources/sources.yaml` and clone it.
2. Read the upstream file(s). Record what they depend on (scripts, hooks, MCP, env vars).
   Anything that executes code is not `file_copy`; model it as `native_plugin`.
3. Check the license of *that file* (ECC has per-skill `license:` frontmatter overrides).
4. Add an entry to `scripts/curate.py` listing exact files, run it, and review `git diff`.
5. Write `capability.yaml`; make `equivalents` specific enough to avoid duplicates.
6. `agent-forge validate` must report 0 errors; `pytest tests/unit/test_registry.py` runs the
   real-registry checks.
7. For Codex, the SKILL.md must have `name` and `description` frontmatter and the name must
   equal the directory name.

## Lifecycle

Only `curated` capabilities are recommended. `deprecated` ones are left installed and
reported by `upgrade`; `rejected` ones stay in the registry as a record of the decision.
