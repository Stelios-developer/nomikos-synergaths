# Architecture

Documents Made Clear is a document-intelligence workspace. Its architecture keeps the user-facing browser, secure backend, document store and workflow orchestration separate.

## Repository layout

```text
auth-service/              Better Auth service and session API
backend/
  routers/                 FastAPI HTTP endpoints only
  services/                Domain logic: ingestion, retrieval, cases and workflow clients
  db/                      PostgreSQL/pgvector access and checksum-verified SQL migrations
  integration_tests/       Real SQL/RLS/transaction tests in disposable databases
  tests/                   Backend unit and API tests
frontend/
  src/api/                 Typed browser-to-backend client
  src/auth/                Better Auth browser client
  src/components/auth/     Sign-in and account-access components
  src/components/documents/ Upload, library, PDF and citation components
  src/components/intelligence/ Case workspace, guided flow and Ask experience
  src/components/agents/   Optional research and advisory interfaces
  src/components/analytics/ Evaluation and observability dashboards
  src/components/ui/       Small reusable visual primitives
  src/utils/               Rendering and formatting utilities
n8n/                       Versioned workflow definitions and local orchestration config
infra/vector/              Dedicated local PostgreSQL/pgvector service
docs/                      Architecture, authentication and testing guides
examples/test-documents/   Safe PDFs for local manual testing
scripts/                   Repeatable developer utilities
```

## Runtime boundaries

1. **Frontend** - React/Vite. It never holds LLM keys or n8n credentials.
2. **Auth service** - Better Auth owns account sessions and browser cookies.
3. **Backend** - FastAPI verifies the authenticated user, scopes all documents to that workspace and exposes the application API.
4. **Document storage** - PDFs are stored per workspace; chunks/embeddings use PostgreSQL/pgvector with explicit workspace access, forced RLS and an unprivileged API role. Case/metrics storage remains SQLite.
5. **n8n** - Orchestrates the persisted document-intelligence stages through secured backend endpoints.
6. **Analysis queue** - PostgreSQL persists intent, stage claims and transition metadata. An API-lifetime background dispatcher uses a separate restricted role for global claims; browser streams only observe progress. Uncertain delivery is reconciled without automatic resend. See [durable analysis](engineering/DURABLE_ANALYSIS.md).

## Backend conventions

- Add HTTP concerns in `backend/routers/`; keep routers thin.
- Put business logic in one focused module under `backend/services/`.
- All document access must receive and enforce the workspace/session identifier through `services/session_scope.py`.
- Add tests beside the affected domain under `backend/tests/`.
- Keep runtime files out of Git: database volumes, recovery archives, stored PDFs, SQLite data, logs and `.env` files are local only.

Migration and isolation evidence: [secure storage](engineering/SECURE_STORAGE.md).

## Frontend conventions

- Keep network calls in `frontend/src/api/client.ts`.
- Keep authentication access in `frontend/src/auth/`.
- Build product surfaces as components; keep formatting helpers in `frontend/src/utils/`.
- Do not place local credentials, uploaded documents or generated build output in `src/`.

## Test asset

`examples/test-documents/nexus-tax-compliance-test-case.pdf` is a deliberately safe, synthetic policy document. It contains deadlines, owners, risks, decisions and evidence references for testing every workspace tab.
