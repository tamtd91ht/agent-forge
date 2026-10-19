## Coding behavior principles

Behavioral guidelines to reduce common LLM coding mistakes. Project-specific instructions in
this file take precedence. **Tradeoff:** these bias toward caution over speed; for trivial
tasks, use judgment.

### 1. Think before coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity first

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked; no abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

### 3. Surgical changes

**Touch only what you must. Clean up only your own mess.**

- Don't "improve" adjacent code, comments, or formatting; don't refactor what isn't broken.
- Match existing style, even if you'd do it differently.
- Remove imports/variables/functions that YOUR changes made unused; mention pre-existing
  dead code instead of deleting it.
- The test: every changed line should trace directly to the request.

### 4. Goal-driven execution

**Define success criteria. Loop until verified.**

- "Add validation" → write tests for invalid inputs, then make them pass.
- "Fix the bug" → write a test that reproduces it, then make it pass.
- "Refactor X" → ensure tests pass before and after.
- For multi-step tasks, state a brief plan: `1. [step] → verify: [check]`.

Adapted from andrej-karpathy-skills (https://github.com/multica-ai/andrej-karpathy-skills),
MIT License, Copyright (c) forrestchang. Installed by Agent Forge.
