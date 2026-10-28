# Durable analysis coordination

Implemented locally on 2026-10-28. PostgreSQL is the durable queue; an API-lifetime
coordinator and two bounded worker threads consume it independently of the browser.
This is single-dispatch coordination, not an exactly-once distributed workflow engine.
The queue persists while the API is stopped; consumption resumes when a healthy API
starts. There is no separate always-running worker service.

## Identity, isolation and admission

Both analysis endpoints admit through the same ledger. An intent binds the verified
workspace, source-generation hash and loaded pipeline-source fingerprint. The source
fingerprint is frozen for the process lifetime; restart after code/config changes.
Concurrent requests reuse the admitted ID. Closed attempts remain closed and an
explicit new analysis gets a fresh ID. A changed source cannot return an old result.

Migration 003 adds stage claims and append-only runtime event metadata. Forced RLS
protects vectors, jobs, stages and events. The ordinary API role cannot execute the
global queue functions. The separate `dmc_dispatcher` login has no direct customer
table access or role memberships, a connection limit of eight, and only fixed,
schema-qualified SECURITY DEFINER claim/heartbeat/observe functions. PUBLIC execute
is revoked and their search path is fixed. No document text is returned by them.
Owner/schema credentials are never supplied to the API dispatcher.

Admission serializes per workspace and allows at most two unresolved jobs there.
Atomic claims serialize globally and allow two delivered/unresolved jobs with live
deadlines across API processes. Claims are FIFO among the loaded pipeline version;
unclaimed work from an obsolete release fails visibly. Queued deadlines begin when
claimed. Metadata observation is bounded and rotated to avoid starving older jobs.

## State and recovery

| State | Meaning | Safe behavior |
| --- | --- | --- |
| accepted | Persisted, not claimed | Background consumer claims it without a browser; survives API restart. |
| dispatching | Delivery may have occurred | Observe the same ID; never resend automatically. |
| uncertain | Delivery/completion not confirmed, including lost heartbeat | Reconcile exact saved case/stages; original callbacks may finish within the original deadline. |
| complete | Final artifact persisted | Read that exact attempt, subject to ownership and current source generation. |
| failed | Known refusal/not-started failure | An explicit admission can retry within the three-claim bound; closure allows a fresh identity. |
| cancel_requested | Cancellation acknowledged for delivered/uncertain work | Block further stages and late commits; wait until deadline for safe closure. |
| cancelled | Queued work cancelled, or attempt safely closed | Never revive this ID; a later explicit analysis uses a new one. |

The dispatcher does not expire a lease and replay an unknown request. A final case
is reconciled even when the webhook acknowledgement was lost. A committed stage
whose SQL acknowledgement was lost is reconciled from persisted case progress.
An in-flight duplicate stage is rejected before entering provider work; a completed
stage returns persisted progress. An ambiguous unfinished stage is never replayed.

The **Background activity** panel shows current work and history, refreshes visible
activity, reads saved progress, and confirms cancellation/closure. Failed reads are
distinct from an empty queue; stale entries have actions disabled. Opening progress
does not dispatch a workflow. Results use `/analysis/jobs/{id}/result`, not a
filename's latest case, and partial results are clearly labelled. Session errors
discard protected UI state. Event rows contain transition codes/times, not payloads.

## Budgets, cancellation and ingress

Transport runs in a supervised child process with a hard total deadline (maximum
900 seconds), refused redirects and a 1 MiB response cap. Credentials use private
stdin, never process arguments. Shutdown stops claims and kills owned transport;
known unstarted claims fail safely, possibly delivered work remains uncertain.
Callbacks have nested monotonic budgets of at most 180 seconds, also bounded by
the original job deadline. Provider SDK calls use remaining-time timeouts, a
120-second maximum per call and zero hidden SDK retries.

Cancellation and case commits serialize through the same cross-process workspace
lock. Commit guards check budget, job state, pipeline and generation before SQLite
commit. A cancellation acknowledged after a prior commit cannot undo that commit;
subsequent stages/commits are rejected. This does not cancel/refund an AI request
already accepted by a remote provider or hard-kill every synchronous OS operation.

Sixteen long-lived analysis observers have a separate bounded allowance. After a
bounded request body is read they release the eight-slot intake allowance, keeping
n8n callbacks available. SSE comments provide keepalives and timely disconnect
cleanup; a browser disconnect never cancels the background job.

## Operations and remaining boundaries

The local activation followed a zero-outstanding-job check, AES-GCM/DPAPI backup,
actual restore into a disposable database and exact vector-content comparison.
Migration 003 is already applied: never edit applied SQL; add a new migration.
The n8n start-node job-ID forwarding update was already applied after its own
verified backup; retention settings were preserved. No paid workflow was run.

Case/PDF/vector publication still spans different stores rather than a single ACID
transaction. Recovery quarantine remains necessary. All API instances sharing a
case store must share its workspace-lock filesystem; independent local disks are
not a supported multi-host topology. Document deletion cascades jobs/stages/events
and removes saved cases; it does not erase backups or accepted remote requests.
Off-machine recovery, real hosted fault/load tests and signed release verification
remain separate gates. No paid model-quality evaluation was performed.

See [operations](../OPERATIONS.md), [API contracts](../API_CONTRACTS.md) and the
[validation record](VALIDATION.md) for commands, exact evidence and scope.
