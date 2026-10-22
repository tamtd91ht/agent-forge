---
name: webhook-signature-verification
description: Accept an inbound webhook or provider callback (payment, messaging, social, CI, SaaS integration) only after proving who sent it - verify the provider's signature over the raw request bytes before parsing, compare in constant time, keep one secret per provider in the environment, reject stale timestamps to stop replays, answer failures with a generic 401 and a structured log that never contains the body, and only then process or publish. Use when adding or changing any endpoint that a third party calls into your system.
---

# Webhook signature verification (prove the sender before you trust the payload)

An unsigned webhook endpoint is a public API that lets anyone invent events: a fake
"payment succeeded" tops up a wallet, a fake "message received" opens a conversation, a
replayed "subscription cancelled" closes an account twice. Every provider that matters
signs its calls; this checklist makes the verification correct, in any language.

## 1. Verify before anything else

- The signature is checked **before** the body is parsed, validated, logged, stored or
  published. A handler that decodes JSON first has already acted on unverified input.
- Verify over the **raw request bytes**, read once. Re-serialising a parsed body changes
  whitespace, key order or unicode escapes and breaks the HMAC; a middleware that consumes
  the stream before the handler loses the bytes. Read the body into memory at the edge and
  pass both the bytes and the parsed form down.
- No endpoint ships without verification "temporarily for testing". A provider that cannot
  sign gets compensating controls (§6) and a written decision, not an exception.

## 2. Compare in constant time

String equality short-circuits on the first differing byte and leaks timing. Use the
platform's constant-time comparison on the decoded signature bytes:

| Language | Use | Never |
|---|---|---|
| Go | `hmac.Equal` | `==` on strings |
| Java / Kotlin | `MessageDigest.isEqual` | `String.equals` |
| Node | `crypto.timingSafeEqual` (same length first) | `===` |
| Python | `hmac.compare_digest` | `==` |
| .NET | `CryptographicOperations.FixedTimeEquals` | `SequenceEqual` |
| Ruby / Rails | `ActiveSupport::SecurityUtils.secure_compare` | `==` |

Decode the provider's encoding (hex, base64) before comparing; strip a documented prefix
(`sha256=`) rather than searching for it.

## 3. One secret per provider, from the environment

- Each provider has its own secret (`{PROVIDER}_WEBHOOK_SECRET`), read from the environment
  or a secret store, never from source or a committed config file, never shared between
  providers.
- Rotation accepts the **current and the previous** secret during a grace window, so the
  provider can switch without dropped events (see the secret-rotation practice).
- Provider specifics (header name, prefix, algorithm, timestamp header, tolerance) live in
  configuration keyed by provider, so a new provider is a config entry plus a secret, not a
  new code path.

## 4. Replays

- When the provider signs a timestamp (header or inside the signed string), reject calls
  whose timestamp is older than a tolerance (five minutes is a common default) **and**
  verify that the timestamp is part of the signed material, otherwise an attacker simply
  updates it.
- When the provider sends an event id, remember recent ids for at least the tolerance window
  and drop duplicates; a provider that retries legitimately will resend the same id.
- Money and account-state webhooks get both controls, not one.

## 5. Failure handling and logging

- Signature failure → `401` (or `403`) with a generic body: no hint about the algorithm,
  the header expected or which check failed.
- Log one structured line: provider, remote address, header name present or missing,
  outcome. Never the body, never the signature value, never the secret, at any log level.
- Success → process or publish; the stored or published event records `provider`,
  `receivedAt` and the verification outcome, so consumers can trust it without re-verifying.
- Verification happens at the **edge** that receives the call. A consumer behind a queue
  cannot verify (it has no raw bytes and no secret) and must not be asked to.

## 6. When a provider cannot sign

Write the decision down and apply compensating controls together: an IP allow-list for the
provider's published ranges, a per-endpoint shared token in the URL or header treated as a
secret (rotated, never logged), rate limiting, and a reconciliation job that confirms every
event against the provider's API before any money or account state changes.

## 7. Review checklist

- [ ] Verification runs before parsing and before any side effect; raw bytes read once.
- [ ] Constant-time comparison on decoded bytes; prefix stripped, not searched.
- [ ] One secret per provider from the environment; current + previous accepted during rotation.
- [ ] Timestamp tolerance and event-id dedup for replay; both for money and account events.
- [ ] Generic 401, structured log without body or signature; success recorded with provider and time.
- [ ] Provider specifics in configuration; unsigned providers have written compensating controls.
- [ ] Tests: a tampered body fails; a valid signature with a stale timestamp fails; a replayed
      event id is dropped; the previous secret works inside the grace window and not after.
