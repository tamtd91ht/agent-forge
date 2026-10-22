---
name: event-consumer-safety
description: Write a message consumer (Kafka, RabbitMQ, SQS, Celery task) that loses nothing, processes nothing twice and never blocks a queue on one bad message - acknowledge only after the work is committed, deduplicate by message id, classify failures into retryable and not, bound the retries, send the rest to a dead-letter queue someone owns, keep ordering per key, and shut down by committing before closing. Use when adding or reviewing any consumer, handler, listener or worker that reads from a broker.
---

# Event consumer safety (nothing lost, nothing doubled, nothing stuck)

A consumer fails in four ways: it acknowledges before it has finished and the message is
lost on a crash; it is redelivered and does the work twice; one poison message is retried
forever and the partition or queue behind it never moves; it is stopped mid-batch and the
offset it never committed is replayed. Every broker has the same four, with different knob
names. This is the checklist for writing and reviewing a consumer, whatever the broker.

## 1. Acknowledge after the work, never before

- Automatic acknowledgement is off (`enable.auto.commit=false`, `autoAck=false`,
  `acks_late=True`). The consumer acknowledges / commits **only after** its own transaction
  has committed, in the success path, never in a `catch` or `finally`.
- The work and the acknowledgement are two steps; a crash between them yields a redelivery,
  which §2 makes harmless. A crash before the work yields the same. There is no order of
  the two steps that loses a message once §2 holds.
- Prefetch / batch size is bounded (`max.poll.records`, `basicQos(prefetch)`,
  `worker_prefetch_multiplier`): unbounded prefetch is a memory bomb and a long redelivery
  storm after a crash.

## 2. Every consumer is idempotent

Redelivery is normal, not an incident. Before doing the work the consumer checks whether it
has already done it:

| Strategy | When |
|---|---|
| processed-id store (the message or event id, with a TTL longer than any redelivery window) | the default; needed whenever the work has a side effect that is not naturally idempotent |
| natural idempotency (upsert, set-to-value, overwrite) | state synchronisation; document why it is safe |
| version check (ignore an event older than the current state) | ordered state updates |

The check and the work belong to the same transaction, or the id is reserved first with a
unique constraint. A money or inventory consumer uses the operation's idempotency key, not
only the message id (see the money-safety skill).

## 3. Classify the failure before handling it

| Class | Examples | Handling |
|---|---|---|
| retryable | timeout, connection refused, pool exhausted, lock wait, 429 / 503 from a dependency | bounded retries with backoff (§4) |
| not retryable | cannot deserialise, schema mismatch, validation failed, unauthorised, unknown message type, any unexpected exception | straight to the dead-letter queue, no retry |

"Unknown exception" is **not retryable**: retrying what you do not understand is how a
partition gets stuck. A handler never swallows an exception (`catch … { log }` and
acknowledge is a silent loss).

## 4. Bounded retries, then a dead-letter queue someone owns

- Retries are bounded (three in memory with short backoff, optionally a few delayed-retry
  tiers through TTL queues or a retry topic; a handful in total). Backoff never below
  100 ms. A retry reuses the same message and the same idempotency key.
- After the last attempt the message goes to a **dead-letter queue** with its context as
  headers: original topic / queue, partition and offset or delivery tag, the exception type
  and a short message, the retry count, the consumer group, the owner id (tenant, account)
  when the system has one.
- The DLQ is durable, retained for weeks, **monitored** (depth, growth rate, age of the oldest
  message) and **owned** by a named team. A DLQ nobody reads is a slower way to lose messages.
- Replay from the DLQ goes through the normal consumer, so §2 protects it. Money and audit
  events are replayed by a person, never by an automatic job.

## 5. Ordering and concurrency

- Ordering is only per **key** (partition key, routing key, FIFO group), and only when the
  key is the business entity (account, order, customer), not a random id.
- Consumer instances for a group never exceed the partition count; extra instances idle and
  break ordering across rebalances. One handler thread per partition, or explicit per-key
  serialisation.
- Blocking I/O in a consumer runs where the broker client expects it (a worker pool, not the
  poll loop): a slow handler trips the poll timeout and triggers a rebalance storm.

## 6. Group names and subscriptions are explicit

- One consumer group per service per purpose, named for both (`billing.invoice-indexer`,
  not `group-1`); two services never share a group.
- Subscribe to named topics / queues, never to a wildcard pattern in production.
- Required headers (message type, owner id, correlation id) are read and validated before
  the body is deserialised; a message missing one is not retryable.

## 7. Shutdown and lag

- On stop: stop polling, finish in-flight work, **commit / acknowledge, then close** the
  client. Closing first replays everything since the last commit.
- Consumer lag per group is a metric with an alert; a lag that only grows is the first
  symptom of §3 and §4 being wrong.

## 8. Review checklist

- [ ] Auto-acknowledge off; acknowledgement only after the work's own commit.
- [ ] Dedup by message / operation id before the work, in the same transaction or by unique constraint.
- [ ] Failures classified; unknown exceptions go to the DLQ, not to a retry loop.
- [ ] Retries bounded with backoff; DLQ exists, carries context headers, is monitored and owned.
- [ ] Key = business entity; instances ≤ partitions; no blocking I/O on the poll thread.
- [ ] Group named for service + purpose; explicit subscriptions; required headers validated.
- [ ] Shutdown commits before close; lag is alerted.
- [ ] Tests: redelivered message is processed once; poison message lands in the DLQ with
      headers and the next message is processed; a crash after the work and before the
      acknowledgement does not double-apply.
