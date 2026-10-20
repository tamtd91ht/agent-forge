# ADR-0006: Canonical capability content, per-adapter rendering, more platforms

Status: accepted (2026-10-20). Input: the 6-month plan phase 2
([roadmap-2026h2.md](../roadmap-2026h2.md)), ADR-0001 D13 (adapters never rewrite content
silently), the adapter conformance suite (ADR-0005 §6).

## Context

Every curated capability carried one asset copy per platform (`assets/claude_code/x`,
`assets/codex/x`), byte-identical for skills. Adding Cursor, GitHub Copilot and Gemini CLI
that way would multiply the registry by five and make every content fix a five-file change.
At the same time the formats are *not* identical: Cursor rules are `.mdc` with
`globs`/`alwaysApply`, Copilot path rules carry `applyTo`, Gemini's MCP settings have no
`type` key. The plan proposed a tool-neutral canonical format with adapters transpiling to
the target. The question was where that boundary sits so that the invariants of ADR-0001
(deterministic plans, content hashes bound to approvals, nothing rewritten at apply time) hold.

## Decisions

1. **Claude Code formats are the canonical content.** A skill is a SKILL.md directory (Agent
   Skills format, shared with Codex, Copilot and Gemini verbatim); a rule is markdown with
   optional `description` and `paths` frontmatter; an instruction is a markdown section; an
   MCP fragment is `{"mcpServers": {...}}` in the Claude Code shape. No second schema is
   introduced: the manifest stays as in `capability-model.md`, and a destination simply
   points its `source` at the canonical asset (`claude_code/<name>`), for any platform.
2. **Rendering is a pure adapter function, run by the planner.** `PlatformAdapter.render(kind,
   rel_path, content)` transpiles canonical content into the platform's format. The planner
   calls it in `_asset_files` for every primary file of a destination, so the plan, the
   diff, the content hash the approval binds to and `managed.json` all carry the *rendered*
   bytes. `apply` writes what the plan holds; it never transforms. Rendering must be
   deterministic: same input, same output, on every OS (CRLF input normalised). The default
   is the identity; today Cursor renders rules and instructions, Copilot renders rules,
   Gemini renders MCP fragments.
3. **Conformance gates every adapter.** `tests/conformance/test_render.py` renders canonical
   fixtures for every kind an adapter supports, requires the adapter's own
   `validate_content` to accept the result, checks determinism, and renders every curated
   destination of the real registry. An adapter is supported only when the whole
   conformance suite passes unchanged (ADR-0005 §6 still applies).
4. **Three new adapters**, each with the official page and date in its docstring: Cursor
   (`.cursor/rules/**/*.mdc`, `.cursor/mcp.json`; instructions as `alwaysApply` rules because
   `AGENTS.md` is owned by the Codex adapter), GitHub Copilot
   (`.github/copilot-instructions.md`, `.github/instructions/*.instructions.md`,
   `.github/skills/<name>/SKILL.md`), Gemini CLI (`GEMINI.md`, `.gemini/skills/<name>/SKILL.md`,
   `.gemini/settings.json` `mcpServers`). Kinds a platform cannot express are listed in
   `unsupported_notes`, never approximated (ADR-0001 D13).
5. **Tool versions are detected and bounded.** `AdapterInfo.version_command`, `min_version`
   and `max_version` record how to ask the tool and the range the conventions were verified
   for. `doctor` reports the detected version; planning commands refuse a tool outside the
   range with both versions named (exit 15) and only note a tool that is absent or silent.
6. **Upstream documentation is watched.** `scripts/watch_docs.py` stores a digest of each
   verified page (`adapters/docs_hashes.json`); a weekly workflow opens an issue when a
   page changes, and the fix is a PR that re-verifies, bumps `verified_on` and updates the
   digests together.

## Consequences

- 24 curated capabilities gained Cursor / Copilot / Gemini destinations without a single new
  asset file; a content fix is still one file.
- Platform-specific asset copies (`assets/codex/...`) remain valid and are kept where the
  content really differs (Codex `agents/openai.yaml` manifests). New capabilities should
  point every platform at the canonical asset unless the content must differ.
- `Platform` gained three values; plans, profiles and policies accept them; JSON schemas were
  re-exported.
- Rendering changes the installed bytes compared with the asset, so `drift` and `sync`
  compare against the rendered hash recorded in `managed.json`, which is what the planner
  stored. Nothing compares an installed file with a raw asset.

## Rejected

- A separate neutral schema (YAML "capability IR") in addition to the manifest: a second
  format to validate and keep in sync, for no information the manifest and the canonical
  asset do not already hold.
- Rendering at apply time: would break the approval ↔ content-hash binding and make the
  diff shown at approval differ from what is written.
- Owning `AGENTS.md` from more than one adapter: `platform_owning` must be unique for
  rollback, drift and remove to attribute a file; Cursor instructions are rules instead.
