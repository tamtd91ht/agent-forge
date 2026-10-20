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
| `status` | `discovered` → `under_review` → `curated` (installable) → `deprecated` (no new installs; installed copies reported as warnings) → `revoked` (withdrawn for cause; installed copies are `validate` errors). `rejected` never installable. Transitions are reviewed changes to this file (git history + plan/registry digests record them). |
| `replaced_by` | capability id to use instead of a deprecated or revoked entry; must exist |
| `provenance` | `upstream` (byte-identical) \| `adapted` \| `workspace` \| `generated` |
| `source` | `source_id` from `sources.yaml` (or `workspace`), repository URL, `revision` (must be a full 40-hex commit SHA: a branch or tag can move), upstream paths |
| `license` | SPDX id, attribution line, optional `notice_file` (relative to `assets/`), `redistribution_ok` (required true for curated) |
| `review` | date, reviewer, `rationale` (required for curated), `risk_rationale` (required above `low`: why, and what limits it), `acknowledged_findings` (content-safety findings a reviewer accepted: `rule`, asset `path` glob, `reason`), `signed_off_by` / `signed_off_at`, notes |
| `integrity` | `assets_sha256` pinned by `scripts/pin_integrity.py`. A capability whose assets no longer match is rejected at plan time (`integrity_mismatch`), not only reported by `validate` |
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
   real-registry checks. It also runs the **content-safety scan**
   (`registry/content_safety.py`): pipe-to-shell, broad deletes, `sudo`/`chmod 777`, global
   config writes, embedded credentials, instruction overrides. Each finding is an error until
   `review.acknowledged_findings` explains it (a defensive example is fine; an unexplained one
   is not). The scan is a review aid, not proof of safety.
7. Above `low` risk, write `review.risk_rationale`. Pin integrity with
   `python scripts/pin_integrity.py`; skills that call other skills must list them in
   `dependencies` (ADR-0003).
8. For Codex, the SKILL.md must have `name` and `description` frontmatter and the name must
   equal the directory name.

## Lifecycle

Only `curated` capabilities are recommended. A `deprecated` entry stays installed where it
is and `validate` warns about it; a `revoked` one is a `validate` error in every project that
still has it. Before either change, `agent-forge impact <id>` lists the projects this
workspace installed it into. `rejected` entries stay in the registry as a record of the
decision; the reason for upstream items never curated lives in `docs/rejections/`.
