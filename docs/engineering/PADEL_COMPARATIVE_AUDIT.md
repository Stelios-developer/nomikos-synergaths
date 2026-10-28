# Engineering comparison and transfer audit

Review date: 2026-10-27. Source: the owner's local Padel Club Management
Platform checkout. Target: NOMIKOS SYNERGATHS (DMC).

This is the historical initial-transfer review. Later remediation replaced the
Chroma runtime, resolved the Python image OS gate and activated durable background
dispatch with safe uncertain-job controls. Use the current
[validation record](VALIDATION.md) and [remaining gates](ROADMAP.md) for status.

## Result and evidence boundary

Padel's strongest advantage is the connection between implementation,
failure scenarios, executable checks and retained release evidence. Its Java,
Keycloak and Kubernetes stack alone does not establish that advantage.

DMC now adopts the useful transport, lifecycle, concurrency, contract,
resilience, repository and security-gate patterns described below. It still
does **not** have evidence equivalent to Padel's signed-image release chain,
multi-service integration suite or real AI evaluation program. Neither this
review nor a passing build certifies production safety or product superiority.

The read-only inventory covers **553 source/configuration/documentation
files**: 174 backend, 49 web, 77 scripts, 61 infrastructure, 19 evaluation,
149 documentation and 24 root/CI files. It excludes dependency trees,
runtime stores, private environment files and generated build output. The
local ignored `output/engineering-audit/padel-source-inventory.json` records
paths, byte counts and SHA-256 hashes. Hashing all candidates is an inventory,
**not a claim that 241,652 lines received individual manual review**.

Manual inspection focused on the implementation and evidence sources cited
in the 59-point matrix below. Padel was not modified. Its services, deployments, tests and
release workflows were not run by this audit. Counts and releases recorded
in its documents are historical source evidence, not newly reproduced results.

Status meanings: **added** = implemented here and locally tested; **existing**
= retained DMC control; **partial** = useful control with a stated limitation;
**next** = engineering work with acceptance criteria in the
[roadmap](ROADMAP.md); **different** = domain/stack choice intentionally kept.

## Architecture, data correctness and security

| Strength found in Padel | Specific source evidence in Padel | DMC adaptation and status |
| --- | --- | --- |
| Domain boundaries are explained | `docs/ARCHITECTURE.md`, `docs/CODE-MAP.md` | **Added:** machine-checked storage/domain-to-HTTP boundary and browser transport-to-UI boundary; architecture decision records the scope. |
| One reproducible developer entry point | root `package.json`, `scripts/quality/checks.mjs` | **Added:** root `check`, `test`, `test:backend`, `test:ui`, `audit:python`; fixed argument arrays, explicit working directories and nonzero failures. |
| Import graph checks catch architectural erosion | `scripts/quality/paths.mjs`, repository-quality documentation | **Added:** local imports, cycles including type dependencies, Node/operator imports in browser, Python AST syntax, local Markdown targets. Static conventions do not prove every dynamic import. |
| Shared request rules prevent API drift | contract-test modules, HTTP contract YAML | **Added:** common question/history contracts across assistant, research, supervisor and panel. Only user/assistant history roles; bounded counts and sizes; reject unknown fields. Consumer/provider integration generation remains **next**. |
| RFC problem responses carry usable diagnostics | common `ApiErrors.java` | **Added:** RFC 9457 API errors, stable codes, safe validation locations/types, request IDs, no raw validation payloads. Existing SSE retains its separate error-event contract. |
| Ownership is enforced server-side | common `SecurityConfiguration.java`, assistant security tests | **Existing:** Better Auth verified session determines workspace, integration keys stay server-side, audit evidence is reloaded from that workspace. **Different:** cookie authentication keeps CSRF protection; copying Padel's bearer-only CSRF exception would be wrong. |
| JWT issuer/audience and role validation | common security configuration and gateway tests | **Different:** retain Better Auth opaque signed cookies and database session checks. Team roles, SSO and delegated access require a separate authorization design, not a framework replacement. |
| Input validation is a security boundary | `AvailabilityRequest.java`, `SearchTime.java`, `SearchDuration.java` | **Added:** trim/validate questions and document selectors, reject system/developer history injection, cap history at ten turns. Existing upload limits remain. |
| Database constraints enforce domain invariants | booking `V4__confirmed_booking_exclusion.sql`, `V6__player_schedule_exclusion.sql` | **Added:** atomic compare-and-swap on persisted case revision; stale stage workers get 409 rather than overwriting newer results or resurrecting a deleted case. **Next:** storage migration discipline and database-backed publication generations. |
| Migrations fail visibly on inconsistent old data | PostgreSQL booking migrations | **Existing:** interrupted document publication is quarantined and prior generation restored on failure. **Next:** versioned case schema migrations and compatibility/restore tests. No silent destructive migration was introduced. |
| One transaction owns domain change and event intent | common `Idempotency.java`, `events/OutboxRepository.java` | **Next:** durable analysis jobs, request fingerprints, admission quotas and resumable delivery. The new revision check is concurrency protection, not idempotency or exactly-once model execution. |
| At-least-once delivery is explicit | common `events/OutboxPublisher.java` | **Next:** persisted dispatch attempts, bounded redelivery and deduplication before changing any model/task side effect. DMC does not need RabbitMQ merely to imitate the source. |
| Infrastructure choices fit actual needs | `compose.yml`, `infra/k8s/`, Terraform scaffolding | **Different:** keep the current deployable components while their boundaries mature. Microservice count and Kubernetes are not quality metrics. |
| Security posture is stated honestly | `SECURITY.md`, security-maintenance documentation | **Added:** disclosure instructions without a fictional contact or certification. **Existing:** production rejects insecure authentication configuration and unapproved Chroma versions. |
| Sensitive files cannot enter the release casually | security policy and repository checks | **Added:** runtime/tool/cloud-state/key patterns, working-tree candidate checks and staged-index checks. Recognizable token detection is useful, not an exhaustive secret-history audit. |

## Browser behavior and user experience

| Strength found in Padel | Specific source evidence in Padel | DMC adaptation and status |
| --- | --- | --- |
| One transport covers fetch and body duration | `web/api.js` | **Added:** shared request budget includes JSON/blob/SSE reads; cookie and CSRF policy centralized; timeout and request diagnostics retained. |
| Ambiguous writes are never silently retried | `web/api.js`, `web/idempotency.js` | **Added:** mutation timeout/network loss warns that it may already have completed; zero automatic mutation retries. Durable server-side replay remains **next**. |
| Failed loading is not a valid empty state | `web/resources.js` | **Added:** idle/loading/success/error resource state; initial library failure has an explicit retry; failed refresh retains a labeled previous snapshot and disables actions against it. |
| Last good state survives temporary errors | `web/resources.js`, frontend-resilience documentation | **Added:** memory-only snapshots with refresh timestamp; no document payload cache added to browser storage. |
| Session changes invalidate protected resources | `web/resources.js` | **Added:** 401/403/404 clear resource data; account-keyed application remount; abort and generation guards reject late responses from a cleared session. |
| Old requests cannot overwrite new views | request/resource generation handling | **Added:** document intelligence and chat cancel outstanding requests and ignore obsolete stream/audit completion after document change or unmount. |
| Pending operations have bounded lifecycle | per-form guards and request signals | **Added:** abort propagation through transport and response consumption; effect cleanup; no late `finally` toggle from a prior document. Cancelling the browser is not proof the remote workflow stopped. |
| Malformed responses do not become success | typed API errors and backend contracts | **Added:** SSE requires a valid completion event, bounds unfinished buffers, supports CRLF/multiline/split UTF-8, rejects malformed/truncated/error streams. |
| Render faults are recoverable | frontend resilience conventions | **Added:** application error boundary offers a safe reload path without exposing stack traces. It is distinct from network and API error handling. |
| Browser coverage spans engines and widths | `web/playwright.config.js` | **Added:** Chromium/Chrome, Firefox and WebKit suite; desktop plus 320/390/768 widths. Every backend/auth route uses synthetic fixtures. This is not real login/DB/CDR integration. |
| Accessibility is executable | `web/browser-tests/accessibility.spec.js` | **Added:** axe WCAG 2 A/AA, 2.1/2.2 scans of eight tabs plus authentication; keyboard focus/dialog escape regressions. Automated zero violations does not replace manual assistive-technology testing. |
| Keyboard navigation and focused dialogs matter | browser accessibility tests | **Existing + checked:** settings/source focus containment, Escape, workspace search navigation and fixed header. |
| Test evidence is reproducible and private | browser report handling | **Added:** per-engine synthetic screenshots and accessibility JSON; short-lived CI artifacts; real workspace port 5173 is refused by the root UI test command. |

## Reliability, operations and observability

| Strength found in Padel | Specific source evidence in Padel | DMC adaptation and status |
| --- | --- | --- |
| Concurrency is bounded before dependency work | common resilience configuration, `AssistantResilience.java` | **Added:** nonblocking n8n bulkhead, capacity two per API process; no waiting queue presented as guaranteed work. Distributed and per-workspace quotas remain **next**. |
| Failing dependencies stop accumulating work | Resilience4j configuration and tests | **Added:** three counted failures open a 30-second circuit; one half-open probe; late successes cannot close a newer open generation; permits are released on exceptions. |
| Expected authorization errors do not trip a dependency circuit | backend resilience tests | **Added:** only unavailable/timeout/429/5xx failures count; normal upstream 4xx do not open the circuit. |
| Recovery is tested through real sockets | `BookingResilienceIT.java`, `AssistantResilienceIT.java`, Toxiproxy fixture | **Added:** loopback HTTP tests for 503/open/recovery, 401, timeout/permit release, redirect and oversized response. **Next:** isolated PostgreSQL/n8n/PDF-worker container fault tests. Loopback is not equivalent to Toxiproxy deployment tests. |
| Credentials stay within their intended hop | explicit API/security boundaries | **Added:** n8n webhook redirects are refused; integration credentials are not forwarded to redirect destinations; response body is capped at 1 MiB. |
| Request budgets are end-to-end | `AssistantRequestBudget.java` | **Partial:** browser total budgets and n8n observation/socket limits exist. The n8n socket timeout is not a universal deadline for all downstream LLM operations; durable cancellation/deadline propagation remains **next**. |
| Readiness differs from process liveness | health/configuration and infrastructure probes | **Added:** `/livez` process probe and `/readyz` bounded auth DB check. Existing `/health` stays compatible. Readiness scope explicitly excludes LLM, n8n, CDR and vector-store end-to-end health. |
| Metrics use stable, low-cardinality labels | Prometheus configuration and alert rules | **Added:** API metrics use route templates rather than PDF names/query paths; generic HTTP span names. **Existing:** OTel/token/cost metrics. Prometheus SLO rules and alert delivery tests remain **next**. |
| Operational recovery is executable | `scripts/operations/backup.mjs`, operations docs | **Existing:** encrypted local n8n backup and isolated restore drill tooling. **Next:** coordinated auth/case/PDF/vector backup, consistency checks, RPO/RTO measurement and retention deletion proof. |
| Failure and recovery evidence survive the test | resilience report scripts | **Partial:** isolated test output/screenshots and security summaries now exist. Durable release manifests tying artifacts to one source revision remain **next**. |
| Capacity/performance claims have a workload | performance and resilience documentation | **Next:** reproducible corpus sizes, ingestion/query concurrency, p50/p95/p99 and memory/disk ceilings. Browser timing and unit duration are not a capacity benchmark. |

## AI trust and evaluation

| Strength found in Padel | Specific source evidence in Padel | DMC adaptation and status |
| --- | --- | --- |
| Retrieval admits only approved source facts | `KnowledgeCatalog.java`, `KnowledgeService.java` | **Existing:** server-owned workspace evidence, fixed local embedding model and audit re-resolution. **Next:** versioned document/embedding provenance and hash-bound retrieval manifests. |
| Model output cannot invent authoritative citations | assistant service and `evals/assertions.mjs` | **Existing:** case citation IDs come from the stored case, invalid evidence fails closed; audit endpoint verifies exact indexed text/page. More schema-negative cases remain part of release regression work. |
| Live business data comes from authoritative APIs | `AvailabilityService.java`, assistant assertions | **Different:** DMC analyzes documents rather than live court inventory. Future task/calendar integrations must revalidate current state and require explicit human approval. |
| Unknown and unavailable are valid outcomes | assistant service/evaluation assertions | **Existing:** malformed/unavailable audit never becomes supported; human-review pack withholds unsupported actions. UI empty-count semantics still need explicit extraction-status coverage for every stage. |
| Critical failures cannot hide behind averages | `evals/assertions.mjs`, `docs/AI-EVALUATION.md` | **Next:** zero-tolerance tenant leakage/citation forgery gates, per-category answer/retrieval thresholds and completeness requirements; no aggregate score alone. |
| Datasets and knowledge are versioned and hashed | evaluation manifests and knowledge catalog | **Next:** separate curated development/evaluation datasets, source/model/prompt versions and immutable first-use report. Existing mocked backend tests are regression coverage, not a model benchmark. |
| Holdout reuse is described honestly | `docs/AI-EVALUATION.md` | **Next:** label reused evaluation sets as regression, freeze a new independent set for major changes and document reviewer limitations. |
| Retrieval quality is measured separately | real embedding/pgvector evaluation runner | **Next:** Recall@k, MRR, no-evidence rate and citation correctness on actual DMC corpora, with a baseline and no real customer documents. |
| Evaluations protect real data and costs | scoped synthetic fixtures, cleanup journal, no hosted inference policy | **Existing:** current tests use isolated data and mocked model responses. **Next:** explicit provider/cost budget and cleanup journal for any real model suite; never silently send another project's corpus. |

## Delivery, maintenance and reviewer experience

| Strength found in Padel | Specific source evidence in Padel | DMC adaptation and status |
| --- | --- | --- |
| CI actions are immutable | `.github/workflows/ci.yml`, `security.yml`, toolchain pins | **Added:** official action commit pins, credential-free checkout, read-only job permissions and bounded job durations. |
| Superseded CI runs stop consuming resources | workflow concurrency policy | **Added:** pull-request/ref concurrency cancellation. Destructive jobs are not part of this workflow. |
| Different test layers are labeled honestly | CI, testing and release evidence docs | **Added:** separate repository, frontend, auth, backend, browser and security gates. Browser fixture success is not auth integration success. |
| Security tools fail closed on malformed output | `scripts/security/policy.mjs` | **Added:** validated OSV batch completeness, SARIF shape/rules/invocations/scores, reject missing/paginated/incomplete results, no silent vulnerability exclusions. |
| Security reports avoid leaking source snippets | sanitization policy | **Added:** only sanitized CodeQL gate summaries uploaded; source-bearing SARIF remains local to the runner. Python reports contain approved package names/versions, not documents or credentials. |
| Dependency inventory supports investigation | Syft/SBOM and supply-chain documentation | **Added:** npm CycloneDX inventory job and project-only Python OSV audit. These are dependency inventories, not signed container attestations. |
| Dependency updates are a maintained workflow | Dependabot configuration | **Added:** scoped weekly Actions/npm/pip/Docker PR configuration. Hosted execution and required checks still need GitHub-side verification. |
| Images are scanned, signed and digest-bound | `docs/SUPPLY-CHAIN.md`, release verification scripts | **Next:** build once, scan/test the exact digest, sign and verify provenance/SBOM, immutable release manifest and rollback evidence. No unsigned deployment is described as verified. |
| Branch rules match the actual gates | repository-quality evidence | **Next:** publish the reviewed change and configure required checks/review policy for the real GitHub repository. Local YAML does not change hosted protection. |
| Reviewer guidance is concrete | contribution rules and PR template | **Added:** test commands, migration/failure/ownership/privacy/rollback prompts, architecture decisions and this transfer ledger. |
| Documentation distinguishes scaffolding from production | deployment/operations docs | **Existing + reinforced:** production remains blocked for unapproved vector storage; hosting/provider encryption/retention claims require deployment evidence. |

## Initial-transfer files and historical proof

The later Chroma replacement, SQL tests, durable job coordination, budgets,
locks and candidate image verification supersede the initial status below.
See [current validation](VALIDATION.md), [storage](SECURE_STORAGE.md),
[analysis coordination](DURABLE_ANALYSIS.md) and [images](DEPENDENCIES.md).

- Transport and lifecycle: `frontend/src/api/http.ts`, `resource.ts`, shared
  types, document list, chat, intelligence panel, auth session remount and
  application error boundary.
- Backend: shared request contracts, safe problems, revision compare-and-swap,
  dependency guard, bounded/no-redirect webhook and bounded health probes.
- Tooling: root dispatcher, architecture/publication checks, strict security
  parsers, pinned CI, dependency jobs and review templates.
- Local checks after the transfer: 237 backend tests; 25 repository/security
  parser tests; 28 frontend tests; 6 auth tests; browser results are recorded
  in the [validation report](VALIDATION.md). No hosted workflow is claimed.

Python security audit initially identified seven affected installed package
names. Updates removed findings for aiohttp, certifi, filelock, OpenTelemetry
API, Pillow and setuptools, with synchronized OTel exporters and a clean
`pip check`. ChromaDB 1.5.9 remains blocked: four GHSA records plus their PYSEC
aliases, not eight independently counted vulnerabilities. Zod was updated in
both Node lockfiles after the new npm advisory was reproduced. See the
[release gate](../SECURITY_RELEASE_GATE.md) for the remaining production limits.

A separate clean PDF-worker virtualenv audit checked 15 packages and passed
after updating its old inherited pip. CI scans backend and worker environments
separately. This does not scan the active Linux container or its OS packages.

The existing staged changes were preserved. New transfer work is not staged,
committed, published or deployed by this audit. Review working-tree and index
diffs separately before creating a release.
