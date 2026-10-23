---
name: mongodb-patterns
description: Design and review MongoDB collections, queries and writes in any driver - shape documents around the queries that read them, give every production query an index it uses (equality, sort, range order; tenant field first), paginate on an indexed key instead of skip, choose write and read concerns per operation, use multi-document transactions only across documents that must change together, keep arrays and documents bounded, size the connection pool for the process, and treat change streams as a resumable log. Use when adding or changing a collection, a query, an aggregation, an index, a transaction or a driver configuration.
---

# MongoDB patterns (documents shaped by their queries, every query indexed)

MongoDB fails quietly: a query without a usable index works on a developer's laptop and
scans the collection in production; an unbounded array grows until one document hits the
16 MB limit; a write with the default concern is acknowledged by a primary that then steps
down. This is the checklist for writing and reviewing anything that touches a collection,
whatever the driver (Java, Spring Data, Node, Mongoose, PyMongo, Motor, Go).

## 1. Shape documents around the reads, then bound them

- Start from the queries the feature needs, not from the entity diagram. Data read together
  is stored together (embedding); data that grows without limit or is shared by many parents
  is referenced.
- Every array has a bound stated in the schema comment or validator (members of a small
  team: embed; events of an account: separate collection). An array that is appended by
  normal operation of the product is a separate collection.
- A document has one shape per collection; variants are a discriminator field, not a
  different set of keys. Turn on JSON-schema validation (`validator`, `validationLevel:
  strict` for new collections, `moderate` when migrating) so the shape is enforced by the
  server, not by the last writer.
- Keep `_id` as the natural key when one exists and is immutable (an external id, a
  `{tenant, slug}` composite); otherwise ObjectId. Never a client-generated value that can
  collide across tenants.
- Field names are short but readable; no field holds a different type in different documents.

## 2. Every production query has an index it actually uses

- Before a query ships, run it with `explain("executionStats")` against a realistic
  collection and read `totalDocsExamined` against `nReturned`. A ratio above a handful is a
  missing or wrong index; `COLLSCAN` on anything but a tiny collection is a defect.
- Compound index key order follows **Equality, Sort, Range**: fields matched by equality
  first, then the sort field so the sort uses the index, then range predicates. One index per
  query shape; a query that filters on `{status, createdAt}` and sorts by `createdAt` wants
  `{status: 1, createdAt: -1}`, not two single-field indexes.
- In a multi-tenant collection the tenant field is the **first** key of every index and the
  first predicate of every query; an index that does not start with it serves no tenant
  query (see the tenant-isolation skill).
- Covered queries (projection of indexed fields only) when the read is hot; `hint()` only
  with a comment explaining why the planner chose wrongly.
- Indexes are created by a migration or startup step that is idempotent and builds online,
  never by hand on production; dropping one is a reviewed change because a query somewhere
  depends on it.
- Watch the write amplification: every index costs each insert and update. Remove indexes no
  query uses (`$indexStats`).

## 3. Pagination on an indexed key, never deep `skip`

- `skip(n)` reads and discards `n` documents; it is fine for page 2 and a timeout for page
  2000. Paginate by **range on an indexed, unique-enough key**: `{_id: {$gt: lastId}}` or
  `{createdAt: {$lt: last}, _id: {$lt: lastId}}` with a matching compound index and a sort
  on the same keys.
- The cursor the API hands out is opaque (encoded last-key tuple), never a page number that
  invites `skip`.
- `limit()` is always present and capped server-side; an unbounded `find()` in request
  handling is a defect.
- Counting for a UI uses `estimatedDocumentCount()` or a cached counter; `countDocuments()`
  with a filter on a large collection is a scan unless the filter is covered.

## 4. Writes: concern per operation, idempotent on retry

- `writeConcern: majority` for anything the user would miss (an order, a payment, a
  consent); `w: 1` only for telemetry-like data where loss is acceptable and documented.
  Keep `retryWrites` on and keep each write idempotent anyway: upsert with a deterministic
  filter, `$setOnInsert` for create-once fields, `$inc` guarded by an idempotency record
  rather than read-modify-write.
- Read-modify-write on one document is `findOneAndUpdate` with a filter on the expected
  state (`{_id, version: n}` then `$inc: {version: 1}`); a lost update between `find` and
  `save` is the classic ODM bug.
- `$set` named fields; never replace a whole document from an object built in the request
  unless the handler owns every field.
- Bulk work uses `bulkWrite` in bounded batches (a few hundred to a few thousand ops) with
  `ordered: false` when order does not matter; errors are read per operation.
- Deletes of user data are soft (a `deletedAt`) when anything references them, and hard
  deletes are a job with a bound per run.

## 5. Transactions only across documents that must change together

- A multi-document transaction is for invariants that span documents (debit one wallet,
  credit another; reserve stock and create the order). It is not a substitute for a
  well-shaped document: if two documents are always written together, consider one document.
- Keep a transaction short (one round of reads, one of writes, no network calls inside),
  retry it on `TransientTransactionError` and `UnknownTransactionCommitResult` with the
  driver's callback API (`withTransaction`), and set `maxCommitTimeMS`.
- A transaction holds locks and a snapshot: no user-facing wait inside it, no loop over an
  unbounded cursor inside it; keep the number of documents it touches small and bounded.
- Read concern `snapshot` inside a transaction; outside, `majority` when a read must not see
  a write that may roll back (a confirmation page), `local` for dashboards.

## 6. Reads: preference and staleness are explicit

- `readPreference: primary` is the default and right for anything read after a write by
  the same user. Secondary reads (`secondaryPreferred`) are for reports and search indexing
  and are labelled stale in the code (`maxStalenessSeconds`).
- Aggregations: `$match` first and on indexed fields, `$project` early to drop large fields,
  `$lookup` only on a small, indexed foreign side (it is a nested loop; a join of two large
  collections belongs in a batch job or a denormalised field), `allowDiskUse` only in
  batch jobs. A pipeline that cannot use an index for its first `$match` is reviewed as a
  collection scan.
- Text search for anything beyond a prefix on one field belongs in a search engine, not a
  `$regex` without an anchor.

## 7. Connections, timeouts and shutdown

- One client per process, created at startup, closed at shutdown; never a client per
  request. Pool size (`maxPoolSize`) is sized to the process's concurrency and the cluster's
  connection budget (`connections.current` on the server is the number to watch), with
  `maxIdleTimeMS` so bursts shrink back.
- Every operation has a bound: `serverSelectionTimeoutMS`, `connectTimeoutMS`,
  `socketTimeoutMS`, and `maxTimeMS` on queries that serve a request. A query that may run
  longer than the HTTP timeout is a job.
- Graceful shutdown drains in-flight operations before `close()`; change-stream consumers
  persist their resume token before exiting.
- Credentials come from the environment; the URI never appears in logs.

## 8. Change streams and schema migration

- A change stream is a resumable log: store the `resumeToken` after each processed event,
  resume with `startAfter`, and expect replays (the handler is idempotent, see the
  event-consumer-safety skill). Filter with a pipeline on the server, not in the client.
- Schema changes are additive and versioned (`schemaVersion` field): new code reads both
  shapes, a background job rewrites old documents in bounded batches, old code is removed
  after the job finishes. Never a migration that rewrites a large collection in one pass.
- Validators are tightened after the data complies, not before.

## Review checklist

- [ ] Each new query: explain plan read, index named, no `COLLSCAN`, tenant field first.
- [ ] Each new list endpoint: range pagination on an indexed key, server-side cap on `limit`.
- [ ] Each write: concern chosen on purpose, idempotent on retry, no read-modify-write race.
- [ ] Each transaction: spans documents that must change together, short, retried with
      `withTransaction`, no network call inside.
- [ ] Documents and arrays bounded; validator present; `schemaVersion` on evolving shapes.
- [ ] One client per process; every operation bounded by a timeout; shutdown closes cleanly.
