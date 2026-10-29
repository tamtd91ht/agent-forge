# anthropics/knowledge-work-plugins: role plugins, connectors and the rest of the catalogue

Source: `kwp` (revision `33d3dea41a34`, 2026-10-21) — every plugin directory except the two
curated skills (`engineering/skills/incident-response`, `data/skills/sql-queries`), plus
`.claude-plugin/marketplace.json`, each plugin's `.mcp.json` and `CONNECTORS.md`.

## Decision

Not curated.

## Why

- **Role plugins** (`sales`, `legal`, `finance`, `marketing`, `human-resources`,
  `customer-support`, `product-management`, `operations`, `enterprise-search`, `productivity`,
  `small-business`, `bio-research`, `pdf-viewer`): content for a person's job, not for the
  agent infrastructure of a code project, which is what Agent Forge scans and installs into.
  `bio-research` also ships Python scripts.
- **Other engineering skills:** `code-review`, `architecture` and `deploy-checklist` duplicate
  stronger registry entries (`ponytail.review`, `mattpocock.two-axis-review`,
  `ecc.architecture-decision-records`, `ecc.deployment-patterns`). `testing-strategy`,
  `system-design`, `tech-debt` and `documentation` are 1.3-1.5 KB templates; `debug` is a
  four-step box plus a report template (`mattpocock.diagnosing-bugs` covers it); `standup`
  needs chat and tracker connectors.
- **Other data skills:** `build-dashboard` (27 KB, above the ADR-0012 size limit),
  `create-viz` / `data-visualization` (Python plotting for analysis notebooks),
  `data-context-extractor` (see *Watching* in `source-curation.md`).
- **`.mcp.json` connectors:** remote http MCP servers, several with OAuth client ids, chosen
  per role rather than per project; and the marketplace install path (`claude plugin
  install`) writes user-level plugin configuration, which Agent Forge never does (ADR-0001).
- **`cowork-plugin-management`:** needs the Cowork desktop mounts (`mnt/.local-plugins`).
- **`partner-built/*`:** vendor plugins around each vendor's own MCP server; mixed MIT and
  Apache-2.0 per directory.

## Revisit when

A project-scoped way to choose MCP connectors per detected tool exists (the `~~category`
idea), or a target project type outside code (analytics or dbt repositories) is added to the
scanner, which would make `analyze` / `explore-data` / `validate-data` candidates.
