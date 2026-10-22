---
name: pii-protection
description: Handle personal data (phone, email, national id, date of birth, bank or card numbers, names, addresses) so it is never stored, indexed, logged or published in clear - classify fields into tiers, encrypt at rest with a key-version prefix, keep a keyed hash for exact lookups and an opaque blind index for partial search, decide per field whether it is shown masked, in full with an audit entry or never, rotate keys with a re-encryption job, and erase on request by scrubbing in place across store, index, cache, logs and events within the legal deadline. Use when adding a field that holds personal data, when such data reaches a search index, log, event or export, or when implementing a deletion or right-to-erasure request.
---

# PII protection (classify, encrypt, search safely, show carefully, erase completely)

Personal data leaks through the places nobody designed: a search index that mirrors the
database, a log line with the request body, an event payload copied by three consumers, a
cache that outlives the record. This skill is the checklist for every field that identifies a
person, from the moment it is added until the day it must be erased. It is stack-neutral;
the regulator (GDPR, PDPA, CCPA, …) sets the deadlines, the engineering is the same.

## 1. Classify every field once, in writing

| Tier | Examples | At rest | In a search index | In logs, events, exports |
|---|---|---|---|---|
| 1 critical | phone, email, national id, date of birth, bank account, card number, passport | encrypted + keyed hash | hash or blind index only, never the value | never in clear; masked or omitted |
| 2 sensitive | full name, address, photo, location | encrypted | name may be indexed as an accepted, written-down risk; address never | masked |
| 3 business | company, tags, status, codes | database-level encryption | as is | as is |

The tier is recorded next to the schema (entity doc, migration comment, model annotation),
so a reviewer can check a new field against it. A field without a tier does not ship.

## 2. Encrypt at rest, with a version in front

- Authenticated encryption (AES-256-GCM or the platform's equivalent), a fresh random
  nonce / IV per value, never reused with the same key.
- Stored value = `{keyVersion}:{encoded(nonce + ciphertext + tag)}`. The version prefix is
  what makes rotation (§6) possible; a value without it blocks rotation forever.
- Keys come from the environment or a secret store, never from source, config files or the
  database; a dev-only key may live in one shared dev fragment and nowhere else.
- Encryption and decryption happen in **one layer** (the persistence mapper or a field
  codec), never scattered through domain or handler code; the domain model holds the plain
  value object and does not know the cipher.

## 3. Searching without exposing

- **Exact match** (login by email, lookup by phone): store a keyed hash (HMAC with a
  server-side salt) next to the ciphertext; index the hash, unique per owner / tenant.
- **Partial match** (type-ahead on phone or email): a **blind index**, a list of HMAC-ed
  n-grams, stored under an opaque field name that does not announce its purpose
  (`lookupRefs`, not `phoneSearchTokens`), with index names equally opaque. For values with
  few symbols (phone digits) add random-position longer n-grams so the stable 3-gram set
  cannot be brute-forced by frequency; draw positions from a cryptographic random source.
- Never expose the hash, the blind index or its length through an API, a DTO or a log.
- A search index (Elasticsearch, OpenSearch, …) receives only what §1 allows for the tier;
  the projection is a deliberate subset of the record, not a copy.

## 4. Showing: decide per field, enforce at the edge

| The client needs to | Pattern | Stored | Returned |
|---|---|---|---|
| never see it again (secrets, tokens) | **has-flag** | ciphertext | `hasX: true/false` |
| see it masked by default (phone, id, card) | **pre-computed mask** | ciphertext + hash + mask computed at write time | the mask; the full value only to a permission-checked caller, with an audit entry **before** decryption |
| always see it (email, name) | **decrypt on read** | ciphertext + hash | plain value |

The pattern is chosen when the field is added and written down with the tier. Masking is
computed once at write time, not improvised per endpoint.

## 5. Where it must never appear

- Logs: no request / response bodies with tier-1 or tier-2 fields; log identifiers and
  masks. Structured logging with an allow-list beats a regex scrubber bolted on later.
- Events and messages: identifiers and masked values; a consumer that needs the clear value
  reads it from the store under its own authorisation.
- Caches: a decrypted value in a cache has a short TTL (minutes), and the cache is
  authenticated and encrypted in transit.
- Exports, reports, analytics copies, test fixtures taken from production: masked or
  synthetic, never raw.

## 6. Rotation

- Encrypt with the newest key, decrypt with every non-expired key (the version prefix picks
  it); an idempotent background job re-encrypts old values in batches.
- Keyed hashes and blind indexes rotate with the same job (a new salt changes every hash).
- Rotation has a written runbook and a schedule with an alert when it is overdue; one
  logical key is one shared secret across services, rotated once.

## 7. Erasure (right to be forgotten)

1. Record the request (who, which subject, when, deadline) before doing anything.
2. **Scrub in place**: null or replace tier-1 / tier-2 fields, keep the record shell and its
   identifiers so references, aggregates and audit history stay consistent; set an
   `erasedAt`.
3. Propagate: the search index is updated in place (not deleted, so the record still
   resolves but reveals nothing), caches invalidated, long-term logs and history partitions
   scrubbed, downstream consumers notified by an erasure event that carries identifiers only.
4. Copies elsewhere (other regions, other instances, backups within policy, third parties
   you sent data to) are part of the request: send them the command, wait for
   acknowledgement, escalate before the legal deadline if any is missing.
5. Write an immutable erasure audit entry: request id, subject, systems confirmed, timestamp.
   The audit entry itself holds no personal data.

A record type that holds personal data without an implemented erasure path does not ship.

## 8. Review checklist

- [ ] Every new field has a tier and a display pattern, recorded next to the schema.
- [ ] Tier 1 / 2 encrypted at rest with a key-version prefix; keys from a secret store.
- [ ] Exact lookups by keyed hash; partial search by an opaque blind index; nothing exposed.
- [ ] Search-index projection is an allow-list; logs, events, caches and exports follow §5.
- [ ] Decrypt-in-full paths check a permission and write an audit entry first.
- [ ] Rotation runbook, previous-key decryption and a re-encryption job exist.
- [ ] Erasure scrubs in place, propagates to every copy, waits for acknowledgements, audits.
- [ ] Tests: a tier-1 field never appears in clear in the index, a log line, an event or an
      export; a masked field returns the mask without the permission; erasure leaves the
      record shell and empties every copy.
