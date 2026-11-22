# Local-to-production release runbook

`python scripts/quality/verify_release_bundle.py --bundle <directory>
--manifest <manifest.json>` checks local evidence-file hashes and declared check
statuses. The JSON contains `commit` (full Git hash), `artifacts` entries
`{"path":"report.json","sha256":"<64 hex>"}`, and `checks` entries
`{"id":"browser","status":"passed","artifact":"report.json"}`.
It refuses unsafe paths, symlinks, hash mismatches and incomplete declared
checks. It does **not** verify signatures, image provenance, report content or
the truth of declared statuses. It is not a production release gate; use only
synthetic reports without secrets.

At commit `0124cf3`, offline verification passed with 332 backend tests and
one Linux DPAPI skip ([report](evidence/offline-0124cf3-2026-11-22.json));
the separate synthetic Windows DPAPI check passed at that same commit
([report](evidence/windows-backup-0124cf3-2026-11-22.json)). These checks
do not verify a coordinated restore, off-machine backup or signed provenance.

For synthetic PostgreSQL/pgvector, RLS, durable jobs and real Better Auth
signed-cookie integration, run
`python scripts/quality/verify_vector_isolated.py` from a clean committed
checkout. It uses pre-existing local backend and pgvector images, creates a
uniquely named internal Docker network and disposable database, and records
the exact source revision, local image IDs, skips and cleanup in ignored
`output/verification/`. Two synthetic users are created in the disposable
database; wrong passwords are rejected and backend verification checks each
signed cookie, ignores a forged workspace header, rejects tampering,
enforces distinct workspace-scoped vector results, and rejects an expired
session and a separate signed-out session. Cookies remain in memory rather than test logs. Email verification
is disabled in this synthetic-only scenario. It does not connect to the
existing vector database or load its credentials. A failed setup, test, timeout or unconfirmed cleanup is a
failure, not a passing release. A separately network-isolated PDF worker checks
synthetic CDR/OCR, invalid requests and fail-closed behaviour with the scanner
unavailable; its OCR timeout is mocked. A second isolated worker uses a real
ClamAV container with bundled signatures to check clean content, a harmless
in-memory EICAR sample, CDR and malformed PDF rejection. It neither updates nor
proves the freshness of signatures. The test reuses local dependencies and does not cover browser-to-auth HTTP deployment,
verified email, end-to-end PDF upload, n8n, provider calls, Kubernetes or
production readiness.

`python scripts/quality/verify_n8n_isolated.py` imports a test copy of the
actual workflow into disposable local n8n and exercises the backend transport
against a synthetic mock on an internal Docker network. It checks missing-header
rejection, stage order and the human-review branch. Integration destinations
are rewritten to the mock and branch-only test markers are added. It does not
exercise real backend endpoints, PDF upload, a provider or a browser, and does
not read existing n8n state. It removes only resources with its unique label.
The fixture refuses workflow nodes outside its explicit five-type allowlist and
nodes with configured credentials. On 22 November 2026 the isolated workflow
test passed at commit `acc7054`; the [report](evidence/n8n-acc7054-2026-11-22.json)
records image IDs, workflow hashes and cleanup. This is not a full application
integration test and does not prove image provenance.

At commit `f6d2aeb`, both the human-review and verified audit branches passed
against the synthetic mock in a new isolated run
([report](evidence/n8n-f6d2aeb-2026-11-22.json)). A separate run at the same
commit passed the cookie, scanner and 39 PostgreSQL integration tests
([report](evidence/vector-f6d2aeb-2026-11-22.json)). These were separate
fixtures: they do not constitute one integrated upload-to-workflow test.

At commit `f403185`, offline verification passed with 332 backend tests and
one Windows DPAPI skip inside Linux ([report](evidence/offline-f403185-2026-11-22.json)).
The separate synthetic Windows DPAPI and encrypted-backup check passed on the
same commit ([report](evidence/windows-backup-f403185-2026-11-22.json)). This
does not prove off-machine recovery or a coordinated restore of all stores.

After the blind-packet and archive-path validation changes, the offline suite
again passed at commit `ff8a246`, with 332 backend tests and one Linux DPAPI
skip ([report](evidence/offline-ff8a246-2026-11-22.json)). The separate Windows
synthetic DPAPI check passed at that same commit
([report](evidence/windows-backup-ff8a246-2026-11-22.json)). The limitations
above still apply; these checks are not a coordinated restore drill.

Legacy encrypted-backup verification and its restore drill share an inventory
validator that rejects duplicate names or manifest keys, links, unsafe paths,
missing members and checksum mismatches. This is an archive-integrity guard,
not a coordinated restore of all stores or evidence of off-machine recovery.
On Windows, `python scripts/quality/verify_windows_backup.py` additionally
runs synthetic encrypted-backup and current-user DPAPI checks that the Linux
container skips. The report is written under ignored `output/verification/`;
the test uses host dependencies and does not prove recovery on another machine.

Status: **not approved for production**. This runbook records the order and
proof required to release without treating a local test as hosted evidence.
It does not create infrastructure, enable billable services, or authorize paid
AI calls. The owner has not selected a provider or domain.

## 1. Establish the deployment inventory

Record the selected account and region, frontend/API/auth URLs, service owners,
and the locations of the PDF volume, case SQLite database, vector/job database,
auth database, n8n state and backups in a private operator record. Identify
which components share physical storage. Use one API instance until cross-host
publication locks and SQLite writes are explicitly supported and tested. Never
commit credentials, database URLs containing credentials or customer documents.

## 2. Build, test and bind the actual artifacts

For a local synthetic checkpoint, `python scripts/quality/verify_offline.py`
requires a clean committed tree and an existing local backend image plus host
pytest packages. It archives that commit, runs evaluation and guard unit tests,
and runs backend unit tests with the source mounted read-only in a container
with networking disabled. It records image ID, lockfile hashes, results and
reported skips under ignored `output/verification/`. This reuses dependencies;
it is not a clean lockfile build, a scanned/signed artifact, a Kubernetes test,
or a release approval. It retains the archived source and logs in that ignored
directory; treat the directory according to the repository's data policy.

Build from a reviewed clean source revision. Record the source revision and
immutable image digests for API, auth, PDF worker and every supporting image.
Scan those exact digests with current advisories, generate an SBOM, record scanner
versions, sign artifacts and independently verify signatures and provenance.
Test the exact digest to be deployed; rebuilding the Dockerfile later is not the
same artifact. Preserve the previously approved digest and configuration for
rollback. Do not claim a signed chain until each step is independently verified.

The current `backend/render.yaml` is a template: it builds from a Dockerfile,
not a verified previously signed digest. Its disk requires a paid plan. Do not
activate it without choosing a provider and reviewing cost. Before startup,
verify that UID 10001 can write the mounted volume and that PDFs, SQLite and
publication locks persist over restarts. Pre-populate the correct embedding model
and verify a restart without a download, matching the model and dimensions in
the vector database. Test model provenance and storage capacity. A missing
cache or wrong permissions must block release, not silently create a new index.

## 3. Configure and verify trust boundaries

Use actual HTTPS domains and least-privilege secret storage. Check API and auth
share the correct auth secret and database, while the vector runtime and
background dispatcher use their own limited PostgreSQL roles and verified TLS.
Verify exact allowed hosts/origins, secure cookies and CSRF; send real verification
and reset email to a controlled test account. Keep n8n administration, PDF worker
and databases private. Test rejected direct access and invalid integration tokens.
Production checks must examine effective live configuration, not merely manifests.
Do not record secret values in logs or the release evidence.

## 4. Recovery and deletion

Choose a recovery point objective, recovery time objective and retention window
with the owner. Coordinate a consistent snapshot across PDFs, case SQLite,
vector/job PostgreSQL, auth PostgreSQL and n8n: establish a quiescence procedure,
include all stores and record the snapshot boundary. Encrypt before transfer to
a separately administered offsite destination with separately recoverable keys;
verify provider encryption and region. A Windows DPAPI-bound local key alone
cannot recover after loss of the machine/profile. Test restoration into an
isolated environment without overwriting live data, compare source/vector/case
links and account/session integrity, and measure RPO/RTO. Test the deletion-ledger
replay and expiry of old backup generations before promising deletion. The
current local independent backup drills are not a coordinated offsite backup.

## 5. Staging acceptance and rollback

Use synthetic PDFs and a fake AI provider; no paid inference. Test two accounts,
upload, evidence isolation, blocked unsafe PDFs, job completion, restart,
cancel, uncertain-result reconciliation, document deletion and restore. Test
real service networking, mail delivery, monitoring and alert delivery using the
chosen provider. Simulate a failed release and restore the approved image and
compatible data; record the result and migration compatibility. Verify resource
limits and PDF scanner signature refresh. Keep the release closed if any test is
missing, or if production configuration, encryption, backup or rollback has
not been verified. A mock AI test does not establish answer quality.

## Evidence checklist

- [ ] Reviewed source revision and exact artifact digests recorded and verified.
- [ ] Provider, DNS, TLS, email and network boundaries tested on live staging.
- [ ] Non-root mounted storage and offline model readiness verified.
- [ ] Real provider encryption and isolated offsite recovery verified.
- [ ] Retention, erasure and deletion-ledger replay approved and exercised.
- [ ] Synthetic end-to-end, operational alerts and rollback exercised.
- [ ] Hosted CI and required branch checks demonstrably enforced, or a separately
      documented and approved release control exists; budget limits alone are
      not proof of CI success.
