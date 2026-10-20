# ECC MCP configs as shipped

Source: `ecc` — `mcp-configs/`, `.mcp.json`.

## Decision

Not copied as files. Two servers are offered as templates instead (`mcp.context7`,
`mcp.playwright`), behind the `mcp` approval class.

## Why

The files launch processes (`npx -y …`) for every server at once; each server has to be
reviewed and approved on its own.
