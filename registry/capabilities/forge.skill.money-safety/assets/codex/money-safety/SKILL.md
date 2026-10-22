---
name: money-safety
description: Make every change to a balance, wallet, invoice, payment, refund or ledger safe to retry and impossible to double-apply - integer minor units, an idempotency key checked before the state change, one atomic transaction or a saga with compensation, serialised operations per account, balance validated under a lock inside the transaction, bounded retries, an immutable audit entry, outbox and idempotent consumers for money events. Use when designing, implementing or reviewing any code that moves or records money.
---

# Money safety (state changes that must never double-apply)

Money code fails in one of three ways: an operation runs twice (a retry, a redelivered
message, a double click), two operations race on the same account, or a multi-step flow
stops half-way. None of these is a corner case; every one of them happens weekly in
production. This skill is the checklist to run **before** writing the code and **when**
reviewing it. It is stack-neutral.

## 1. Four questions before any design

Answer in writing, in the design note or the PR description:

1. **Real or virtual?** Does this touch an external money movement (card, bank, wallet
   provider) or only an internal balance? External movements need a reconciliation path.
2. **What changes the balance?** List every operation that credits or debits, including
   corrections, reversals and fees.
3. **What happens if it runs twice?** For each operation: duplicate charge, duplicate credit,
   or harmless? Nothing is "harmless" until the idempotency key in §3 proves it.
4. **Does order matter?** Two operations on the same account in the wrong order can produce
   a negative balance that each one alone would have refused.

If any answer is unknown, stop and ask before coding.

## 2. Representation

- Amounts are **integers in minor units** (cents, satoshi, the currency's smallest unit) with
  the currency code next to them. Never a float, never a string parsed at the edge.
- Arbitrary-precision decimals (`BigDecimal`, `Decimal`, `NUMERIC(19,4)`) only where a
  fraction is unavoidable (exchange rates, tax computation), rounded once, with the rounding
  mode written down (banker's rounding unless the regulator says otherwise).
- A money value object (amount + currency) that refuses to add two currencies.

## 3. Idempotency before the state change

Every money operation carries a client-supplied or deterministic **idempotency key** and the
service checks it **before** touching the balance:

- key = `{tenant or account owner}:{account}:{operation type}:{client request id}`; the
  client request id comes from the caller (header or field), not from the server clock;
- the check and the state change are in the same transaction, or the key is reserved first
  with a unique constraint so a concurrent duplicate fails at the database;
- a repeated key returns the **original result**, not an error and not a second execution;
- keys are kept at least as long as a retry can arrive (days, not minutes).

## 4. Atomicity and multi-step flows

- One account, one transaction: debit, credit, ledger entry and audit entry commit together
  or not at all.
- Across services or external providers (a saga): every forward step has a **compensation**
  step, the saga's state is stored durably after every step, and a recovery process resumes
  or compensates interrupted sagas. No "partial success" is ever reported as success.
- A balance change and its event are published through an **outbox** in the same
  transaction, never by a publish call after the commit (which can be lost or duplicated).

## 5. Serialise operations on the same account

Two operations on the same account must not interleave:

- a row-level lock (`SELECT … FOR UPDATE`) or an optimistic version check inside the
  transaction, **taken before** any check-then-act (`if balance >= amount: debit`);
- for message-driven flows, the partition / routing key is the **account or business key**,
  so one consumer processes one account's operations in order;
- the balance read for validation comes from the transaction, **never from a cache**.

## 6. Retries

- Classify failures: **retryable** (network, timeout, lock wait) vs **not retryable**
  (insufficient balance, invalid input, rejected by provider). Only the first class is retried.
- Bounded retries (three is a sane default) with backoff; after that the operation goes to a
  dead-letter path that a person or a reconciliation job looks at.
- A retry reuses the **same idempotency key**; a new key is a new operation.

## 7. Audit

Every balance-changing operation writes an immutable audit entry: actor, account, operation
type, amount and currency, previous balance, new balance, idempotency key, timestamp, reason
or reference. Retention follows the regulator (years, not months). The audit table is
append-only: no updates, no deletes, corrections are new entries.

## 8. Money events and consumers

- Payload carries amount, currency, account, operation id and idempotency key; never a raw
  card number or account secret.
- Producers use the outbox (§4) and acknowledged writes; consumers are **idempotent** (they
  check the operation id before acting) and commit their offset only after their own
  transaction succeeds.
- A dead-letter queue exists and someone owns it.

## 9. Review checklist

- [ ] Amounts are integer minor units with a currency; no floats.
- [ ] Idempotency key composed as in §3, checked before the state change, inside the transaction.
- [ ] Single transaction, or a saga with stored state and a compensation per step.
- [ ] Lock or version check taken before check-then-act; balance read inside the transaction.
- [ ] Retries bounded, classified, same key; dead-letter path owned.
- [ ] Immutable audit entry with previous and new balance.
- [ ] Events via outbox; consumers idempotent; DLQ present.
- [ ] Tests: duplicate request returns the original result; two concurrent debits cannot
      overdraw; an interrupted saga is compensated or resumed.
