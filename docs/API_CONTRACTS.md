# API failure and lifecycle contracts

Browser APIs use Better Auth cookies and the existing `X-CSRF-Protection`
mutation header. No browser API key or client-selected workspace is introduced.
Legacy cookie/header names remain compatible with existing local accounts.

## Request bounds

Assistant/research/supervisor/panel questions are trimmed, nonempty and at
most 4,000 characters. Optional document selectors are trimmed, nonempty and
at most 255 characters. Conversation history is at most ten user/assistant
turns, each with nonempty content at most 16,000 characters. Unknown fields
and privileged system/developer history roles are rejected. These bounds are
independent of the existing HTTP-body and PDF-upload limits.

## Ordinary HTTP errors

FastAPI HTTP/validation handlers return `application/problem+json` with RFC
9457 fields `type`, `title`, `status`, `detail`, `instance`, plus `code`,
`request_id`, `retryable`. Validation returns field locations/types without
raw submitted input. `X-Request-ID` is exposed to trusted CORS clients. An
incoming ID must match `[A-Za-z0-9._-]{1,64}`; otherwise it is regenerated.
Errors are not cached. Unexpected exceptions have a generic public message.

| Code | Typical status | Caller behavior |
| --- | --- | --- |
| AUTH_REQUIRED | 401 | Discard protected resource state; sign in again. |
| FORBIDDEN | 403 | Discard this resource; do not retry with a guessed workspace. |
| INVALID_REQUEST | 422 | Correct structural input; do not display submitted payloads in diagnostics. |
| CASE_CHANGED | 409 | Reload the current persisted case before deciding to repeat an operation. |
| RATE_LIMITED | 429 | Respect `Retry-After` when supplied; no automatic mutation replay. |
| DEPENDENCY_UNAVAILABLE | 503 | Show recoverable service failure; preserve only labeled safe stale snapshots. |
| ANALYSIS_UNCERTAIN | 503 | Read saved progress; retryable=false; never automatically dispatch another analysis. |
| HTTP_500 | 500 | Show the safe message and request ID; do not expose internals. |

Browser parsing accepts the older string `detail` shape as well. Some edge
middleware responses retain their framework-specific contract; this is not
a claim that every byte from every dependency follows RFC 9457.

## Streaming and time budgets

SSE JSON events retain their existing `type` vocabulary. `error` is terminal
failure and `done` is required for successful completion. EOF before `done`,
invalid JSON and oversized unfinished frames are errors, not partial success.
CRLF, comments, multiline data and split UTF-8 are supported. Readers are
cancelled/released after completion, abort or error.

The shared browser transport budgets fetch **and body consumption**: ordinary
requests default to 30 seconds, upload to 180 seconds, audit to 120 seconds,
and analysis streams to 960 seconds. These values preserve the existing
long-running workflow; they are limits, not latency objectives. Request
options may override them with a positive finite budget.

The n8n webhook has a hard 900-second total child-process deadline and a
separate observer deadline. Job callbacks validate a persisted deadline;
provider calls use nested monotonic budgets, explicit timeouts and no hidden
SDK retries. Redirects are refused and response size is capped at 1 MiB.
This does not promise hard cancellation of accepted remote work.

Timeout/network loss after sending a mutation has an **uncertain outcome**:
the server may already have completed it. Refresh before retrying; the client
does not automatically replay writes. Aborting the browser stops local work
and stale rendering, not necessarily an already-running remote analysis.

## Persistence and probes

Case stages save with the revision they read. A mismatching revision/deleted
case is a conflict; it must not overwrite newer work. Revision timestamps
advance strictly even when clock samples collide. This does not guarantee
exactly-once processing. A separate PostgreSQL job ledger and stage claims
coordinates one dispatch per source/pipeline intent; reconnects observe its
saved case. `ANALYSIS_UNCERTAIN` forbids blind replay and offers a saved-progress
read. See [durable analysis and its limits](engineering/DURABLE_ANALYSIS.md).

`/health` remains compatible. `/livez` reports process liveness. `/readyz`
checks auth DB availability with a two-second timeout when auth is required,
and requires a healthy coordinator when background dispatch is enabled.
This checks recent queue-loop health, not an end-to-end n8n/LLM/CDR request.

## Background activity

All routes below require the existing verified workspace session; foreign IDs
return 404. No caller-supplied workspace is accepted. UUIDs are normalized.

| Route | Contract |
| --- | --- |
| GET `/analysis/jobs` | At most 50 recent jobs, with safe reconciliation; no dispatch. |
| GET `/analysis/jobs/{id}` | One job plus up to 100 transition event codes/actors/timestamps. |
| GET `/analysis/jobs/{id}/result` | Exact saved case for this attempt and current source generation, or 404; never a different attempt's latest result. |
| POST `/analysis/jobs/{id}/resolve` | Strict JSON action `cancel` or `close`; existing trusted-origin/CSRF protections; no automatic retry. |

Job metadata exposes ID, filename, state, attempts, deadline/timestamps, safe
reason codes, `can_cancel`, `can_close` and `result_available`. Worker credentials,
pipeline/generation fingerprints and document text are absent from metadata.
The result route intentionally returns the actor-owned public case payload.
Unavailable results after deletion/replacement are not empty successful results.

Queued cancellation is immediate. Delivered/uncertain work becomes
`cancel_requested`; new stages and late commits are fenced. Closure of uncertain
work before its deadline is 409. A closed attempt is never reset; explicit new
analysis gets a fresh identity. Original uncertain callbacks may complete within
the original deadline, unless cancelled. Accepted remote provider work cannot
be undone by a browser abort or local cancellation.

Analysis streams include SSE comment keepalives. Browser connections observe
background work rather than owning it; disconnect does not cancel the job.
Sixteen analysis observers release the eight-slot intake guard after bounded
body consumption, so idle observers do not starve workflow callbacks.
