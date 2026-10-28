# Project layout

- `frontend/`: user interface, frontend tests and web deployment configuration.
- `backend/`: API, business services, database migrations and backend tests.
- `auth-service/`: authentication service and its tests.
- `n8n/`: workflow definitions and local n8n configuration.
- `security/pdf_worker/`: isolated PDF validation, scanning and OCR service.
- `infra/`: supporting infrastructure configuration.
- `docs/`: architecture, security, development and release documentation.
- `scripts/database/`: database setup, migration, integration and recovery tools.
- `scripts/integration/`: isolated image and PDF service checks.
- `scripts/recovery/`: local encrypted n8n backup and restore-drill tools.
- `scripts/examples/`: test-document generators.
- `scripts/quality/`, `scripts/security/`, `scripts/tests/`: repository quality,
  security audit tools and their tests. `scripts/repository.mjs` is the npm
  command dispatcher; the remaining root-level scripts are shared entry points.
- `.github/`: GitHub configuration and workflows.

Root-level `package.json`, Git configuration, README, license and security and
contribution documents are intentionally at the repository root: tools and
hosting platforms discover them there. Service-level configuration and entry
points likewise remain at their expected locations. Ignored `tmp/` and `output/`
contain local temporary data and sensitive evidence, not release artifacts.
Never commit environment files, database volumes or backup archives.
