---
name: vertx-patterns
description: Write and review Vert.x code (Java or Kotlin) - never block the event loop (no JDBC, Thread.sleep, synchronous HTTP or heavy CPU on it; executeBlocking or a worker verticle instead, the blocked-thread checker left on), compose Futures instead of nesting callbacks and never call result() or join(), put a timeout on every outbound call and propagate cancellation, keep per-verticle state on its own context and share through the event bus with registered codecs and named addresses, configure clients once with bounded pools, deploy verticles with explicit instances and config, close in reverse order on shutdown, and test with vertx-junit5 checkpoints and timeouts. Use when adding or changing a verticle, a handler, a route, an event-bus consumer, an outbound client call or a Vert.x test.
---

# Vert.x patterns (nothing blocks the loop, every call has a timeout)

Vert.x has one rule and many ways to break it: an event loop thread that blocks stalls every
connection it serves. The breakages look innocent (a JDBC call in a handler, a `Future.result()`
in a test helper, a JSON parse of a 50 MB body, a synchronous HTTP client from a library) and
only show under load. The rest of this checklist is about the second rule: a reactive program
with no timeouts is a program that leaks.

## 1. Nothing blocks the event loop

- On an event loop (`Vertx.vertx()` verticles, `Handler`s, route handlers, event-bus
  consumers): no JDBC, no `Thread.sleep`, no `synchronized` waiting, no `CompletableFuture.join()`,
  no synchronous HTTP, no file I/O through `java.io`, no heavy CPU (large JSON, compression,
  cryptography on big inputs). Use the reactive clients (`vertx-pg-client`, `vertx-mysql-client`,
  `vertx-mongo-client`, `vertx-kafka-client`, `vertx-redis-client`, `WebClient`, `FileSystem`).
- Code that must block (a legacy driver, a blocking SDK) runs in `executeBlocking` (ordered
  `false` unless order matters) or in a **worker verticle**, with the worker pool sized and
  named (`setWorkerPoolName`, `setWorkerPoolSize`) so it can be observed and bounded.
- The blocked-thread checker stays on in every environment (`setBlockedThreadCheckInterval`,
  `setMaxEventLoopExecuteTime`); a warning in the log is a defect, not noise.
- A library is only used from the event loop after checking it is non-blocking; a blocking
  one is wrapped once, in one place, with the wrapper documented.

## 2. Futures compose; callbacks do not nest

- `Future.compose` / `map` / `recover` / `onFailure` (or Kotlin coroutines with `await`):
  one chain per operation, failure handled at the end of the chain, never a chain that ends
  without an `onFailure` or a returned `Future` (an unhandled failed Future is silent).
- Never `Future.result()`, `.cause()` polled, `.toCompletionStage().toCompletableFuture().join()`
  or `CountDownLatch` on an event loop; those are blocking in disguise.
- Fan-out with `Future.all` / `Future.any` / `Future.join` (`join` when every branch must
  finish; `all` when one failure should abort); a loop that launches an unbounded number of
  futures is bounded with a semaphore-like counter or batches.
- A handler that throws is a handler that drops the request: wrap, or rely on the router's
  failure handler, and always finish the response (`ctx.fail(...)` / `ctx.response().end()`).
- Exceptions carry context (which call, which key) and are mapped to responses in one
  failure handler per router; stack traces never leak to clients.

## 3. Every outbound call has a timeout; cancellation propagates

- `WebClient` requests: `timeout(ms)` per request, connection pool bounded (`setMaxPoolSize`),
  `setIdleTimeout`, `setConnectTimeout`; a retry policy only for idempotent requests, with
  backoff and a bound.
- Event-bus `request`: a `DeliveryOptions.setSendTimeout`; reply with a failure code the
  caller handles.
- Database clients: pool size bounded (`PoolOptions.setMaxSize`) and sized against the
  database's connection budget, statement timeout set on the server side or per query, no
  pool per request.
- `Future.timeout(...)` (or `vertx.setTimer` + `tryFail`) on any composed operation that
  serves a request, shorter than the server's request timeout, with the downstream work
  cancelled or at least ignored when the timer fires.
- Periodic work (`setPeriodic`) guards against overlapping runs (skip if the previous run
  is still in flight) and is cancelled on undeploy.

## 4. State belongs to a context; sharing goes through the event bus

- A verticle instance owns its state; it is single-threaded within its context, so no
  locks are needed and no state is shared between instances by static fields. Deploying
  `instances: n` means `n` copies of that state.
- Cross-verticle sharing: the event bus (named addresses in one constants class, a
  `MessageCodec` registered for every non-JSON type, request/reply for commands, publish for
  events), `SharedData` local maps or `AsyncMap` / `Lock` / `Counter` for cluster-wide
  coordination. A `ConcurrentHashMap` static is the wrong answer in a cluster.
- Event-bus consumers register in `start()` and are unregistered on `stop()`; a consumer
  that does work for a message is idempotent on redelivery, as any consumer is (see the
  event-consumer-safety skill when the bus bridges to a broker).
- A handler never captures a `RoutingContext` beyond the response's lifetime and never
  holds a reference across a `compose` that may run after the response ended.

## 5. Deployment, configuration and shutdown are explicit

- Verticles are deployed with `DeploymentOptions` naming `instances`, `config`
  (`vertx-config` from env / files, validated at start, secrets from the environment), and
  `worker` / `threadingModel` where needed; the main verticle composes the deployments and
  fails fast when one fails (`deployVerticle(...).onFailure(... -> vertx.close())`).
- HTTP server: `setMaxHeaderSize`, `setMaxFormAttributeSize`, body size limits on
  `BodyHandler`, compression chosen, `setIdleTimeout`; the server listens only after every
  dependency it needs is ready, and a readiness route reports that.
- Shutdown: on SIGTERM, stop accepting (close the server), let in-flight requests finish
  within a bound, undeploy verticles in reverse order (`stop(Promise)` completes only after
  its resources close), close clients, then `vertx.close()`. `stop()` that returns before
  its resources are closed is a resource leak on every redeploy.
- Metrics (`vertx-micrometer-metrics`) and the blocked-thread log are part of the service's
  dashboards: event-loop utilisation, pool usage per named pool, HTTP client pool queue.

## 6. Tests are asynchronous too

- `vertx-junit5`: `VertxTestContext` with `completeNow()` / `failNow()`, `checkpoint()` for
  every expected callback, `@Timeout` on each test, assertions inside `testContext.verify`
  so an assertion failure fails the test instead of being swallowed in a handler.
- Never `Future.result()` or `Thread.sleep` in a test to "wait"; await the Future
  (`toCompletionStage().toCompletableFuture().get(timeout)` from the **test** thread is
  acceptable, not from an event loop).
- One `Vertx` instance per test class, closed after; verticles deployed in `@BeforeEach`
  and the deployment awaited; ports chosen at `0` and read back from the server.
- Integration tests run the real reactive client against a container, and at least one
  test asserts that a handler does not block (a `BlockedThreadChecker` warning captured
  from the log fails the test).

## Review checklist

- [ ] No blocking call on an event loop; blocking work in `executeBlocking` / a named worker
      pool; blocked-thread checker on.
- [ ] Every Future chain ends in `onFailure` or is returned; no `result()` / `join()` on a
      loop; fan-out bounded.
- [ ] Every outbound call, request/reply and composed request operation has a timeout; pools
      bounded and sized.
- [ ] Verticle state on its context; sharing through the event bus with codecs and named
      addresses or `SharedData`; consumers unregistered on stop.
- [ ] Deployment options explicit; server limits set; readiness after dependencies; shutdown
      closes in reverse order inside `stop(Promise)`.
- [ ] Tests use `VertxTestContext` checkpoints and timeouts; no sleeps; verify blocks.
