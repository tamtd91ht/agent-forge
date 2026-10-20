# Security policy

## Reporting a vulnerability

Please report privately through GitHub: **Security → Report a vulnerability** on
https://github.com/tamtd91ht/agent-forge (private vulnerability reporting). Do not open a
public issue for a vulnerability.

Include: the version or commit, the command you ran, what happened, and the smallest project
or plan that reproduces it. We acknowledge reports on a best-effort basis, aim to confirm
within 7 days, and publish a fix with a GitHub security advisory and a patch release.

## In scope

- Writes outside the target project or its managed roots; writes through links or aliases.
- Applying a plan that was not approved as-is (tampering, stale content, policy bypass).
- Rollback overwriting changes a user made after apply; backup or record tampering.
- A curated capability or the installer executing code, reaching the network, or writing
  user-global configuration in ways its manifest and the docs do not state.
- Secrets read, logged or written into reports.

## Out of scope

- What an installed agent, hook or MCP server does at runtime inside the permissions the
  user granted it: Agent Forge is a capability manager, not a sandbox
  ([docs/security.md](docs/security.md#runtime-boundary)).
- An attacker who can already write the Agent Forge workspace (`~/.agent-forge`): the
  workspace is the trust anchor.
- Upstream repositories under `sources/checkouts/` (report to their maintainers).

## Supported versions

The latest release and `main`. Pin a release with `AGENT_FORGE_REF=<tag>` when installing.

## Triage

Reports are triaged by severity (write outside the project or code execution: critical;
approval/integrity bypass: high; information exposure: medium), fixed with a regression test
in `tests/security/`, and listed in `CHANGELOG.md`.
