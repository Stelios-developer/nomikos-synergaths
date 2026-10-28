# Local operations and failure behavior

## Scope and commands

Run project commands from the repository root. `npm run check` validates
publication candidates, import boundaries, documentation, lint/build and auth
types. `npm test` runs repository, transport/state and auth tests.
`npm run test:backend` creates a fresh ignored temporary test directory and
uses the project's Python environment. It does not target the live stores.
Optional `DMC_PYTHON` selects a compatible interpreter for ordinary checks.

`npm run audit:python` explicitly sends only this project's installed package
names/versions to the public OSV API. The script refuses system Python and
other project environments, and requires its `--allow-osv` opt-in. Its output
is ignored at `output/security/python-audit.json`. An unavailable, incomplete
or paginated response is not a clean audit. This command is not an OS/image
scanner. Never point it at Padel or unrelated package inventories.

The browser suite needs a separate loopback Vite server and synthetic API
fixtures; see [testing](TESTING.md). CI artifacts have seven-day retention and
must contain synthetic browser evidence or sanitized security summaries only.

## Failure and recovery

- A failed document-list load is not an empty account. Retry the read. A
  failed refresh labels and retains the previous memory snapshot while
  disabling actions against it; 401/403/404 discard it.
- A timed-out mutation may already have completed. Inspect current server
  state before submitting again. There is no automatic write replay.
- Case 409 `CASE_CHANGED` means a worker tried to save an old revision.
  Reload; do not overwrite the winner. It can also mean the case was deleted.
- The n8n dependency guard admits two calls per API process. Three consecutive
  transient failures open it for 30 seconds; one recovery probe is allowed.
  The PostgreSQL ledger separately enforces two active/unresolved jobs per
  workspace across API processes.
- Webhook redirects are refused. A 401/403 is a configuration/authorization
  failure, not a reason to flood a dependency or open its transient circuit.
- Browser abort ignores late responses and cancels local readers. Existing
  remote workflow work may continue. Durable single-dispatch jobs, hard webhook
  deadlines and nested provider budgets are implemented. Background consumption
  is active while the API runs; remote cancellation remains limited; see
  [durable analysis](engineering/DURABLE_ANALYSIS.md).

`/livez` is process liveness; `/readyz` checks auth DB availability when auth
is required and recent dispatcher health when enabled. Neither promises that model, scanner or n8n work will
complete. Existing `/health` is compatible. Do not attach a paid inference
call to a frequent readiness probe.

Request IDs allow support correlation without a document filename in metrics.
Unexpected request failures log the exception class with the request ID, not
exception text or the submitted document. Route-template metrics avoid
filename cardinality. Existing streaming timing is not a complete workflow
latency SLO; provider traces/redaction and alert delivery still need dedicated
verification before production. Exported exception spans have a regression
test for class-only diagnostics without provider/document message text.

## Data and release boundaries

The local vector-store and Python image gates now pass; hosting, release signing
and off-machine recovery remain separate gates. Do not remove schema/security
checks to obtain a green boot. Do not run a storage
migration, purge, live upload/delete test or container reset as an incidental
health check.

Existing n8n encrypted backup/restore tools and their limits are documented in
[retention and recovery](DATA_RETENTION_AND_RECOVERY.md). A successful n8n
restore is not proof of coordinated restoration of every DMC store. The
[roadmap](engineering/ROADMAP.md) lists the missing consistency/RPO/RTO gates.

Preserve any existing staged changes when performing maintenance. Inspect
`git diff`, `git diff --cached`, both `--check` forms and the
exact index safety checker before a commit. No deployment, GitHub protection
change, signing operation or push was performed as part of the local audit.

## Background dispatcher runbook

Set `ANALYSIS_DISPATCH_ENABLED=true` and a distinct
`ANALYSIS_DISPATCH_DATABASE_URL` for the restricted `dmc_dispatcher` role.
Use the runtime-only vector DSN separately. `scripts/setup_vector_database.py`
is an explicit owner operation creating/verifying roles and migrations;
the API never applies DDL. Keep credentials in ignored environment files.
Production dispatch requires a reviewed host and `sslmode=verify-full`.

The API lifespan starts two workers and one coordinator. Failed configuration
or role/schema verification refuses startup. A stopped/stale dispatcher makes
readiness and new admissions fail closed. PostgreSQL retains queued work during
an API outage; it is consumed after restart, without opening a browser. There is
no separate daemon that runs while every API process is offline.

Before code/queue maintenance, stop new submissions and inspect **Background
activity**. Never reset unknown work to `accepted`. Keep original job identity
while checking saved progress. A missing heartbeat after 30 seconds becomes
uncertain; a final saved case/stage may settle it without another provider call.
The original deadline still fences callbacks. Cancel queued work directly;
request cancellation for delivered work and wait for safe closure. Closure is
an explicit action and does not itself start replacement work.

For migration maintenance use the zero-job encrypted backup/restore checks in
`scripts/backup_vector_database.py` and `scripts/activate_local_dispatcher.py`.
Activation already applied migration 003 locally; never edit applied migration
bytes. The backup contains sensitive data and its DPAPI key is machine/profile
bound, not an offsite recovery solution. Preserve the old image for rollback;
an older application that cannot understand schema 003 must not serve this DB.

Graceful shutdown stops claims, wakes workers and terminates owned transport.
Possibly delivered requests stay uncertain. Forced termination is not a remote
rollback. All API processes using one case store must share the lock filesystem;
multi-host local SQLite copies are unsupported. Capacity is two active claims
globally, two unresolved jobs per workspace, sixteen stream observers per API
process and eight bounded body intakes. These bounds are not a throughput SLO.
