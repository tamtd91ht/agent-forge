---
name: event-contract
description: Design the publishing side and the topology of an event-driven system - transactional outbox so state and event commit together, an envelope every message carries, partition and routing keys that are business keys, topic naming with one message type per topic and a version, compatible schema evolution, reuse-before-create and a retirement path for topics, durable producer settings, full payloads built by the producer, and when a synchronous call is the right transport instead. Use when creating a topic, queue or exchange, adding a producer, changing an event's shape, or choosing between an event, a command and an RPC call.
---

# Event contract (publishing side and topology)

The consuming side (`event-consumer-safety`) can only be as safe as what it is given. A
producer that publishes after its database commit loses events; a topic that carries three
message types forces every consumer to branch and skip; a second topic created because the
first was hard to find leaves two half-maintained flows. This skill is the checklist for
producers, topics and the contract between them.

## 1. State and event commit together: the outbox

- A domain event is written to an **outbox table or collection in the same transaction** as
  the state change it describes. A separate relay (poller, CDC) publishes outbox rows and
  marks them sent.
- Never publish from inside the business transaction (the broker may accept while the
  transaction rolls back) and never after it (the process may die in between). Both are
  dual writes.
- The relay is idempotent and at-least-once; consumers deduplicate (their skill, §2).
- Producer settings favour durability: Kafka `acks=all` + `enable.idempotence=true`;
  RabbitMQ persistent delivery (`deliveryMode=2`), durable (quorum for critical) queues,
  publisher confirms with a timeout and a handled return for unroutable messages. "Fire and
  forget" (`acks=0`, transient messages) is for metrics, never for state.

## 2. The envelope

Every message carries, in headers or a fixed top-level block:

| Field | Why |
|---|---|
| `id` (UUID / ULID) | the consumer's dedup key |
| `type` (`customer.created`) | routing and dispatch without deserialising the body |
| `version` of the schema | consumers choose the parser; evolution without a flag day |
| `occurredAt` (UTC) | ordering and age; not the publish time |
| `correlationId` | tracing across services |
| `source` (producing service) | ownership and debugging |
| owner id (tenant, account) when the system has one | isolation and routing, validated by consumers |

Payloads carry identifiers and the facts that changed; never secrets, raw credentials or
unmasked personal data (mask or encrypt at the producer).

## 3. Keys and ordering

- The **partition / routing key is the business entity** the event is about (customer,
  account, order). A random key gives no ordering; a constant key gives no parallelism.
- Ordering is promised only per key. Anything that needs global order is a design smell,
  not a broker setting.

## 4. Topics: naming, one type each, a version

- Name: `{domain}.{kind}.{event-name}.{version}` (`billing.event.invoice-issued.v1`,
  `notification.command.send-email.v1`); lowercase, dots or hyphens, no environment or tenant
  in the name, no generic names (`events`, `data`).
- **One message type per topic.** Commands and events never share one; events of different
  aggregates share one only with a written, low-volume justification. A consumer must never
  read a message and skip it because it was meant for someone else.
- Every topic has an explicit retention class (events days, commands shorter, DLQ weeks,
  audit long, compacted state forever), replication and in-sync settings for production, and
  a dead-letter topic per consumer group.
- Topic and queue names live in **one constants module per service**, never as inline string
  literals; a shared registry document (who produces, who consumes, with which group) lists
  them across services.

## 5. Schema evolution

- Compatibility is backward (transitive) by default: add optional fields, never rename,
  remove or retype one in place.
- A breaking change is a new version in the topic name, produced in parallel for a bounded
  window while consumers move, then the old one is retired (§6). Flag days do not exist.
- A schema registry or a contract test per producer keeps the written contract and the
  bytes on the wire equal.

## 6. Reuse before create, retire after replace

Before creating a topic, search the constants modules of every service and the registry
document. The same domain plus the same consumer role means **reuse** (add a `type` variant),
not a second topic. A new topic is justified by a different consumer set, retention class,
traffic class or command-versus-event separation, stated in the PR.

Replacing a topic owns the old one's retirement:

| Phase | Exit criterion |
|---|---|
| announce | old constant deprecated with a pointer to the replacement and a cutover date |
| dual-produce (optional, bounded) | parity proven on the consumer side |
| cutover | every producer moved, tracked per producer |
| drain | old-topic lag is zero; no producer or consumer references remain |
| retire | constant, group, DLQ, physical topic and registry row removed |

A topic string that no producer or consumer uses (documentation only) is a phantom: delete
it, never wire to it.

## 7. The producer builds the payload; the consumer delivers

For dispatch-style flows (notifications, exports, webhooks): the producer, which holds the
data at the moment of the event, builds the **full payload** (recipient, variables, locale)
and chooses the **channel** by choosing the topic. The consumer is mechanical: load the
template, substitute, deliver. A consumer that calls back to the producer (or a third
service) to fetch business data has the dependency pointing the wrong way and a new failure
point mid-flight. Each channel is its own topic with its own group; a shared realtime
transport (socket push) is a consequence of delivery, not a channel a business producer
publishes to.

## 8. Which transport

| Need | Transport |
|---|---|
| a fact happened; several parties may care; replay useful | event on a durable log (Kafka, Pulsar, event streams) |
| do this once, exactly one worker, maybe delayed | command on a queue (RabbitMQ, SQS, Celery) |
| the caller needs the result before it can answer its own caller | synchronous call (HTTP / gRPC) through a dedicated client package, with timeouts and a circuit breaker |
| delay ≤ an hour | TTL + dead-letter forward to the target (pre-declared tiers, named with the duration) |
| delay > an hour | a scheduler that publishes later; never a queue holding messages for hours |

Never a synchronous call for work that needs no immediate answer; never a shared domain
model library as the "contract" between services.

## 9. Review checklist

- [ ] Event written to the outbox in the state change's transaction; relay separate and idempotent.
- [ ] Durable producer settings; no fire-and-forget for state.
- [ ] Envelope complete; key = business entity; no secrets or raw PII in payloads.
- [ ] Topic name follows the format with a version; one message type; retention and DLQ declared; names in constants.
- [ ] Change is backward compatible or ships as a new version with a retirement plan.
- [ ] Searched for an existing topic first; the PR states why reuse was not possible.
- [ ] Dispatch flows: producer builds the payload and picks the channel; consumer does not fetch.
- [ ] Transport chosen by the table in §8; delays over an hour go to a scheduler.
