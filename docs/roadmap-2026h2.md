# 6-month plan: from a personal tool to the team's platform

Written 2026-10-20 from the owner's proposal (`agent-forge-roadmap.html`, 41 items in five
phases). This file is the tracked version: one line per item, its status in this repository,
and what is left for a person to do. [engineering-roadmap.md](engineering-roadmap.md) keeps
the release gates; accepted ADRs still win over anything here.

Status: ✅ done in the repo · 🟡 done in the repo, needs a human action to complete ·
⏳ not started · 👤 only a person can do it (noted what the repo provides).

## Phase 0 · Stabilise and ship the first release (weeks 1–2)

| # | Item | Status | Evidence / what is left |
|---|---|---|---|
| 0.1 | Tag the first release, one-page release process | 🟡 | version 0.2.0, `CHANGELOG.md` section, `release.yml` (tag check, build, SHA256SUMS, SBOM, Sigstore, Release notes), `operations.md#release-process`. **Left:** `git tag -a v0.2.0 && git push origin v0.2.0` by a maintainer. (0.1.0 was the untagged initial build; the first tag is 0.2.0.) |
| 0.2 | Installers pinned to a tag, not `main` | ✅ | `install.sh` / `install.ps1` resolve the latest Release; `AGENT_FORGE_VERSION` pins; `main` only as a stated fallback; checksums + signatures attached by `release.yml` |
| 0.3 | Dependency lock, CI from the lock | ✅ | `uv.lock` (cross-platform), `uv sync --locked` in CI on 3 OS, pip-audit on the locked set |
| 0.4 | macOS installer smoke test | ✅ | `ci.yml` installer matrix includes macos-latest |
| 0.5 | Clean the repo root | ✅ | `docs/history/` with a header line in each file; references updated |
| 0.6 | Repo description, topics, badges | 🟡 | badges in README; `gh repo edit` command in `operations.md`. **Left:** run it (admin rights) |
| 0.7 | 5-minute quickstarts per stack + GIF | 🟡 | `docs/quickstart/{node,python,go,java}.md`. **Left:** record a ≤30 s GIF for the README |

## Phase 1 · Package it for the team's running projects (weeks 3–6)

| # | Item | Status | Evidence / what is left |
|---|---|---|---|
| 1.1 | Pick 3 pilot repos, record the baseline | 👤 | `docs/pilots/README.md` + `TEMPLATE.md` (measures, how to measure). **Left:** choose repos, fill the baseline |
| 1.2 | Private team registry with priority | ✅ | `registries:` in `agent-forge.yaml`, team wins on duplicate id, shadowing reported by `validate`/`doctor`; `docs/registries.md` |
| 1.3 | Team policy template (strictest wins) | ✅ | `examples/policy/team-default.yaml`, loaded in a test |
| 1.4 | Non-interactive CI: approval by file, clear exit code | ✅ | `approve --approval-file`, `forge --approval-file`, `--export-approval`; exit 14 in `cli-reference.md` and `test_exit_codes` |
| 1.5 | `check` as the CI gate + official Action | ✅ | `agent-forge check` (exit 0/12), `.github/actions/check` |
| 1.6 | `sync` for a fresh clone | ✅ | restores files and sections at the pinned versions; `team-workflow.md` target < 10 min |
| 1.7 | Distribution without manual Python: uvx/pipx, trial binary | 🟡 | uvx/pipx documented (README, operations). **Left:** a PyInstaller binary was deliberately not shipped (launcher/workspace layout needs a second code path); revisit after pilot feedback |
| 1.8 | Local usage log and feedback channel (opt-in, offline) | ✅ | `agent-forge stats [--since]` from the audit log; feedback template in `docs/pilots/` |
| 1.9 | "Agent Forge in team X" process page | ✅ | `docs/team-workflow.md` (roles, flow diagram, CLAUDE.md conflicts). **Left:** pilot tech leads review it |
| 1.10 | Pilot retrospective, go / no-go ADR | 👤 | retrospective outline in `docs/pilots/README.md`; ADR number reserved (0007) |

## Phase 2 · Every coding tool, not only Claude Code (weeks 7–12)

| # | Item | Status | Evidence / what is left |
|---|---|---|---|
| 2.1 | Tool-neutral canonical capability format | ✅ | ADR-0006: Claude Code formats are canonical; no second schema; `envelope`/manifest schemas exported |
| 2.2 | Per-adapter transpile layer in the planner, deterministic | ✅ | `PlatformAdapter.render`, called in `_asset_files`; `tests/conformance/test_render.py` (CRLF/LF same hash, every curated destination) |
| 2.3 | Cursor adapter | ✅ | `adapters/cursor.py`, verified 2026-10-20 |
| 2.4 | GitHub Copilot adapter | ✅ | `adapters/copilot.py`, verified 2026-10-20; unsupported kinds listed with reasons |
| 2.5 | Gemini CLI adapter | ✅ | `adapters/gemini.py`, verified 2026-10-20 |
| 2.6 | Finish the Codex adapter (subagents, hooks, MCP) | ⏳ | waits for upstream trust model; `version_command` added |
| 2.7 | Windsurf, Cline/Roo, Aider, Junie | ⏳ | by demand; `docs/adapters.md#adding-a-platform` is the recipe; legacy files are detected |
| 2.8 | Alert when official docs change | ✅ | `scripts/watch_docs.py` + weekly `docs-watch` workflow + stored digests (13 pages) |
| 2.9 | Detect tool versions, refuse incompatible ones clearly | ✅ | `adapters/tool_versions.py`, `doctor`, exit 15; Claude Code ≥ 2.0.0 |

## Phase 3 · Prove capabilities make code better (months 4–5)

| # | Item | Status | Evidence / what is left |
|---|---|---|---|
| 3.1 | Opt-in evaluation harness (separate package) | ✅ | `tools/agent-forge-eval` (claude -p / codex exec, scripted runner for tests) |
| 3.2 | Task sets for the 6 fixtures | 🟡 | 30 tasks (5 per fixture) in `examples/*/tasks/`. **Left:** second reviewer per task set |
| 3.3 | Measure the 5 core skills with confidence intervals | 👤 | plan and budget in `evaluation.md`. **Left:** run it (needs the tool, ~30 sessions per fixture) |
| 3.4 | Evaluation results in the manifest (`review.evidence`) | ✅ | model + schema + `catalog show` table |
| 3.5 | Scanner precision/recall on ≥ 20 anonymised real repos | 🟡 | `matching_report.py --corpus --min-precision --min-recall`. **Left:** build the anonymised corpus (outside the repo) |
| 3.6 | Context cost shown in plans, warning above policy | ✅ | `ctx` column + total; `max_total_context_chars` note and decision line |

## Phase 4 · Open it to projects outside the team (months 5–6)

| # | Item | Status | Evidence / what is left |
|---|---|---|---|
| 4.1 | Sign releases and registry digests (Sigstore) | 🟡 | every release file signed keyless in `release.yml`; verification in `operations.md`. **Left:** `agent-forge verify` of a downloaded registry (needs the registry-as-artifact step, 4.7) |
| 4.2 | SBOM per release | ✅ | CycloneDX in `release.yml`, release fails without it |
| 4.3 | JSON envelope v1 for every `--json` command | ✅ | `models/envelope.py`, `envelope.schema.json`, `test_json_envelope.py` snapshot of every command |
| 4.4 | Capability versioning and dependency constraints | ✅ | semver already; `dependencies: ["id >=1.2.0 <2.0.0"]`, checked in `validate`, matching and installed projects; `upgrade` plans name old → new version |
| 4.5 | Capability submission process (template, CI, 2 reviewers) | 🟡 | `docs/contributing-capabilities.md`, PR template, CI checks, CODEOWNERS. **Left:** branch protection + 3 external submissions |
| 4.6 | Deprecate / revoke / replace policy with user-facing notice | ✅ | `docs/deprecation-policy.md`; `status` prints the line; tests |
| 4.7 | Public registry in its own repo, static hosting, index + digest | 🟡 | layered registries + `docs/registries.md` ("your own registry in 10 minutes"). **Left:** create `agent-forge-registry`, HTTP index |
| 4.8 | Documentation site | 🟡 | `mkdocs.yml` + `docs-site.yml` (GitHub Pages). **Left:** enable Pages once |
| 4.9 | Second and third maintainer, CODEOWNERS, merge rules | 🟡 | `MAINTAINERS.md`, `CODEOWNERS`. **Left:** the people |
| 4.10 | v1.0 and the announcement with numbers | 👤 | depends on 1.10 and 3.3 |

## Governance and KPIs (cross-cutting)

| KPI | Now | Where it is measured |
|---|---|---|
| Team projects using Agent Forge | 0 | `docs/pilots/` |
| Fully supported platforms | 5 adapters (Claude Code, Codex, Cursor, Copilot, Gemini CLI) | `tests/conformance` |
| Onboarding time into a repo with AF | not measured | pilot template, target < 10 min with `sync` |
| Capabilities with evaluation evidence | 0 of 33 | `catalog show`, `review.evidence` |
| Failed rollbacks in practice | not measured | pilot weekly log |
| Maintainers with release rights | 1 | `MAINTAINERS.md` |

The four principles in the proposal are unchanged and enforced: no writes outside managed
roots and never executing registry content (`filesystem_safety`, content-safety scan); a
person approves every shared-file, hook and MCP change (approval classes, approval files);
every feature ships with a proving test and a changelog line; architecture decisions are
ADRs and the vision yields to an accepted ADR.
