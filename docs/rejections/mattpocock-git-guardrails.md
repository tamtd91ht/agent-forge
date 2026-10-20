# mattpocock/skills git-guardrails-claude-code

Source: `mattpocock` — `misc/git-guardrails-claude-code`.

## Decision

Not curated as upstream content. Re-implemented as `forge.hook.guard-dangerous-git`.

## Why

The bash script needs `jq`, the skill offers to install into `~/.claude/settings.json`, and it
blocks every `git push`. The idea is sound, so the behaviour was rewritten as a stdlib Python
hook that blocks only destructive forms.
