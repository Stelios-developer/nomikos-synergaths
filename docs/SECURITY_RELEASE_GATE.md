# Documents Made Clear security and trust release gate

This is a release checklist, not a certification or penetration-test report.
Do not describe Documents Made Clear as end-to-end encrypted, malware-free, or suitable for
regulated confidential data until the relevant controls have been independently
verified in the deployed environment.

## Current status after storage and image replacement, 2026-10-28

The ChromaDB runtime blocker described in the historical checks below has
been resolved by replacement, not suppression: the API uses PostgreSQL/pgvector
with forced RLS, explicit workspace access, checked migrations and a limited
database role. The old package was uninstalled. The subsequent installed audit
checked 159 packages and passed; a fresh hash-locked environment checked 134
and passed. Exact migration and actual restore evidence are recorded in
[secure storage](engineering/SECURE_STORAGE.md).

The current continuation also delivered autonomous background consumption while
the API runs, persistent stage claims, cancellation/commit serialization,
lost-ack reconciliation and an authenticated activity/closure UI. Unknown work
is never automatically resent. Real SQL and three-engine UI tests cover these
boundaries; no paid AI test was run.

The old Debian image findings were remediated using pinned Wolfi candidates,
without advisory exclusions: current full-severity backend/PDF-worker scans
report zero OS/Python advisory-package records. Exact-image imports/source
checks and synthetic English/Greek OCR/CDR pass. These are scoped scan/test
results, not a vulnerability-free or production certification. See the
[current validation record](engineering/VALIDATION.md) and
[image gate](engineering/DEPENDENCIES.md). Configured CI has not executed
on GitHub; release signing, production/provider encryption and hosting remain
unverified. Historical failed image reports remain available locally.

The refreshed auth-image scan exposed new Better Auth 1.6.26 advisories. Both
client/service were upgraded together to 1.7.14; current npm and rebuilt image
scans report zero findings. A disposable-database test verifies real signed
cookies against the backend, tampering/wrong-password denial and sign-out
revocation. Read-only planning confirms the existing local auth schema needs
no migration. Mail delivery and real production sessions remain separate gates.

Production remains conditional on real hosting/TLS/encryption/backup and
release evidence. A clean package audit does not approve an arbitrary database
host, certify OS images, establish off-machine recovery or run hosted CI.
The older audit counts below are retained as history, not current findings.

## Dependency recheck, 2026-10-27

The opt-in OSV check was limited to package names/versions located in DMC's
own approved virtualenv. Seven package names initially had advisory records.
Security floors and installed updates removed findings for aiohttp, certifi,
filelock, OpenTelemetry API, Pillow and setuptools. OTel SDK/exporters were
synchronized and `pip check` passed. The repeat checked 153 installed packages
and still **failed** for ChromaDB 1.5.9 (four GHSA records plus PYSEC aliases).
No advisory exclusions or production bypass were added.

A separate clean PDF-worker environment passed its 15-package OSV scan after
upgrading inherited pip to 26.2.2. CI now scans both environments. That is not
a scan of the running Linux container, its base OS, Tesseract or ClamAV.

Zod's newly reported npm advisory was reproduced in frontend and auth;
targeted compatible lockfile updates were applied. Both subsequent npm audits
reported zero findings. This is dependency-audit evidence, not an image/OS
scan or an assurance that an already-running process has loaded the new code.

The new pinned security CI includes npm inventory/audit, scoped OSV and a
fail-closed CodeQL SARIF gate. It has **not run on GitHub** in this audit.
See [validation](engineering/VALIDATION.md) and
[remaining engineering gates](engineering/ROADMAP.md) before a release.

## Current data flow

- PDFs are stored as raw bytes outside the webroot. Extracted chunks and
  embeddings are stored in PostgreSQL/pgvector; analysis cases are stored in SQLite.
- Document excerpts are sent to the configured OpenAI or Anthropic provider
  when an AI analysis runs. Review that provider's contract, region, retention,
  training controls, and incident process before handling customer documents.
- Better Auth owns account/session records in PostgreSQL. The backend uses a
  server-verified user ID as the document workspace scope in production.
- n8n receives case metadata and an integration header. The local container
  disables completed-execution payload retention. n8n still writes in-flight
  state; completed state is physically pruned on a one-minute cycle with a
  zero-hour recovery buffer. Its execution/payload row counts were zero after
  a real webhook test on 2026-10-12. Backups are separate sensitive copies.
- Quality-score telemetry no longer stores new raw questions and answers or
  returns legacy question text through its admin API. Existing evaluation DB
  rows may still contain historic text and require an operator-reviewed purge.

## Controls implemented in the application

- The on-demand answer auditor now fails closed. Invalid or unavailable model
  verdicts are marked *unverifiable*, never *supported*. The case-file evidence
  gate already blocks automatic action when its structured audit fails.
- The audit endpoint accepts citations only when their exact page and text are
  present in the current user's indexed workspace evidence.
- Browser and n8n uploads share bounded reads, PDF signature/parser checks,
  page-count limits, and rejection of encrypted PDFs and embedded attachments.
  A failed extraction leaves the previous stored PDF untouched.
- A pure-ASGI ingress guard rejects untrusted mutation origins and missing
  CSRF protection headers before parsing. It bounds the actual request stream
  (including absent/spoofed Content-Length): 21 MiB multipart uploads and
  256 KiB other mutation bodies, a 60-second read timeout and eight concurrent
  body-bearing mutation requests per API process (held until the response,
  including any SSE stream, closes). Production proxies must still enforce
  their own size, connection and timeout limits.
- Both upload paths share shielded threadpool publication, with at most two
  upload pipelines per process. Extraction/OCR/embeddings run before mutation;
  quotas, index replacement, source commit and case invalidation are serialized
  per workspace with cross-process file locks. Exceptions restore the previous
  source, vectors and case rows. Scoped index/case/source reads use the same
  lock. An interrupted publication or failed rollback quarantines that workspace
  with HTTP 503 instead of serving inconsistent evidence. This is not a shared
  cross-store ACID transaction or a guarantee against power loss.
- A separate PDF safety worker is available and connected to the local backend.
  Uploads pass ClamAV scanning and visual PDF reconstruction before indexing.
  Greek/English OCR runs inside that worker because visual reconstruction
  removes original text objects. In production the worker is mandatory and
  fails closed. See `security/pdf_worker/README.md`.
  Each parser/OCR job has a separate subprocess, Linux resource limits,
  timeout, scrubbed environment, and bounded ephemeral output. Containers
  are not a substitute for an independently reviewed native-code sandbox.
- Deleting a document removes its stored source, PostgreSQL chunks, and all case
  payloads in that workspace. A failed source deletion returns an error rather
  than a false success. Successful re-upload invalidates old case files.
- Production startup requires authenticated workspaces, a shared auth secret,
  verified-email enforcement, specific HTTPS frontend origins and API hosts,
  and an n8n integration secret/URL. The auth service requires HTTPS origins
  and a configured email provider in production.
  Either `APP_ENV` or `NODE_ENV` set to production activates safeguards in
  both services. Auth image defaults are production; local compose overrides
  them explicitly. Production vector startup verifies PostgreSQL runtime-role
  restrictions, SQL migration hashes, model/dimension compatibility and TLS.
  The vulnerable Chroma runtime has been replaced; image OS findings still
  block release. See [current validation](engineering/VALIDATION.md).

## Release blockers requiring deployment work

1. Put the app, API, auth service, and n8n behind HTTPS. Restrict n8n's editor
   and webhook network access; run the [n8n security audit](https://docs.n8n.io/hosting/securing/security-audit/).
2. Pin and routinely update every image and dependency. The local n8n image,
   PDF worker base, ClamAV, and nginx gateway are pinned to verified local
   digests. The PostgreSQL compose image matches the existing local digest;
   the auth build's Node base matches the official Docker Hub digest and runs
   as a non-root user. The updated Node 22.23.4 auth candidate passed a local
   build, four offline runtime checks and an image scan with zero
   unknown/high/critical findings. Live login/email/DB integration is separate.
   Node lockfiles were updated and audited; a local backend SBOM and
   audit were generated under ignored `output/`. Python security floors are
   enforced and platform-specific hash locks are tested. Current backend/PDF
   candidate images have been built and scanned: unresolved Debian OS findings
   keep the image gate closed. Scheduled review is configured in CI but hosted
   execution, controlled releases and signature verification remain. Local
   compose is not a production specification. See
   [dependency/image evidence](engineering/DEPENDENCIES.md).
3. The API now enforces actual body limits *before* FastAPI parses uploads;
   enforce matching limits at the production reverse proxy as well. Deploy and
   test the isolated PDF worker, ClamAV signature
   refresh, and visual reconstruction in the actual hosting environment; the
   local backend is connected, but this is not a production deployment.
   A one-page live Greek/English OCR smoke test passed; verify representative
   documents, load/timeout behavior, and citation quality before release.
   The in-process checks alone are not a malware verdict. See the
   [OWASP file-upload guidance](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html).
4. Choose encrypted-at-rest storage for the PDF volume, PostgreSQL vectors, SQLite case
   store, PostgreSQL, n8n, and backups; control access to keys and rotate them.
   Confirm this with the actual hosting provider. Local BitLocker status was
   inaccessible without admin rights and remains unverified.
5. Approve and enforce `docs/DATA_RETENTION_AND_RECOVERY.md`. The document DELETE
   endpoint does **not** erase provider-side model logs, historic n8n execution
   records, legacy evaluation DB rows, backups, or an account's PostgreSQL data. Document the backup
   expiry window and a verified erasure procedure before promising complete
   deletion. Never silently delete historic n8n data without an operator audit.
6. Verify that backend and Better Auth use the same `BETTER_AUTH_SECRET` and
   `DATABASE_URL`, that email verification actually sends mail, and that
   unauthorized/cross-account access fails in the deployed environment.
7. Run a third-party security review and threat-model the document-to-LLM
   pipeline, especially malicious instructions inside PDFs, tenant isolation,
   n8n access, and webhook replay. Model-generated "supported" labels remain
   probabilistic aids, not proof of legal or factual correctness.

## Pre-release verification

- Run the full backend tests, frontend build, auth-service TypeScript check,
  dependency audits, `git diff --check`, and a secrets scan of the exact staged
  commit.
- Test upload/re-upload/deletion under disk errors and during concurrent reads;
  verify no stale case can be shown after deletion or replacement.
- Test sign-up, sign-in, verification, password reset, expiry, sign-out, and
  cross-user document access against the real deployed databases and domains.
- The active local n8n container was recreated with the same volume; inspect
  showed `none|none|false|false|true|24|1000` for the seven retention settings.
  On 2026-10-11, all six workflows had no per-workflow retention override,
  and execution/payload tables each had zero rows. This initial check is
  superseded by the completed local checks below.
- Verify restore from backup and the documented retention/deletion timeline.

## Completed local verification — 2026-10-12

- Backend: the initial **177 tests passed**, including subprocess/scanner failure,
  authenticated upload, evidence checks, tenant isolation, production startup
  configuration, and embedded-only vector-store regression checks. One
  non-failing Starlette/httpx deprecation warning remains.
- Frontend production build and auth-service TypeScript check passed. Both
  npm audits reported **zero known vulnerabilities** after dependency fixes.
- App, backend, auth, n8n, and PDF-worker health checks returned HTTP 200.
  The actual local backend has `AUTH_REQUIRED=true`; backend/auth share the
  same database and 32+ character secret, and backend/worker tokens match.
  An unauthenticated document-list request returned HTTP 401. Development
  listeners and Docker-published service ports are restricted to loopback.
  These are completed checks, not a claim of continuous uptime: a later
  check could not reach the Docker daemon after the interrupted turn.
- Python's installed-environment audit was reduced from 23 findings across
  six packages to five records across one package: ChromaDB 1.5.9. Two records
  duplicate the same advisory, leaving **four unique unresolved advisories**.
  `pip check` reports no broken requirements. No audit findings are hidden.
- n8n was updated to **2.42.7**, digest-pinned, preserving the volume and all
  six workflows. Global retention settings were inspected in the actual
  container. Both Documents Made Clear workflows explicitly disable saved payloads; unrelated
  workflows were preserved. Community packages, the public management API,
  remote templates, and diagnostics are disabled.
- A live missing-integration-header webhook returned **401**. A later
  read-only SQLite check found **zero execution and payload rows** after
  automatic physical pruning. This verifies the tested rejection path, not
  every possible crash, cancellation, or long-running workflow.
- The CLI security audit completed. It flags intentional HTTP/code nodes and
  credentials belonging to inactive workflows, including a separate FORGE
  project. Those unrelated resources were **not deleted**. The audit reported
  no unprotected-webhook or outdated-instance section at the time of checking.
- Consistent AES-256-GCM backups were created with n8n stopped. The latest
  pre-upgrade archive is `output/security-backups/n8n-volume-20261012T110040Z.tar.aesgcm`
  with its separate `.key.dpapi` file. An actual isolated-volume restore,
  SQLite integrity/foreign-key checks, and counts (six workflows, zero
  executions/payloads) passed. The temporary plaintext test volume was removed;
  encrypted archives were retained. This is local recovery, not offsite DR.
- Live PDF CDR/OCR and an in-memory EICAR scanner test passed. At-rest disk
  encryption remains unverified because Windows admin access is required.
- The app is **local only**. Real production HTTPS, encrypted cloud storage,
  mail verification, backup expiry/offsite recovery, and provider retention
  cannot be verified against a deployment that does not exist.

## Historical dependency risk: ChromaDB (runtime replaced)

The published advisories currently have no patched release:
[CVE-2026-45829](https://github.com/advisories/GHSA-f4j7-r4q5-qw2c),
[CVE-2026-45833](https://github.com/advisories/GHSA-36p7-vc44-83pf),
[CVE-2026-45830](https://github.com/advisories/GHSA-2wm9-hf6c-p5cr), and
[CVE-2026-45831](https://github.com/advisories/GHSA-xph7-9rjv-w5fr).
Their described attack paths target Chroma server collection/configuration
and authorization APIs. Documents Made Clear uses an embedded Rust-backed PersistentClient,
no public Chroma server, a fixed collection, explicit supplied embeddings,
and `embedding_function=None`. Its API never accepts Chroma collection or
embedding-function configuration. This is an applicability assessment and
mitigation, **not a patched dependency or independent proof of safety**.
Do not introduce HttpClient, expose a Chroma server, or accept user-defined
embedding functions. A production release requires a patched replacement or
a documented, independently reviewed risk decision.

## Follow-up remediation verification — 2026-10-12

The later independent review identified four application defects despite the
previous passing tests. They are now addressed with regression coverage:

1. Cookie-authenticated mutations cannot rely on CORS/SameSite alone: the
   ingress guard enforces trusted origins and the custom CSRF header.
2. PDF processing, including local parser validation, OCR, embeddings and
   publication, runs off the ASGI event loop with bounded concurrency. Blocking
   n8n agent adapters and document read/render handlers use FastAPI's threadpool.
3. Source commit and case-store failure tests verify rollback of the entire
   prior generation. Float32 vectors may undergo harmless re-normalization
   during restoration; regression comparisons use numerical tolerance.
   Failed rollback, leftover journals and temporary-source cleanup errors
   quarantine the workspace. See `DOCUMENT_PUBLICATION_RECOVERY.md`.
4. Better Auth uses one production decision for cookie policy, verification
   and server binding. Tests import the actual auth configuration using each
   production flag independently, including conflicting development flags.

The body-limit regression tests confirm that oversized declared, chunked and
misdeclared bodies never reach the downstream parser. Auth-service tests and
TypeScript checks, frontend build, npm audits and Python requirement consistency
were rerun: **200 backend tests and five auth-service tests passed**, frontend
build and TypeScript passed, both npm production audits had zero findings and
`pip check` reported no broken requirements. Git diff whitespace checks passed.
The fresh installed-Python audit again reports five records in ChromaDB 1.5.9
(four unique advisories, one duplicate), no patched versions and no other
affected installed package. Its report is Git-ignored at
`output/backend-pip-audit-remediation.json`. Comparing actual configured secret
values against Git candidate contents found no matches; this is not a scan of
all Git history or a substitute for scanning the exact future staged commit.
Do not treat these checks as an external penetration test.

The Docker engine is unavailable during this follow-up, so no fresh live
container/PDF-worker/n8n/auth-image build verification is claimed. Earlier live
checks above remain historical evidence only. Real production and at-rest
encryption verification still require a deployment/operator access.
The follow-up localhost health checks also found ports 5173, 8000, 3001, 5678
and 5186 unavailable. No running service was restarted or container recreated
in this follow-up. Backend/auth configuration values were compared without
printing secrets: authentication is enabled, database/secret values match,
and backend/worker tokens match.

The production Chroma-version allowlist described at this historical checkpoint
was superseded on 2026-10-27. The runtime now uses PostgreSQL/pgvector with
verified SQL migrations, a restricted role and forced RLS. The actual local
migration and isolated encrypted restore are recorded in
[secure storage](engineering/SECURE_STORAGE.md). Source files remain available
for recovery; Chroma is no longer an installed runtime dependency. This does
not resolve the separate production/image gates.
