# Kubernetes: local storage inventory and prerequisites

This is a proposed isolated demo topology, not Kubernetes manifests, a deployed
cluster or evidence of production readiness. Do not connect it to the existing
local stores or use real PDFs, credentials, email or AI providers in a drill.

| Store | Current code/configuration | Boundary and local test implication |
| --- | --- | --- |
| Source PDFs | `PDF_STORAGE_DIR`, default `backend/storage/pdfs` relative to the source; workspace-scoped paths. | Persist a synthetic-only volume for the single API instance. A replacement pod must find the same PDF and source-page data. Deleting a pod is not a backup. |
| Case state | `DOCUMENT_CASE_DB_PATH`, default `./document_cases.db`; SQLite and workspace locks. | One API replica and one local filesystem shared with its locks. Do not assume shared SQLite on multiple nodes is safe. |
| Evaluation / observability | `EVAL_DB_PATH` and `OBSERVABILITY_DB_PATH`, default local SQLite files. | Separate named writable test paths; define whether each store participates in a drill. Their persistence is not implied by vector backup. |
| Vectors and analysis jobs | `VECTOR_DATABASE_URL`; PostgreSQL/pgvector, separate owner/runtime/dispatcher roles and migrations. | Use a new disposable database and credentials. Run a versioned migration job before API readiness; test existing schema and version checks. A single test PVC is not HA. |
| Auth state | Better Auth PostgreSQL in `auth-service/docker-compose.yml`. | Use a separate synthetic-only database and credentials. Auth and vector databases are distinct recovery domains. |
| Workflow state | n8n local compose mounts `n8n_data` at `/home/node/.n8n`. | A future local demo needs an isolated test workflow/state volume, not the existing n8n instance. Avoid real webhooks and providers. |
| PDF/OCR scratch | PDF worker uses bounded temporary storage and a separate scanner. | Provide an explicitly bounded writable scratch path; test cleanup, scanner failure and OCR timeout. Container isolation is not VM-grade protection. |

Case/PDF/vector publication spans stores: an individual volume snapshot is not
automatically a consistent backup. The current durable-analysis documentation
requires the case store and workspace locks to share a filesystem and does not
support independent API disks. A first test must remain **one API replica**;
multi-node or multi-replica coordination requires a new design and fault tests.

Before an isolated AK deployment: establish a clean source/artifact baseline;
create a new local cluster and namespace with an ownership marker; prepare only
synthetic fixtures and temporary secrets; define private services, restrictive
RBAC, probes and network policy; and verify actual CNI enforcement. Prove PDF,
case, auth, vector/job and workflow consistency across pod replacement and a
separate coordinated restore to fresh storage. Record what was and was not
restored, checksums, image IDs and cleanup. These tests are not yet evidenced by
this inventory, and external backups, real TLS, independent security review and
provider/data decisions remain release gates.
