# Policy

Policy decides what may ever be planned. It is deterministic YAML, never an LLM, and it can
only make things stricter as layers are added.

## Layers and precedence

```text
registry/policies/default.yaml        shipped baseline        (inside the registry digest)
<workspace>/policy.yaml               organisation baseline   (optional, trusted)
<project>/.agent-forge/policy.yaml    repository policy       (optional, untrusted input)
--want / --request / --exclude        user intent             (cannot lift a deny)
```

Every capability gets one verdict per platform: `allow`, `require_request` or `deny`.
Layers are combined **strictest wins**, so the order above is also the order of authority: a
lower layer cannot weaken a higher one, and an explicit `--request` only satisfies
`require_request`, never `deny`. Approval classes (`--shared-files`, `--hooks`, `--mcp`) are
enforced by `approve`/`apply` on top of any verdict; a policy can switch a whole class off
but never grant one.

Non-overridable constraints are the ones in code, not policy: paths inside the project and
the adapter's managed roots, no writes through links, approval bound to the plan digest,
only `curated` capabilities whose pinned digest still matches.

## Rules

| Key | Effect |
|---|---|
| `max_risk` | capabilities above it are denied |
| `require_request_from_risk` | at/above it a capability needs `--request` / `--want` |
| `capabilities.deny` / `require_request` / `allow_only` | capability id globs (`rea.*`) |
| `capabilities.deny_tags` | deny anything carrying the tag |
| `grants.process_execute` / `network_access` / `secrets_read` | verdict for capabilities with that grant |
| `classes.shared_file` / `hook` / `mcp` | `deny` switches the approval class off entirely |
| `platforms` | non-empty: other platforms are denied |
| `require_signoff` | deny entries without a human `review.signed_off_by` |
| `max_context_chars` | above this always-loaded context, a capability needs a request (ADR-0003) |
| `max_total_context_chars` | budget for a whole plan's always-loaded context; exceeding it adds a note and a decision line for the approver (not blocking) |

Unknown keys are rejected. An **invalid project policy fails closed**: planning stops with a
clear error instead of silently ignoring the file, because ignoring it would drop exactly
the restrictions it was written to add. Fix or delete the file to continue.

## Plans bind to the policy

Every `assign`/`upgrade` plan records the digest of the effective layers. `approve` and
`apply` refuse a plan whose policy changed since it was built (stale): tightening a project
policy after approval stops the pending apply.

## Examples

Organisation baseline (`<workspace>/policy.yaml`):

```yaml
version: 1
name: acme-baseline
require_signoff: true
classes: { mcp: deny }
grants: { network_access: deny }
max_context_chars: 4000
```

Repository policy (`<project>/.agent-forge/policy.yaml`):

```yaml
version: 1
capabilities:
  deny: ["rea.*", "uiux.*"]
  require_request: ["ecc.agent.*"]
```

Inspect the result: `agent-forge policy <project>` shows the layers and each verdict with
the layer that produced it.
