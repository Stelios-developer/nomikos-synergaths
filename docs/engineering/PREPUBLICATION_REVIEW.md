# Prepublication review — 2026-10-28

Decision: **do not commit/publish the current staged snapshot or deploy it to
production yet**. The working tree passes the local checks below. The index
contains an older, incomplete implementation. GitHub publication and production
service release are separate gates.

## Verified in this review

- Root source/architecture/publication checks, Python static correctness,
  frontend lint/build, auth typecheck, actionlint and both Git whitespace checks.
- 269 backend regressions; 39 disposable-PostgreSQL tests; 30 repository/security
  tests, 29 frontend unit tests and six auth unit tests.
- Real Better Auth signed-cookie/backend validation, wrong-password/tampering
  rejection and sign-out revocation in a fresh disposable database. It was removed;
  the real account database was not changed. No email or AI inference call.
- Exact backend image import/runtime check and 53 source-file hashes passed.
  All three candidate image IDs still match their clean 2026-10-28 scan reports.
  These bindings were rechecked; the advisory DB was not downloaded again in this
  review. These are not scans of every supporting container or the Windows host.
- Index secret/path checker: 166 entries, zero findings. Working-tree candidate
  checker: 250 files before this report was added, zero findings.
- Reachable Git history: 15 commits, 410 text blobs checked, one binary skipped;
  zero recognizable token/current configured-secret matches and zero prohibited
  historical paths. This is pattern/known-value scanning, not an exhaustive
  entropy scanner, unreachable-object audit or proof that all former secrets are
  absent. No secret values were printed/exported.
- The earlier same-day browser evidence remains 133 assertions and twelve axe
  scans per engine (Chromium/Firefox/WebKit). Browsers were not rerun for this
  documentation-only review; incomplete accessibility checks need manual review.

## Gate 1 — make the Git snapshot coherent

1. Preserve and review the existing 157 staged changes, including 18 staged
   deletions. Necessary implementation files are still untracked/not staged:
   root package scripts, backend Dockerfile/vector store/dispatcher/router,
   security workflow and integration tools, among others.
2. Replace stale staged versions with their reviewed working-tree versions.
   Both staged Node lockfiles still select Better Auth **1.6.26**; the tested
   working tree selects **1.7.14**. Staged backend requirements still include
   ChromaDB. A commit now would not represent the tested replacement runtime.
3. Stage selectively, then recheck the exact index for secrets, runtime data,
   import closure, intentional deletions and lockfile/source consistency. Verify
   that a clean checkout of that commit passes the full checks. Do not force-add
   ignored environment files, PDFs, backups, logs or database volumes.
4. Resolve the default-branch policy: local branch is `master`, while the CI
   push/pull-request filters target `main`. Either use the intended `main` flow
   or deliberately update filters. Do not assume a push to `master` ran CI.
5. Publish to the intended GitHub repository, run the hosted CI/security/CodeQL
   jobs, and require their actual check names before merging/releasing. Configure
   branch protection and secret scanning with least-privileged workflow tokens.

No staging, branch rename, commit, push or GitHub policy change was performed
in this review. The scan cannot approve an index that is changed afterward.

## Gate 2 — prepare the actual production deployment

1. **Choose hosting and align manifests.** `backend/render.yaml` currently uses
   native Python rather than the tested Wolfi Docker image and does not declare
   `ANALYSIS_DISPATCH_ENABLED` or `ANALYSIS_DISPATCH_DATABASE_URL`. It is an
   incomplete deployment template, not a release manifest. Use the exact tested
   image/digest, configure the restricted dispatcher role, readiness and graceful
   shutdown, then verify the host's streaming/timeout behavior.
2. **Persistent storage and topology.** Keep PDFs, case SQLite, publication locks
   and operational state on persistent storage. Prepare an explicit embedding
   model/cache before serving users: the current model is loaded/downloaded on
   first use and is not bundled into the candidate image. A read-only deployment
   needs an appropriate writable/prepopulated cache. Do not scale to independent
   API disks: current SQLite/lock coordination requires the same filesystem.
   Validate disk capacity and per-account/global limits on the chosen host.
3. **Domains and authentication.** Configure actual HTTPS app/API/auth origins,
   secure cookie scope, exact CORS/host allowlists, trusted proxy handling and
   frontend URLs. Set production flags, mandatory authentication/email
   verification, a shared high-entropy auth secret and matching auth DB settings
   through the host secret manager. Never put server secrets in Vite variables.
   Exercise verification/reset email, expiry and sign-out on real HTTPS origins.
4. **Service boundaries.** Keep database administration, n8n editor and PDF
   worker private. Apply verified database TLS, separate owner/runtime/dispatcher
   roles, network restrictions and independent integration secrets. The local
   n8n/auth compose files intentionally contain development settings and must
   not be copied unchanged into production. Use only the DMC workflow/config;
   the local n8n instance also contains unrelated project resources.
5. **Encryption, recovery and retention.** Verify storage encryption and key
   ownership on the actual provider. Establish coordinated PDF/case/vector/auth/
   n8n backups, encrypt off-machine copies, define expiry/RPO/RTO and restore to
   an isolated environment. Current DPAPI-bound local recovery backups are not
   offsite disaster recovery. Verify deletion and old-generation/backup handling;
   review the configured AI provider's data-processing/retention controls.
6. **Release and operational acceptance.** Execute the full cross-service staging
   path with synthetic inputs, including tenant isolation, upload rejection,
   dispatcher restart/cancel/uncertain work, deletion and rollback. This can use a
   fake provider without paid inference; model-quality evaluation remains
   deferred by the user's choice. Promote signed immutable image identities with
   SBOM/provenance verification; exercise health/error/disk/queue alerts and
   rollback before allowing customer documents.

## Live localhost snapshot

In this review the PDF gateway/scanner and n8n returned 200. The API (8000),
auth (3002) and DMC frontend (5174) were stopped/unavailable. No service was
restarted as an incidental health check. Isolated backend/SQL/auth tests passed,
but this snapshot is not a fresh live end-to-end application run or any form of
production evidence.

Ignored evidence is in `output/engineering-audit/prepublication-*.json` and
`prepublication-*.txt`. Current implementation evidence and remaining engineering
limits are in [validation](VALIDATION.md), [durable analysis](DURABLE_ANALYSIS.md)
and [acceptance gates](ROADMAP.md).
