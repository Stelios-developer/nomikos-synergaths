# Verified vector storage replacement

The application now uses PostgreSQL 17 with pgvector 0.8.7. ChromaDB is no
longer an API dependency or runtime import. The one-time legacy reader is an
offline operator script, not a service or a production fallback.

## Actual local migration evidence

On 2026-10-27 the source held 64 chunks. **46 chunks across four existing
workspaces were transferred**, preserving IDs, text, metadata and float32
embeddings. Every workspace's row count and canonical SHA-256 digest matched.
Eighteen older chunks had no owner; they were preserved in recovery data and
were not silently assigned to an account or exposed in the new database.

Before activation, a streaming AES-256-GCM backup was written without a
plaintext archive on disk. Frame order and EOF are authenticated; its key is
wrapped by Windows current-user DPAPI. The written backup was decrypted and
all 13 archive-member checksums were verified. A second actual restore drill
loaded the 46 owned chunks into a fresh disposable PostgreSQL database and
verified three restored SQLite databases. It did not replace the active
database or extract over live PDFs. The original legacy files were retained.

Ignored evidence: `output/engineering-audit/vector-migration.json`,
`storage-restore.json` and `output/security-backups/`. These contain recovery
material and must stay out of Git. DPAPI binds this local recovery key to
this Windows user; this is not an off-machine disaster-recovery solution.

The old package was uninstalled from the API virtualenv. The repeat OSV check
of 159 installed packages reported zero findings. A separate clean,
hash-locked build environment checked 134 packages and also reported zero
findings. These are package audits, not certification or an OS-image scan.

## Isolation and integrity

- Every get/add/delete/query requires an explicit server-verified workspace.
  Arbitrary metadata filters and dynamically selected embedding functions
  are absent from the API storage contract.
- SQL is parameterized. Row-level security is enabled and forced, and both
  reads and writes use a transaction-local workspace context. Returning a
  pooled connection cannot retain that context.
- The runtime role cannot own/change tables, bypass RLS, truncate data,
  create schemas/roles/databases or change embedding configuration.
- Batches commit atomically. Duplicate IDs or invalid embeddings roll back
  the batch. IDs are unique within a workspace, not globally across accounts.
- Schema migrations have SHA-256 records and a transaction/advisory lock.
  API startup does not run DDL. A schema/manifest mismatch fails closed.
- Exact cosine search preserves tenant-filtered recall; no approximate index
  is enabled without a measured recall/performance decision.
- Production additionally requires `sslmode=verify-full` and a reviewed
  database host. Local Docker configuration is explicitly local only.

The SQL role protects against accidental unscoped application queries. An
attacker who compromises the trusted API process or its runtime credentials
may choose another transaction context; RLS is defense in depth, not a claim
that one shared database credential cryptographically separates tenants.

## Reproduce verification

Create distinct random values in `infra/vector/.env` using its example, then:

```powershell
docker compose -f infra/vector/compose.yml --env-file infra/vector/.env up -d --wait
backend/.venv/Scripts/python.exe scripts/setup_vector_database.py
npm run test:integration
```

The integration runner creates and removes only a fresh `dmc_it_<UUID>`
database. It tests real RLS, query ranking, SQL injection values, transaction
rollback, thread/pool isolation, role permissions, model drift and persistence.

For the exact backup recorded in the ignored migration report:

```powershell
backend/.venv/Scripts/python.exe scripts/restore_drill_storage.py output/security-backups/<exact-backup>.tar.aesgcm
```

The restore runner validates the archive before creating a fresh
`dmc_restore_<UUID>` database, and removes that exact test database afterward.

## Remaining deployment evidence

Provider encryption at rest, off-machine key custody/backups, full coordinated
auth/n8n/storage restore, retention policy, real TLS and operating-system/image
scans still need deployment evidence. These are distinct from the resolved
Chroma runtime dependency. See the [acceptance gates](ROADMAP.md).
