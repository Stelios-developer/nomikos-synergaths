# Remaining engineering acceptance gates

This is the work remaining after the [comparison and initial transfer](PADEL_COMPARATIVE_AUDIT.md),
not a list of capabilities already delivered. Order follows data safety and
recovery dependencies. Do not replace a failed gate with a waiver to make CI green.

| Priority | Work | Completion evidence |
| --- | --- | --- |
| Done locally | Replace vulnerable vector-store runtime | PostgreSQL/pgvector active; forced RLS and role restrictions; 46 owned chunks hash-verified; 18 unowned chunks preserved for recovery; actual disposable-database restore drill; zero known Python package findings. [Evidence](SECURE_STORAGE.md). |
| Done locally; external release evidence pending | Python image OS remediation | Wolfi Python 3.12 images, hash locks, no runtime shell/pip/apk; zero reported findings in final full-severity scans; exact backend source and English/Greek CDR/OCR checks. Signed release/hosted CI still pending. [Evidence](DEPENDENCIES.md). |
| P0 | Real deployment trust boundaries | HTTPS, same-site cookie/origin rules, verification/reset email, shared auth secret, database TLS/credentials and private service networks tested on the chosen host. Local files are not production evidence. |
| P0 | Backup and deletion across stores | Coordinated PostgreSQL/cases/PDF/vector snapshots; encrypted off-machine backup; measured restore/RPO/RTO; deletion/retention behavior including old generations, in-flight n8n state and backups. Verify provider encryption and key management. |
| Done locally; hosted resilience pending | Background analysis and uncertain jobs | API-lifetime background consumer, global/workspace limits, restricted dispatcher role, forced RLS, persistent stage claims, lost-ack reconciliation, safe cancellation/closure UI, exact attempt result reads and restart tests. No browser required; no blind replay. [Limits](DURABLE_ANALYSIS.md). |
| Done locally; remote cancellation limited | Deadline and cancellation propagation | Hard supervised transport deadline/shutdown, nested callback/provider budgets, cancellation/commit serialization, zero SDK retries and independent bounded SSE observers tested. Accepted remote requests cannot be undone; full hosted crash/load tests remain. |
| P1 | Isolated service integration suite | Dedicated disposable PostgreSQL, n8n and hardened PDF worker; real Better Auth cookies; two users; foreign document/case/citation denial; workflow failure/recovery; CDR/malware/OCR limits. Record cleanup and never target user databases. |
| P1 | Versioned storage migrations | Forward/restore tests from representative old case/publication schemas; concurrent writes; migration rejects inconsistent state visibly; explicit operator rollback. |
| P1, deferred by user | Real AI evaluation | User declined paid provider tests. No inference charges were incurred for evaluation. Real retrieval/grounding/model-quality measurements still require a separately approved corpus and run; mock/offline smoke tests are not substitutes. |
| P1 | Signed release chain | Build exact images once; scan image OS/language dependencies; generate SBOM/provenance; sign and verify digests; run tests on those digests; immutable manifest and rollback drill. GitHub CI/CodeQL must actually execute, not only parse. |
| P1 | Hosted repository rules | Required checks match actual job names; review policy, protected default branch, no bypass by ordinary workflows; secret-history scan before publication. Requires actual repository access/configuration. |
| P2 | Observability and SLOs | Stable route metrics, complete-stream duration and provider cost; bounded labels; privacy redaction tests; error-budget/queue/latency alerts exercised through a receiver; dashboards tied to a reproducible test run. Current API timing primarily covers response setup. |
| P2 | Performance and capacity | Fixed corpus/page/OCR sizes, documented hardware, concurrency and sustained load; p50/p95/p99, memory, disk and recovery limits; no claims extrapolated from unit or browser tests. |
| P2 | Accessible product sign-off | Manual keyboard/screen-reader/zoom/contrast review across actual PDF states, not just synthetic happy paths; retain automated three-engine checks and report axe incomplete results for manual review. |
| P2 | Maintainability of large UI modules | Split by state ownership and product feature after invariants are covered; component interaction tests; avoid cosmetic folder moves that obscure behavior. |
| P2 | Team authorization and audit trail | Explicit roles/grants/revocation model; immutable event metadata without document payloads; scoped export/deletion rights and revocation tests. Do not introduce SSO before defining the policy. |

No Kubernetes, RabbitMQ, Terraform, framework migration or UI rewrite is a
prerequisite by itself. Adopt infrastructure when a measured need and its
operational ownership justify it. The completion criterion is reproducible
behavior and recovery evidence.
