# Upgrade lifecycle

```
SCAN ──► ASSIGN / UPGRADE ──► DIFF ──► APPROVE ──► APPLY ──► VALIDATE ──► (ROLLBACK)
 read     plan (draft)         read     binds       writes      read         writes
 only     read only            only     digest      target                   target
```

## Plan states

| State | Set by | Meaning |
|---|---|---|
| `draft` | assign/upgrade | reviewable, not approved |
| `approved` | approve | digest recorded; shared-file ops listed in `approval.extra_approvals` |
| `stale` | approve (re-check) | target files or registry changed; create a new plan |
| `applied` | apply | transaction id recorded; a plan is applied at most once |
| `failed` | apply | partial/failed transaction; see `rollback` |
| `revoked` | approve --revoke | approval withdrawn |

## What makes a plan stale

- any destination's current hash ≠ `before_sha256` (user or another tool changed it)
- registry digest ≠ `plan.registry_digest` (curated content changed)
- plan file edited after approval (content digest ≠ approval digest)

## What `upgrade` does and does not do

Does: compare each record in `.agent-forge/managed.json` with the registry; for a newer
version with **no local drift**, emit replace/create/remove operations and section updates.
Does not: touch capabilities with local drift (listed under *decisions needed*), deprecated or
removed capabilities (noted), or anything whose new version has unmet dependencies or new
conflicts (rejected with reason).

## Transaction record

`state/transactions/<tx>/transaction.json` (sealed with a hash) plus `backup/` holding the
pre-apply bytes of every modified or removed file. Rollback produces a second record
(`rb-…`) that references the original.

## Managed manifest in the target

`.agent-forge/managed.json` lists, per capability: version, transaction id, install time,
file hashes, managed sections. `scan` validates it and computes drift; it is never trusted
for paths outside the target. Commit it if you want other machines to know what is managed.
