# Testing checklist

The dark-workspace browser regression suite and its isolated test-data
boundaries are documented in [FRONTEND_DESIGN.md](FRONTEND_DESIGN.md).

1. Upload a text PDF and confirm it appears in the document list.
2. Ask the Document Assistant a question and open a page citation.
3. Run the Supervisor and confirm its answer is grounded in the same documents.
4. Use the Research Agent for a compound question and confirm it shows sub-questions.
5. Run Expert Review only for a high-impact decision and inspect the moderator summary.
6. Use the Hallucination Auditor to check an answer's supporting evidence.
7. Upload a PDF through the application and confirm that **Documents Made Clear · Agent
   Orchestrator** runs the sequential case stages. Verify the final app result
   is either the verified pack or the human-review pack. Completed execution
   payloads are intentionally not retained in n8n; do not enable history just
   to make this test visible. Watch live execution or inspect app case state.

Automated verification:

```powershell
# Repository root; requires installed frontend/auth deps and backend virtualenv.
npm run check
npm test
npm run test:backend
```

Security controls, actual local verification, unresolved dependency advisories,
and production blockers are recorded in `SECURITY_RELEASE_GATE.md`. Backup
and isolated restore tooling is in `scripts/`; keep its output and DPAPI keys
out of Git. Run `npm audit` in both Node services and audit the actual Python
deployment environment; a passing build is not a vulnerability audit.

New regression coverage lives in `backend/tests/test_request_security.py` and
`backend/tests/test_document_publication.py`: untrusted origins, CSRF headers,
pre-parser stream limits, source/case commit failures, prior-generation rollback,
interrupted-publication quarantine, concurrent workspace reads and responsive
async work during heavy ingestion. Auth tests verify both production flags.
Chroma has been replaced by PostgreSQL/pgvector. Run `npm run test:integration`
for the real SQL/RLS boundary; ordinary backend tests use an in-memory test
double for vector storage. [Migration and restore evidence](engineering/SECURE_STORAGE.md).

## Isolated browser regression

Start a dedicated frontend in one terminal:

```powershell
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5197 --strictPort
```

In another terminal from the repository root:

```powershell
$env:UI_TEST_URL='http://127.0.0.1:5197'
$env:UI_TEST_ENGINE='chromium' # also firefox or webkit
$env:UI_TEST_BROWSER='chrome' # optional Chromium channel; omit for bundled browsers
npm run test:ui
```

Install the matching bundled browsers from `frontend/` with
`npx --no-install playwright install` if needed. When testing Firefox or
WebKit, unset `UI_TEST_BROWSER`. API/auth requests are intercepted with synthetic
fixtures; external requests are blocked. The command refuses the real local
workspace port 5173. Screenshots and accessibility JSON go to ignored
`output/engineering-ui/<engine>/`. Inspect axe `incomplete` entries manually.

The tests include real loopback webhook faults, but not live PostgreSQL/auth,
real n8n workflow execution, malware-engine validation or a model-quality
benchmark. Current results and limitations: [validation](engineering/VALIDATION.md).

Separate image checks are available after building the candidate tags:

```powershell
backend/.venv/Scripts/python.exe scripts/integration_pdf_image.py
backend/.venv/Scripts/python.exe scripts/integration_auth_image.py
```

These run synthetic input with no network or host volumes and a read-only
root. PDF tests perform real CDR/OCR; auth tests cover startup/HTTP/configuration
and unavailable-DB failure. They do not replace live ClamAV or authenticated
session integration. `npm run test:integration` separately verifies PostgreSQL
with a disposable database.
