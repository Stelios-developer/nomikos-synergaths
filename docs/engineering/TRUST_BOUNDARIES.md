# Trust boundaries and failure assumptions

This is an architectural inventory for the local system, not an independent
security assessment or authorization to process real documents. It reflects the
code and referenced engineering documents at the time of review; deployment
configuration must be checked separately.

| Boundary | Data and authority | Failure and open verification |
| --- | --- | --- |
| Browser → Better Auth → API | Browser sends an HttpOnly session cookie; the API verifies it and derives a workspace server-side. Client-selected workspace headers are not authority when auth is required. See [authentication](../AUTHENTICATION.md). | Reject expired, revoked or unverified sessions. HTTPS, cookie scope, CSRF/origin behavior, proxy headers and cross-user access need tests against the exact deployed configuration. |
| API → PDF worker / scanner | An authenticated service boundary processes untrusted uploaded PDF bytes. The worker scans, reconstructs and scans again; its subprocess has bounded resources. See [worker design](../../security/pdf_worker/README.md). | Scanner errors, unsupported inputs and timeouts fail closed. Native parser isolation is not VM-grade; verified signatures, real ingress limits and private routing are deployment gates. OCR can change facts and citations. |
| API → PostgreSQL / pgvector | Verified workspace scope selects document chunks, vectors and metadata. Runtime RLS is forced and the application role is restricted. The dispatcher has separate limited queue functions. See [storage](SECURE_STORAGE.md) and [durable analysis](DURABLE_ANALYSIS.md). | Shared trusted API credentials can select another workspace context after compromise; RLS is defense in depth, not cryptographic tenant isolation. TLS verification, secret rotation and negative cross-user integration tests require deployment-specific evidence. |
| API → filesystem / SQLite | Source PDFs, case state, evaluation and observability stores are separate from vector and queue data. Workspace locks must match the case-store filesystem. | A single SQLite/file layout does not establish multi-host consistency. Independent copies, encryption, retention, coordinated backup and restoration across *all* stores remain separate gates. |
| API ↔ n8n | Orchestration uses backend stage endpoints and persisted job identifiers. The API-lifetime dispatcher maintains durable job state. | A dispatch with an unknown result is reconciled; it is not blindly resent. Callback auth, timeouts, cancellation, late callbacks and replay behavior must be checked against the actual configured workflow. |
| API → model provider | Excerpts, prompts and generated claims can leave the system when a provider is configured. Provider credentials stay server-side. SDK retries are disabled and calls use bounded timeouts. | No paid calls are authorized by this inventory. Provider access, retention and data transfer require an explicit decision. Citations and a positive auditor verdict do not establish that a claim is supported. |
| Logs / backups → operator | Operational metadata can reveal identifiers; encrypted local backups may still contain sensitive document contents. | Do not publish credentials, contents or backup keys. A same-machine restore and a DPAPI-bound key do not establish offsite recovery. Review logging, retention and operator access for the actual deployment. |

## Trust and release decisions

Document text is untrusted input. It cannot grant permissions, select another
workspace or authorize tool actions; test prompt injection independently of
ordinary retrieval quality. Treat browser input, uploaded PDF, OCR text, n8n
callbacks, provider output and logs as separate trust boundaries.

For each release record the exact commit, configuration, synthetic fixtures,
commands, results and skips. Run two-user ownership, session, CSRF, worker
failure and restore tests in an isolated environment. A separate human review
must assess authorization, document handling and retention before real usage.
The presence of this document alone is not proof any of those checks passed.

For structured-case audit, a claim without a known citation now leaves the whole batch unverifiable without a model call. The prompt includes only evidence cited by at least one claim. Batch members still share the union of cited excerpts, so this is not per-claim isolation or proof of entailment; positive verdicts still require human review. These checks are local code and regression tests, not independent evaluation or an authorization to send documents to a provider.

The structured-case guard also refuses ambiguous duplicate IDs, empty excerpts and missing or invalid source-page numbers before invoking a model. This is structural validation only: a nonempty excerpt and valid page number do not prove that the source supports a claim.

The batch prompt now maps each claim to its cited IDs and instructs the model to treat excerpts as untrusted. All cited excerpts are still visible in the same batch, so prompt instructions do not enforce isolation or guarantee resistance to injected text. No model-based verdict constitutes verified source support.

The structured-case audit now refuses inputs beyond 30 claims, 48 evidence entries, 1,500 characters per claim or 700 per excerpt before invoking a model; invalid or oversized input remains unverifiable for human review. These bounds limit the submitted material but do not establish relevance or factual correctness.
