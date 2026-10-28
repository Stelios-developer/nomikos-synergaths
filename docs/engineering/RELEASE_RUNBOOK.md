# Local-to-production release runbook

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
