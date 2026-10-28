# ADR 0001: Transfer engineering patterns without copying service topology

Status: accepted for this local implementation, 2026-10-27.

## Context

The same owner has a Java/Spring Padel platform with stronger delivery,
resilience and evaluation evidence. DMC has a working React/FastAPI/Better
Auth/n8n application with sensitive document processing and existing local
data. A wholesale framework, authentication or database rewrite would change
several risk boundaries simultaneously and discard useful product work.

## Decision

Keep the current product stack. Adapt the demonstrable properties: bounded
transport, explicit resource state, session invalidation, safe errors,
conditional writes, dependency admission, architecture checks, failure tests
and honest release evidence. Reimplement them in the target's language and
cookie-authentication model; do not copy business rules, credentials, test
accounts, infrastructure identities or generated release artifacts.

Keep UI resource snapshots memory-only. Do not persist document contents in
localStorage for convenience. Retain mandatory evidence checks and human
approval; an elegant UI cannot relax an evidence gate.

Keep the Chroma production block until a reviewed patched implementation or
replacement is tested. A storage migration needs an inventory, backup,
checksum/tenant-isolation tests and rollback plan. No migration runs as an
incidental consequence of an audit.

Use revision compare-and-swap for case stages now. Do not label it idempotency
or exactly-once delivery. Durable jobs and transactional event intent need a
separate reviewed schema and recovery design.

## Storage and job follow-up

The reviewed replacement and migration were completed on 2026-10-27.
PostgreSQL/pgvector now enforces tenant RLS and schema fingerprints. A separate
durable admission/claim ledger coordinates dispatch without claiming
exactly-once execution. See [storage](../SECURE_STORAGE.md) and
[analysis coordination](../DURABLE_ANALYSIS.md).

## Consequences

This delivers independently testable reliability improvements without
deploying extra services. It does not confer Padel's release guarantees.
Process-local circuits do not provide a cluster quota, mocked browser routes
do not prove backend authorization, and security configuration files do not
prove a hosted environment applied them. Those gaps have explicit acceptance
criteria in the [roadmap](../ROADMAP.md).
