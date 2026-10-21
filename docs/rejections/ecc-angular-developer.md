# ECC `skills/angular-developer`

Source: `ecc` — `skills/angular-developer/`.

## Decision

Rejected (0.4.0 stack curation); `ecc.rules.angular` (path-scoped rules) is curated instead.

## Why

131,000 characters across many reference files, far above the 500-line SKILL.md guideline
and the largest item upstream by a factor of four. Loaded on demand it would still dominate
a session's context the moment it triggers, and most of its content is code generation
templates that a project's own conventions replace. The rule pack gives Angular projects the
style / patterns / security / testing guidance at zero always-loaded cost.

## Revisit when

Upstream splits it into focused skills (routing, signals, testing) of a reviewable size.
