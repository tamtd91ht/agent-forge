---
name: tenant-isolation
description: Keep every tenant's data invisible to every other tenant in a multi-tenant service - tenant identity from the authenticated context only, a tenant condition on every query, cache key, message and search request, one tenant at a time in background jobs, explicit and audited cross-tenant paths, and the tests that prove it. Use when writing or reviewing any code that reads or writes tenant-scoped data, builds a cache key, publishes an event, or runs a job across tenants.
---

# Tenant isolation (multi-tenant data boundary)

A multi-tenant leak is rarely a clever attack. It is one query without the tenant condition,
one cache key built from the record id alone, one background job that iterates "all
customers". This skill is the checklist for every code path that touches tenant-scoped data,
and the review questions to ask before a change ships. It is stack-neutral; the pointers at
the end name the construct per stack.

## 1. Where the tenant identity comes from

| Source | Allowed? |
|---|---|
| the authenticated principal (session, verified token claims, mTLS identity) | **yes**, the only source |
| request body, query string, path parameter, header set by the client | **no**, a client may send any value |
| a value cached from an earlier request | **no**, resolve it per request |
| an admin or platform call that names a target tenant explicitly | only through the dedicated path in §4 |

Resolve the tenant once, at the edge (middleware, interceptor, handler base), and pass it
down as a parameter or a request-scoped context. A repository or service that *could* be
called without a tenant should not compile or should fail fast: make the tenant a required
argument, not an optional filter.

## 2. The condition on every layer

Each layer below needs the tenant condition **in every operation**, not only in the ones that
"obviously" need it.

| Layer | The rule | The typical leak |
|---|---|---|
| database reads and writes | tenant is the first condition of every query, update and delete; the tenant column is part of every unique index and foreign key that could cross tenants | `findById(id)`, `deleteWhere(status = …)`, a report query joining without the tenant |
| listing endpoints | no unfiltered list on a tenant-scoped table; always paginated | `findAll()` "for the admin page" |
| cache keys | `{namespace}:{tenant}:{id}` - the tenant segment is never omitted | key built from the record id because "ids are unique anyway" |
| messages and events | tenant in the payload **and** in the partition / routing key; consumers validate it | a consumer that trusts the id in the payload and loads the record without the tenant |
| search index | tenant filter is the first clause of every search; per-tenant index or alias when the engine allows it | a free-text search without the tenant term |
| files and object storage | tenant in the path prefix; signed URLs scoped to that prefix | a bucket shared across tenants with guessable object names |
| background jobs | iterate tenants explicitly and process one at a time inside a tenant-scoped context | a nightly job that aggregates across all tenants in one query |
| logs and metrics | tenant as a field, never as free text with PII | - |

When the database supports it, add a second line of defence that does not depend on
application code: row-level security policies, a per-tenant schema, or a per-tenant
database. Application-level filtering remains mandatory even then.

## 3. Identifiers and uniqueness

- Uniqueness is **per tenant**: `(tenant, email)`, `(tenant, external_id)`. A global unique
  index on a business key leaks existence ("this email is already registered") across tenants.
- Never accept a foreign key from the client without checking it belongs to the same tenant:
  "attach invoice X to customer Y" must verify both X and Y under the caller's tenant.
- Record ids should be unguessable (UUID / ULID) so that a missing tenant check is harder to
  exploit, but unguessable ids are not a substitute for the check.

## 4. Cross-tenant paths are explicit, named and audited

Platform operators, support tooling and billing sometimes need to read across tenants. Do not
relax the rule above; add a separate, visible path:

- a distinct entry point (an admin API, an internal service surface) with its own
  authorization (role or audience), never the regular tenant endpoints with a flag;
- the target tenant named explicitly in the request and **checked** against what the caller
  is allowed to administer;
- every cross-tenant read or write written to an immutable audit log: who, which tenant,
  what, when, why;
- platform-scoped data (tenant registry, global configuration) lives in clearly separated
  modules or packages so a reviewer can see at a glance which code is allowed to run without
  a tenant.

## 5. Tests that prove it

For every tenant-scoped aggregate, keep at least:

1. **Two-tenant test:** create a record under tenant A, read / update / delete it with tenant
   B's identity; expect not-found (not forbidden, which confirms existence).
2. **Listing test:** records under A and B; list as A; only A's records appear, with pagination.
3. **Cache test:** the same id under A and B does not collide in the cache.
4. **Event test:** an event published for A carries A's tenant and a consumer running as B
   rejects it.
5. **Job test:** a background job touches only the tenant it was started for.

A change that adds a query, a cache key, an event or a job without one of these tests is
incomplete.

## 6. Review checklist

- [ ] Tenant identity comes from the authenticated context; nothing from the request is trusted.
- [ ] Every new query, update, delete, cache key, event and search request carries the tenant.
- [ ] Every new unique constraint and foreign key includes the tenant.
- [ ] New listing endpoints are paginated and tenant-filtered.
- [ ] Any cross-tenant access goes through the explicit path in §4 with an audit entry.
- [ ] The tests in §5 exist for the touched aggregate.

## Per-stack pointers (use what the project already has)

- **SQL / ORMs** (JPA, Hibernate, Prisma, Django ORM, SQLAlchemy, ActiveRecord): a base
  repository or query scope that injects the tenant predicate; Postgres row-level security as
  the second line.
- **MongoDB:** `tenantId` first in every filter and as the leading field of compound indexes.
- **Elasticsearch / OpenSearch:** tenant `term` as the first `filter` clause; aliases per
  tenant when index-per-tenant is too costly.
- **Redis:** key prefix with the tenant segment; `SCAN` by prefix for per-tenant invalidation.
- **Kafka / RabbitMQ / SQS:** tenant in the message key / routing key and in the payload;
  consumers validate before loading state.
- **HTTP frameworks:** a middleware / interceptor / base handler that resolves the tenant from
  the verified principal and refuses requests without one on tenant-scoped routes.
