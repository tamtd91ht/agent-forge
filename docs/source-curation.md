# Source curation record (initial catalog 2026-10-16, last update 2026-10-24)

Principle: small, verified, low-duplication. Every item below was read in the checkout at the
recorded revision. "Verbatim" means byte-identical to upstream.

## Curated (139)

### Stack-specific ECC content (0.4.0, 89 capabilities)

A Java/Kafka/Redis service used to receive only the stack-agnostic, TypeScript-flavoured
skills (`ecc.tdd-workflow` teaches Vitest, `ecc.security-review` shows Express). ECC ships
per-language rule packs and framework skills; they are curated as one capability each so the
resolver and `/agent-forge-upgrade` pick by stack. Everything below is from ECC at the pinned
revision, one file per item, copied by `scripts/curate.py`; relative links to sibling skills
are rewritten to names (`_rewrite_links`), which is the only adaptation.

| Group | Capabilities | Applies to |
|---|---|---|
| Rule packs `ecc.rules.<x>` (21) | golang, typescript, python (+fastapi), java, kotlin, rust, csharp, php, ruby, swift, dart, react, vue, nuxt, angular, react-native (+a11y, performance, production-readiness), web (+design-quality, performance); tag-only: cpp, fsharp, perl, arkts | detected language / framework; every file has `paths:` so **0 always-loaded context**; `hooks.md` excluded everywhere |
| JVM (15) | java-coding-standards, springboot-{patterns,tdd,security,verification}, jpa-patterns (gated on `jpa`, not `spring`, since 1.1.0), quarkus-security, kotlin-{patterns,testing,coroutines-flows}, kotlin-ktor-patterns, kotlin-exposed-patterns; tag-only: hexagonal-architecture, android-clean-architecture, compose-multiplatform-patterns | `java` / `spring` / `jpa` / `quarkus` / `kotlin` / `ktor` / `exposed` |
| Go (2) | golang-patterns, golang-testing | `go` |
| Node / TypeScript (13) | nestjs-patterns, react-{patterns,testing,performance}, frontend-{patterns,a11y}, nextjs-turbopack, vue-patterns, nuxt4-patterns, vite-patterns, prisma-patterns, e2e-testing, react-native-patterns | detected framework (`react`, `nextjs`, `vue`, `nuxt`, `nestjs`, `vite`, `prisma`, `test:playwright`, `react-native`) |
| Python (8) | python-{patterns,testing}, fastapi-patterns, django-{patterns,tdd,security,verification}, django-celery | `python` / `fastapi` / `django` / `celery` |
| Rust, .NET, PHP, Ruby (10) | rust-{patterns,testing}, dotnet-patterns, csharp-testing, laravel-{patterns,tdd,security,verification}, rails-patterns; tag-only fsharp-testing | `rust` / `csharp` / `laravel` / `rails` |
| Swift, Dart, C++, Perl (11) | swiftui-patterns, swift-concurrency-6-2, swift-protocol-di-testing, swift-actor-persistence, dart-flutter-patterns, flutter-dart-code-review; tag-only cpp-{coding-standards,testing}, perl-{patterns,security,testing} | `swift` / `dart`; tags |
| Data and infrastructure (9) | redis-patterns, postgres-patterns, mysql-patterns, database-migrations, deployment-patterns, kubernetes-patterns (gated on `kubernetes` since 1.1.0); tag-only api-design, backend-patterns, accessibility | integration markers the scanner records (`redis`, `kafka`, `rabbitmq`, `postgres`, `mysql`, `mongodb`, `elasticsearch`, `jpa`, `prisma`, `vite`, `celery`, `ktor`, `exposed`, `docker`, `kubernetes`); workspace stack skills `forge.skill.{mongodb,elasticsearch,vertx}-patterns` key on `mongodb` / `elasticsearch` / `vertx` |

Framework-specific counterparts **conflict** with the generic skill they replace and score one
point higher, so a Spring project gets `springboot-tdd` / `springboot-security` /
`springboot-verification` and not `ecc.tdd-workflow` / `ecc.security-review` /
`ecc.verification-loop` (same for Django, Laravel, Quarkus security, Java coding standards).
No upstream has Kafka content yet; `kafka` is detected and recorded for when one does.
`ecc.rules.common` is now `frozen` in `curate.py`: its 1.1.0 hand adaptation is never
overwritten by a re-run.

### Workspace-authored (0.4.0)

| Capability | Decision | Why |
|---|---|---|
| `forge.agent.backend-reviewer` | subagent (Claude Code), `project_types` backend / fullstack / service, read-only (Read, Grep, Glob) | six fixed dimensions: security, money and transactions (idempotency, atomicity, ledger), data integrity and concurrency, readiness for traffic (N+1, caching, timeouts, backpressure), API contract, clarity; evidence-backed findings with severity and "not checked" |
| `forge.agent.frontend-reviewer` | subagent (Claude Code), `project_types` frontend / fullstack / mobile-or-desktop, read-only | seven dimensions: backend contract, how the view loads its data (request map), state and races, client security, performance, resilience and a11y, clarity; declares existing reviewer agents as equivalents so the skill's review-coverage step judges before adding |
| `forge.skill.view-data-loading` | skill, both platforms, `project_types` frontend / fullstack / mobile-or-desktop | request discipline for a screen: request map (first paint vs enhancement vs on interaction), one request per resource, parallel independent calls, nothing secondary blocking the first render, fetch on need, dedupe / cache / cancel; written from a recurring client-project finding |

### Ponytail (2026-10-24)

Scout report on dietrichgebert/ponytail (MIT, v5.3.2): the three skills that run nothing and
need no plugin runtime, verbatim. Hooks, band, gain and help are in `rejections/`.

| Capability | From | Decision | Why |
|---|---|---|---|
| `ponytail.lazy-senior-dev` | ponytail `skills/ponytail` (v5.3.2) | verbatim, both, tags `yagni` / `lazy` / `simplicity`; not always-on | reuse-first ladder after reading the code the change touches, test where the logic needs one, `shortcut:` marker, "never cut" list; upstream's paired benchmark (39 tasks x 5 runs) is the evidence, the project's own evaluation decides always-on; overlaps `karpathy.principles` on simplicity only |
| `ponytail.shortcut-debt` | ponytail `skills/ponytail-debt` | verbatim, both, tag `shortcut-debt`; depends on lazy-senior-dev | read-only `git grep` ledger of the `shortcut:` comments the ruleset leaves |
| `ponytail.review` | ponytail `skills/ponytail-review` | verbatim, both, tag `code-review`; equivalent to any generic review skill | fixed order correct / safe / load / tested / fast / lean, callers read not only the diff, four-part findings in plain English |

### Superpowers (2026-10-23)

Scout report on obra/superpowers (MIT, v7.0.1): only the two skills that name no other
skill and run nothing; the rest is under *Watching* or in `rejections/`.

| Capability | From | Decision | Why |
|---|---|---|---|
| `superpowers.verification-before-completion` | superpowers `skills/verification-before-completion` (v7.0.1) | verbatim, both, tag `verification` (always-on only after eval evidence) | claim gate (fresh evidence before "done"); complements `ecc.verification-loop`, whose `verif` equivalence pattern now excludes it |
| `superpowers.receiving-code-review` | superpowers `skills/receiving-code-review` (v7.0.1) | verbatim, both, tag `code-review` | the receiving side of review (verify, push back, YAGNI check); no registry equivalent |

### Initial catalog (34)

| Capability | From | Decision | Why |
|---|---|---|---|
| `ecc.tdd-workflow` | ECC `skills/tdd-workflow/SKILL.md` | verbatim, both platforms, always; since 1.1.0 testing patterns and mocks split into `references/` | pure markdown; optional `.claude/tdd/` mention is harmless |
| `ecc.verification-loop` | ECC `skills/verification-loop/SKILL.md` | verbatim, Claude only, always | wording is Claude-session specific; mentions hooks informationally |
| `ecc.security-review` | ECC `skills/security-review/*` (2 files) | verbatim, both, backend/fullstack/service/infra or `--want security` | no external refs |
| `ecc.coding-standards` | ECC `skills/coding-standards/SKILL.md` | verbatim, both, always; conflicts with `ecc.rules.common` | one mention of "narrower ECC skill"; harmless |
| `ecc.error-handling` | ECC `skills/error-handling/SKILL.md` | verbatim, both, TS/JS/Python/Go only | content covers only those languages |
| `ecc.conventional-commit-review` | ECC `skills/conventional-commit-review/SKILL.md` | verbatim, both, tag `git` | many teams already document commit rules |
| `ecc.architecture-decision-records` | ECC `skills/architecture-decision-records/SKILL.md` | verbatim, both, tag `adr` | not every project keeps ADRs |
| `ecc.agent.planner` | ECC `agents/planner.md` | adapted (attribution footer), Claude only, always | documented frontmatter only (`tools`, `model: opus`) |
| `ecc.agent.code-reviewer` | ECC `agents/code-reviewer.md` | adapted (footer), Claude only, optional (`runs_shell`) | has Bash access ⇒ permission flag |
| `ecc.rules.common` | ECC `rules/common/{coding-style,testing,security,code-review,patterns,development-workflow}.md` | verbatim into `.claude/rules/ecc-common/`, Claude only, always | no frontmatter ⇒ always-on; cheaper than the skill |
| `uiux.guidelines` | UI UX Pro Max `references/{quick-reference,pro-rules}.md` + workspace SKILL.md | adapted, both, frontend/fullstack/mobile | upstream SKILL.md needs `${CLAUDE_PLUGIN_ROOT}` + Python scripts |
| `uiux.full-toolkit` | UI UX Pro Max (whole skill set) | `native_plugin` with `uipro` hints | installer copies 3 MB data + scripts; sub-skills call external APIs |
| `rea.reverse-engineer-anything` | REA `.agents/skills/reverse-engineer-anything` + MCP server | `native_plugin`, tag-only, risk high | skill is inert without the REA runtime; runtime attaches debuggers |
| `forge.skill.agent-forge-upgrade` | workspace | user-invoked skill, both platforms; installed by `agent-forge setup` (the one-line installer, ADR-0004), otherwise opt-in (`--want agent-forge`); also in the repo's `.claude/skills/` | the project's entry point: LLM-side review of the project driving `~/.agent-forge/bin/agent-forge` read-only / dry-run calls; applies only on explicit user yes |
| `forge.skill.agent-forge-scout` | workspace | skill, opt-in (`--want agent-forge`); also in the repo's `.claude/skills/` | reviews a public GitHub repo for Agent Forge: impressive points, curate / engine-upgrade / watch / reject per point, licence check, proposed sources.yaml entry or ADR stub; read-only |
| `forge.managed-notice` | workspace | `section_merge` into `CLAUDE.md` / `AGENTS.md`, always | makes managed skills discoverable; exercises shared-file approval |
| `forge.hook.guard-secrets-python` / `-node` | workspace | hook (class `hook`): PreToolUse script blocks edits to `.env*`, keys, credentials; Python variant for Python projects, Node variant for JS/TS (mutually conflicting) | stdlib / dependency-free, exit 2 blocks the tool call, never reads the file |
| `forge.hook.python-ruff-format` | workspace | hook: PostToolUse `ruff format` on the edited `.py`; no-op without ruff | single file, no network |
| `forge.hook.node-prettier-format` | workspace | hook: PostToolUse runs the project's `node_modules/.bin/prettier` on the edited file; no-op if absent | never uses npx |
| `mcp.context7` | ECC `mcp-configs/mcp-servers.json` (template) | mcp (class `mcp`): `npx -y @upstash/context7-mcp@latest`, always | docs lookup for any project; network, downloads on first use |
| `mcp.playwright` | ECC `mcp-configs/mcp-servers.json` (template) | mcp: `npx -y @playwright/mcp@latest`, frontend/fullstack only | browser automation; `--browser chrome` flag dropped |
| `karpathy.principles` | andrej-karpathy-skills `CLAUDE.md` | adapted, `section_merge` into `CLAUDE.md` / `AGENTS.md`, both, always; conflicts with `karpathy.guidelines` | always-on beats a skill that may not trigger; ~45 lines, wording of the principles unchanged |
| `karpathy.guidelines` | andrej-karpathy-skills `skills/karpathy-guidelines/SKILL.md` | verbatim, both, tag-only (`--want guidelines-skill`) | for projects that keep instruction files minimal; an explicit request outranks the section |
| `forge.hook.guard-dangerous-git` | workspace (idea from mattpocock `misc/git-guardrails-claude-code`) | hook (class `hook`), tag-only (`--want git-guard`) | PreToolUse on Bash: blocks force-push, remote ref deletion, `reset --hard`, `clean -f`, `branch -D`, wholesale `checkout`/`restore`, `stash drop/clear`; plain `git push` passes; stdlib, fails open |
| `forge.hook.guard-secret-literals` | workspace (patterned after a production team's content-level secret scan, ADR-0010 scouting) | hook (class `hook`), tag-only (`--want secrets`) | PreToolUse on Edit/Write/MultiEdit: blocks a credential *value* in the new text (password / API-key assignment with an inline value, AWS key id, PEM block, JWT, connection string with a password, known token prefixes); placeholders and `${VAR}` pass, test / fixture / docs paths skipped; complements the by-name guards; stdlib, fails open |
| `forge.skill.tenant-isolation` | workspace (generalised from a production multi-tenant platform's critical rule, ADR-0010) | skill, all four platforms, `traits: [multi_tenant]` | tenant identity from the authenticated context only, the tenant condition on every query / cache key / message / search / job, per-tenant uniqueness, explicit audited cross-tenant paths, two-tenant tests; proposed only when the scan shows tenant identifiers |
| `forge.skill.money-safety` | workspace (generalised from the same platform's money rule, ADR-0010) | skill, all four platforms, `traits: [money]` | integer minor units, idempotency key before the state change, atomic transaction or saga with compensation, lock before check-then-act, bounded classified retries, immutable audit, outbox + idempotent consumers; proposed only when the scan shows money handling |
| `forge.skill.event-consumer-safety` | workspace (generalised from the same platform's Kafka / RabbitMQ consumer, retry-DLQ and shutdown rules, ADR-0010) | skill, all four platforms, `traits: [event_driven]` | acknowledge after the work's commit, dedup by id, failure classification, bounded retries, owned and monitored DLQ with context headers, ordering per business key, explicit groups, commit-then-close; broker-neutral |
| `forge.skill.event-contract` | workspace (generalised from the same platform's message-integrity, topic governance / lifecycle, durability, delay and dispatch-contract rules, ADR-0010) | skill, all four platforms, `traits: [event_driven]` | transactional outbox, durable producer settings, envelope, business keys, one type per topic with a version, compatible evolution, reuse-before-create and five-phase retirement, producer-built payloads, transport table |
| `forge.skill.pii-protection` | workspace (generalised from the same platform's PII-encryption rule, blind-index, secret-rotation and erasure skills, ADR-0010) | skill, all four platforms, `traits: [pii]` | three tiers recorded with the schema, encryption at rest with key-version prefix, keyed hash + opaque blind index for search, display pattern per field, nothing in clear in logs / events / caches / exports, rotation with re-encryption, erasure that scrubs in place and propagates to every copy |
| `forge.skill.webhook-signature-verification` | workspace (generalised from the same platform's critical webhook rule, ADR-0010 scouting) | skill, all four platforms, tag-only (`--want webhook`; the entry skill proposes it when it finds inbound callback endpoints) | verify over raw bytes before parsing, constant-time compare per language, one secret per provider with current + previous, timestamp tolerance and event-id dedup, generic 401 with a body-free log, verification at the edge, compensating controls for unsigned providers |
| `forge.hook.changelog-gate` | workspace (patterned after the same team's commit gate) | hook (class `hook`), tag-only (`--want changelog`) | PreToolUse on Bash: a `git commit` with a feat / fix subject and no CHANGELOG.md staged is blocked; `[skip-changelog]` bypasses; honours `git -C`; reads `git diff --cached` only; stdlib, fails open |
| `mattpocock.diagnosing-bugs` | mattpocock `skills/engineering/diagnosing-bugs` (+ `scripts/hitl-loop.template.sh`) | verbatim, both, always | red-capable feedback loop before any hypothesis; no registry equivalent |
| `mattpocock.grilling` | mattpocock `skills/productivity/grilling` | verbatim, both, tag `grilling` | frontier-of-the-design-tree interview with recommended answers |
| `mattpocock.domain-modeling` | mattpocock `skills/engineering/domain-modeling` (+ ADR/GLOSSARY formats) | verbatim, both, tag `domain-modeling` | lazy GLOSSARY.md and the three-criteria ADR test; overlaps `ecc.architecture-decision-records` only on format |
| `mattpocock.codebase-design` | mattpocock `skills/engineering/codebase-design` (+ DEEPENING, DESIGN-IT-TWICE) | verbatim, both, tag `codebase-design` | deep-module vocabulary; dependency of `mattpocock.tdd` |
| `mattpocock.grill-with-docs` | mattpocock `skills/engineering/grill-with-docs` | verbatim, both, tag `grill-with-docs`; depends on grilling + domain-modeling | user-invoked (no always-loaded context); its Skill-tool calls are checked by `validate` |
| `mattpocock.writing-for-agents` | mattpocock `skills/productivity/writing-for-agents` (+ SKILL-MECHANICS) | verbatim, both, tag `agent-docs` | context pointers, the two loads, completion criteria; also the yardstick for curated descriptions |
| `mattpocock.two-axis-review` | mattpocock `skills/engineering/code-review` | adapted: renamed (harness built-in `code-review` collision), setup-skill precondition replaced by the project's tracker docs; tag `code-review` | Standards and Spec reviewed by separate sub-agents, never merged |
| `mattpocock.tdd` | mattpocock `skills/engineering/tdd` (+ tests, mocking) | adapted (one pointer renamed), both, tag `tdd-seams`; conflicts with `ecc.tdd-workflow`; depends on codebase-design | compact alternative; explicit request wins |

## Excluded on purpose

One record per item, with the reason and what would have to change, lives in
[`rejections/`](rejections/README.md). Check it before proposing a source or capability.

## Watching

| Item | Why not yet |
|---|---|
| mattpocock `skills/engineering/pr` | reproduced almost word for word from humanlayer `show-me` (`pr/CREDITS.md`); that upstream licence is not verified yet |
| mattpocock `skills/engineering/improve-codebase-architecture` | user-invoked and useful, but its HTML report template loads Tailwind and Mermaid from CDNs; curate once the report is optional or offline |
| mattpocock `skills/engineering/retro` | depends only on `writing-for-agents`; reads session logs on the machine; wait for an observed need |
| superpowers `skills/systematic-debugging` (+ root-cause-tracing, defense-in-depth, condition-based-waiting) | overlaps `mattpocock.diagnosing-bugs`; names `superpowers:` skills (validate rejects); curate adapted and tag-only if a project asks for it |
| ponytail `skills/ponytail-audit` | the review checklist applied to a whole repo; curate when a project asks for a repo audit |
| ponytail `hooks/ponytail-map.js` | 2,000-character codebase map at session start (reuse-first costs no search); a hook, so revisit as a workspace-authored stdlib hook once `context_load` counts hook-injected context |
| ponytail `benchmarks/agentic/` | the design reference for the deferred evaluation engine (ADR-0002): paired arms in one run, deterministic checks with good / bad references self-tested before any API spend, LLM judges gated by a self-test and never a curation gate, geometric mean of per-task medians with a bootstrap interval |
| superpowers `writing-plans` / `executing-plans` / `subagent-driven-development` / `using-git-worktrees` / `finishing-a-development-branch` | one chain of 6+ skills with scripts that write `.superpowers/` into the working tree; revisit as a single capability if a chain with scripts is ever allowed |

## Re-curation workflow

Skills at or above 20,000 bytes are split, not trimmed (ADR-0012): add `Split` entries to
`ECC_SPLITS` in `scripts/curate.py` (heading, reference file, when to read it). Today:
`ecc.cpp-coding-standards`, `ecc.django-patterns`, `ecc.django-tdd`,
`ecc.flutter-dart-code-review`, `ecc.kotlin-exposed-patterns`, `ecc.kotlin-testing`,
`ecc.kubernetes-patterns`, `ecc.laravel-security`, `ecc.tdd-workflow` (all 1.1.0, adapted).

```bash
agent-forge sources sync --update        # moves checkouts to upstream HEAD
python scripts/curate.py --allow-revision-drift
git diff registry/                       # review every changed asset
# bump `version` and `source.revision` in affected capability.yaml files
agent-forge validate
```

Nothing in a target project changes until a user runs `upgrade` → `approve` → `apply`.
