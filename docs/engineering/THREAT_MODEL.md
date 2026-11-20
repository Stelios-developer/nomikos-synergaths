# Document intelligence trust boundaries

Scope: repository revision `0df7249` plus local changes, 2026-11-07. This is a
development threat model, not a security assessment or evidence that a deployed
system is safe. The actual infrastructure, AI provider and domains are not selected.

## Data flows and boundaries

| Boundary | Data and authentication | Failure and limits |
| --- | --- | --- |
| Browser → auth/API | Email/password go to Better Auth; browser sends a signed session cookie to API. Production API checks signature, live database session, expiry and verified email. Mutation origin/CSRF and size guards are separate. | Invalid/expired session is rejected; unavailable auth database results in 503. TLS, cookie attributes and proxy trust require deployed verification. |
| API → PDF worker → scanner | Untrusted PDF crosses a private service boundary using `X-PDF-Security-Token`; scanner and visual reconstruction precede indexing when configured and are mandatory in production. | Worker/scanner error fails closed. Default input limit 20 MiB and 250 pages; sanitize client timeout 90s, OCR client timeout 600s. Worker subprocess limits and scanner signatures must be verified on the deployed host. |
| API → storage | Source files and SQLite cases are local storage; chunks/vectors/jobs use workspace-scoped PostgreSQL, restricted roles and RLS; authentication also uses PostgreSQL. | Store operations are not a shared atomic transaction. Workspace locking/quarantine reduce inconsistent publication; restore must preserve the relationship across stores. RLS with shared credentials is not cryptographic isolation. |
| API ↔ n8n | Workflow receives case metadata and an integration header; callbacks invoke API stages and operate in the specified workspace. | A transport timeout after dispatch may be uncertain. Do not blindly replay; inspect stored job/attempt. Service networking and secrets must be verified in deployment. Orchestrator upper timeout is 900s. |
| API → model provider | Relevant document excerpts, questions and claims are sent to the configured model provider for analysis or audit. Provider receives content even if local telemetry is redacted. | Provider failure or invalid audit output is unverifiable. An LLM can wrongly approve a claim or obey malicious document instructions. Provider location, retention and contract remain unverified. |
| Backups and operators | PDFs, cases, jobs, auth, vectors and n8n may be copied into backup artifacts. Keys confer recovery access. | Local encrypted backup is not offsite recovery. A coordinated snapshot, independent key recovery, deletion replay and restore drill remain open. |

## Threats and controls to verify

- **Cross-workspace access:** derive workspace from validated session, scope reads
  and citations to that workspace, and revalidate stored evidence. Test two real
  signed sessions and stale/replaced documents on the deployed stack.
- **Hostile PDF:** enforce ingress and worker limits; reject encrypted files,
  embedded content and bad signatures; fail closed on scanner or worker failure.
  Resource exhaustion and parser vulnerabilities still require sandbox and patch review.
- **Prompt injection:** document text and model output are untrusted; keep tool
  privileges minimal and avoid autonomous external actions. Prompt instructions
  alone do not prove isolation; evaluate adversarial fixtures and tool boundaries.
- **Incorrect evidence:** a model's positive audit is not independent proof.
  All positive model verdicts now require human source review in both auditors;
  historical verified cases are downgraded on read without rewriting storage.
  There is no implemented human attestation workflow and AI output can still be wrong.
- **Disclosure:** avoid raw source content and secrets in operational logs; audit
  provider, n8n in-flight data, backups and any historical telemetry separately.
- **Loss or inconsistency:** rehearse coordinated restore on disposable storage;
  never assume a local snapshot or one store's restore recovers the entire case.

Controls and tests are subject to the deployment gates in
`docs/SECURITY_RELEASE_GATE.md` and `docs/engineering/RELEASE_RUNBOOK.md`.
