# Your own registry in 10 minutes

A registry is a directory (usually a git repository) with the same layout as this
repository's `registry/`. Agent Forge layers any number of them over the core catalog
(`registries:` in `agent-forge.yaml`, first wins on a duplicate id, shadowing is reported).
This is how a team keeps private rules and hooks, and how the public catalog can later move
to its own repository with the core registry as just the default source.

## 1. Create the layout

```bash
mkdir -p agent-forge-team-registry/capabilities
cd agent-forge-team-registry && git init
```

```
agent-forge-team-registry/
  README.md
  capabilities/
    team.rules.api-conventions/
      capability.yaml
      assets/claude_code/api-conventions/conventions.md
```

## 2. Write one capability

```yaml
# capabilities/team.rules.api-conventions/capability.yaml
schema_version: "1"
id: team.rules.api-conventions
name: API conventions
description: How this team names endpoints, versions APIs and writes error bodies.
version: 1.0.0
kind: rule
category: team.conventions
purpose: Keep every service's API consistent without repeating the review comments.
status: curated
provenance: workspace
source: { source_id: workspace }
license: { spdx: MIT, attribution: "Example team", redistribution_ok: true }
review:
  reviewed_at: "2026-10-20"
  reviewer: tech-lead
  rationale: Internal content, reviewed by the platform team.
  signed_off_by: tech-lead
  signed_off_at: "2026-10-20"
applicability: { project_types: [backend] }
platforms: [claude_code, cursor, copilot]
install_strategy: file_copy
destinations:
  - { platform: claude_code, source: claude_code/api-conventions/conventions.md, dest: .claude/rules/api-conventions.md }
  - { platform: cursor, source: claude_code/api-conventions/conventions.md, dest: .cursor/rules/api-conventions.mdc }
  - { platform: copilot, source: claude_code/api-conventions/conventions.md, dest: .github/instructions/api-conventions.instructions.md }
risk: low
benefit_score: 6
maintenance_cost: 2
```

The content is one markdown file in the canonical (Claude Code) format; Cursor and Copilot
get it rendered by the adapters ([ADR-0006](adr/0006-canonical-format-and-adapters.md)).

## 3. Pin and validate

```bash
python /path/to/agent-forge/scripts/pin_integrity.py --registry .
agent-forge validate      # with the registry configured below
```

## 4. Point the workspace at it

```yaml
# ~/.agent-forge/agent-forge.yaml
registries:
  - { name: team, path: /path/to/agent-forge-team-registry }
```

`agent-forge doctor` lists the layers and any shadowed id; `catalog show <id>` names the
registry an entry came from; plans bind to the digest of the merged registries, so a change
in either layer invalidates pending approvals as usual.

## 5. Share it

Commit the registry, have every developer clone it to the same path (or set the path per
machine), and add `git pull` of the registry to the same step as updating Agent Forge. A
registry served over HTTP with an index and digests is the next step on the plan; today a
git checkout is the distribution.

## Rules that still apply

Everything the core enforces applies to every layer: strict manifests, integrity pins,
content-safety scan, licence notice, approval classes, policy. A team registry cannot grant
anything the policy denies; it can only add content.
