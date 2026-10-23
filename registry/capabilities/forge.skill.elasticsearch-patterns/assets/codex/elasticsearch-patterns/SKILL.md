---
name: elasticsearch-patterns
description: Write and review Elasticsearch or OpenSearch code in any client - explicit mappings behind an alias so reindexing is a swap, keyword vs text chosen per field, filter context for anything that does not need scoring, point-in-time with search_after for deep or exported result sets instead of from/size, bounded page sizes and track_total_hits, bulk indexing with backoff on 429 and a refresh policy chosen on purpose, timeouts and a circuit-breaker on the client so an overloaded cluster degrades the feature instead of the service, slowlog and shard sizing checked before go-live, and the primary store kept elsewhere so an index can always be rebuilt. Use when adding or changing an index, a mapping, a query, an aggregation, an indexing pipeline or a search client configuration.
---

# Elasticsearch patterns (an index you can rebuild, a query that cannot take the cluster down)

Elasticsearch is a derived store with sharp edges: a mapping guessed from the first document
cannot be changed without a reindex; `from: 10000` is refused and `from: 9000` is slow on
every shard; a bulk indexer without backoff turns a busy hour into a cascade of 429s; a
search with no timeout holds a thread while the cluster is red. This is the checklist for
writing and reviewing anything that touches an index, whatever the client (Java API client,
Spring Data Elasticsearch, the Node, Python or Go clients, OpenSearch).

## 1. The index is derived; the source of truth lives elsewhere

- The database (or the event log) is the primary store; the index is rebuilt from it. A
  feature that can only be served from the index has no recovery story. Document the
  rebuild command and run it in a test environment regularly.
- Indexing follows the primary write: outbox / change stream / event, never a dual write
  in the request handler that can succeed on one side and fail on the other (see the
  event-contract and event-consumer-safety skills). The indexer is idempotent: it indexes by
  the primary id, so a replay overwrites rather than duplicates.
- A document in the index carries a `version` or `updated_at` from the primary store;
  the indexer uses external versioning (`version_type: external`) or `if_seq_no` so an old
  event cannot overwrite a newer document.

## 2. Mappings are explicit, templates own them, aliases front them

- `dynamic: strict` (or `false` for a known payload field) on every production index; a
  mapping inferred from the first document is a defect waiting for the first string that
  looks like a date.
- `keyword` for identifiers, codes, enums, anything filtered, sorted or aggregated; `text`
  only for fields searched by words, with the analyzer named. A field needed both ways gets
  a `fields.keyword` sub-field, not two documents. `index: false` for fields only returned.
- The mapping lives in an **index template** (component templates for shared parts) in the
  repository, applied by a migration or startup step, versioned with the code. Nobody edits
  a mapping on a live cluster by hand.
- Every index the application reads or writes is reached through an **alias**. A mapping
  change is: create `index-v2` from the template, reindex (bounded `slices`, `requests_per_second`), swap the alias atomically, delete `index-v1` later. Zero downtime, reversible.
- Time-series and log-like data use data streams or dated indices with ILM, not one index
  that grows for ever.

## 3. Query correctness: the right clause in the right context

- `term` on `keyword` fields; `match` on `text` fields. A `term` query against an analysed
  field silently returns nothing for most inputs.
- Everything that does not need a score (tenant, status, date range, ownership) goes in a
  `bool.filter`, which is cached and never scored. In a multi-tenant index the tenant filter
  is present in every query, applied by one shared query builder, and tested for its
  absence (see the tenant-isolation skill).
- `minimum_should_match` is stated whenever a `should` clause is meant to be required with
  a `filter` alongside it; otherwise the `should` is optional and the query returns more than
  intended.
- Aggregations on `keyword` fields only; `size` on `terms` aggregations is bounded and the
  cardinality considered; `composite` for paging through buckets. No `fielddata: true` on
  `text` fields to make an aggregation work.
- Scripts in queries (`script_score`, painless) are reviewed for cost and never built from
  user input by string concatenation.
- The query the application sends is logged once at debug level in its final JSON form, so
  a slow query can be replayed.

## 4. Pagination and exports: PIT + search_after, never deep from/size

- `from + size` is for the first few pages only (it costs every shard `from + size`
  documents and is refused above `index.max_result_window`, 10 000 by default; do not raise
  that limit to make a bug go away).
- Anything deeper, and every export or batch walk, opens a **point in time**
  (`keep_alive` of a minute or two, renewed on each call), sorts on a deterministic
  tiebreaker (`_shard_doc` in the PIT, or the primary id as the last sort key), and pages
  with `search_after` carrying the last sort values. Close the PIT when done; a leaked PIT
  pins segments.
- The cursor the API hands out is opaque (PIT id + last sort values), never a page number.
- `size` is capped server-side; `track_total_hits` is `false` or a bound (`10000`) unless
  the UI really shows the exact total; counting is `_count`, not a search with `size: 0`
  unless aggregations are needed too.
- `scroll` is legacy: acceptable in an existing batch job, not for new code and never for a
  user-facing request.

## 5. Indexing: bulk, bounded, backing off

- Writes go through `_bulk` in batches sized by bytes (a few MB) rather than by count,
  with a bounded number of concurrent batches per process; the per-item response is
  checked, because a 200 bulk can contain failed items.
- 429 (`es_rejected_execution_exception`) is normal under load: retry the failed items with
  exponential backoff and jitter, bounded, then dead-letter or pause the indexer (see the
  event-consumer-safety skill); never tight-loop.
- The refresh policy is chosen on purpose: `refresh=false` for bulk and background indexing
  (the interval makes documents visible), `wait_for` only when a test or a read-after-write
  path needs it, `true` never in a loop. A large backfill lowers `refresh_interval` and
  `number_of_replicas` for the run and restores them after.
- Each document has a stable `_id` (the primary key); `_routing` is set when a tenant or
  key groups documents on one shard and the same routing value is used on read.
- Field values are bounded (long text truncated or stored elsewhere; `ignore_above` on
  keywords); a document that can exceed the HTTP body limit is split before indexing.

## 6. The cluster can be overloaded; the service must not be

- Every search carries a `timeout` (and the client a request timeout shorter than the HTTP
  handler's); a timed-out search returns partial results flagged `timed_out: true`, which the
  caller either accepts and marks, or treats as an error. Never ignore the flag.
- Searches that serve requests sit behind a bulkhead (bounded concurrent in-flight searches
  per process) and a circuit breaker: when the cluster is red, slow or rejecting, the feature
  degrades (cached results, a reduced query, "search unavailable") instead of exhausting
  threads and taking the whole service down.
- `allow_partial_search_results` is decided per query: acceptable for suggestions, not for
  an export or a compliance search.
- Client configuration: a pool of connections to several nodes (or the coordinating
  endpoint), sniffing only where the network allows it, compression on, retries only for
  idempotent reads, credentials from the environment, one client per process.
- Shard count and size are checked before go-live: a few tens of GB per shard, as few
  shards as the data needs (thousands of tiny shards are a cluster-wide cost), replicas for
  read throughput and resilience. A dated index pattern with one shard per day for a few
  MB per day is the common mistake.

## 7. Observe before and after shipping

- Slowlog thresholds set on the index (`index.search.slowlog.threshold.query.warn` and the
  fetch and indexing counterparts) and read during the first days of a feature; a query that
  appears there is tuned or redesigned.
- The profile API or `explain` is used when a query is slow, not guesswork about caching.
- Dashboards watch rejected executions per thread pool, search and indexing latency, JVM
  heap and GC, disk watermarks (a cluster at the flood-stage watermark makes every index
  read-only) and the lag between the primary store and the index.
- Integration tests run against a real node (container) with the production template,
  `refresh=wait_for` only where the test needs read-after-write, and assert on the query the
  code sends, not only on the result.

## Review checklist

- [ ] Index reached through an alias; mapping explicit, in a template, in the repository.
- [ ] Every filtered / sorted / aggregated field is `keyword`; `term` vs `match` correct.
- [ ] Non-scoring conditions in `filter`; tenant filter present and tested.
- [ ] Deep pages and exports use PIT + `search_after` with a tiebreaker; `size` capped;
      `track_total_hits` bounded; PIT closed.
- [ ] Bulk indexing bounded, per-item errors read, 429 backed off, refresh chosen on purpose.
- [ ] Every search has a timeout; `timed_out` handled; bulkhead and circuit breaker around
      the client; the feature degrades, the service stays up.
- [ ] Index can be rebuilt from the primary store; indexer idempotent and version-guarded.
