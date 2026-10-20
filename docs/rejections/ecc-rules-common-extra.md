# ECC common rules: agents, hooks, git-workflow, performance

Source: `ecc` — `rules/common/{agents,hooks,git-workflow,performance}.md`.

## Decision

Not curated; the other six common rules are (`ecc.rules.common`).

## Why

They describe ECC's own agents and hooks, reference `~/.claude/settings.json` and ECC CLI
flags. Installed without ECC they instruct the agent to use things that do not exist.

## Revisit when

ECC rewrites them to be harness-neutral.
