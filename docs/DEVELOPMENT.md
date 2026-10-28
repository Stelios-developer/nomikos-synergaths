# Development workflow

## First-time setup

1. Copy `backend/.env.example` to `backend/.env` and provide the required local values.
2. Copy `auth-service/.env.example` to `auth-service/.env` and use the same `BETTER_AUTH_SECRET` in the backend.
3. Create `n8n/.env` from the documented local values before starting n8n.

Never commit real `.env` files or credentials.

Use Python 3.12 and Node 22 for the supported CI profiles. From the repository
root, create the virtualenv and install the reviewed Windows wheel locks:

```powershell
py -3.12 -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install --upgrade pip==26.2.2
backend/.venv/Scripts/python.exe -m pip install --require-hashes --only-binary=:all: -r backend/requirements-win-py312.lock -r backend/requirements-test.lock
npm --prefix frontend ci
npm --prefix auth-service ci
```

Linux deployment uses `backend/requirements-linux-py312.lock`; see
[dependency profiles](engineering/DEPENDENCIES.md). Do not install Chroma or
point the application at an old embedded store as a fallback.

Create `infra/vector/.env` from its example with two distinct random passwords,
set the matching runtime-only `VECTOR_DATABASE_URL` in `backend/.env`, then:

```powershell
docker compose -f infra/vector/compose.yml --env-file infra/vector/.env up -d --wait
backend/.venv/Scripts/python.exe scripts/setup_vector_database.py
npm run test:integration
```

Schema setup is an explicit owner operation; the API never applies DDL.
The setup helper also generates a third distinct password in the ignored vector
environment for `dmc_dispatcher`, verifies restricted privileges and grants only
the fixed queue functions. Do not reuse the owner/runtime password. Configure
`ANALYSIS_DISPATCH_DATABASE_URL` with this role and enable
`ANALYSIS_DISPATCH_ENABLED=true` in the backend environment before running analysis.
Never print or commit the generated connection string. Applied migration 003
must remain byte-identical; make future changes through new migrations.
The integration command creates/removes a new disposable database, not the
active document database. Auth PostgreSQL, email configuration and PDF-worker
setup are separate boundaries documented in [authentication](AUTHENTICATION.md)
and [the PDF worker](../security/pdf_worker/README.md).

## Run locally

```powershell
# Terminal 1 - backend
cd backend
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000

# Terminal 2 - frontend
cd frontend
npm run dev

# Terminal 3 - n8n
cd n8n
docker compose --env-file .env up -d

# Terminal 4 - Better Auth (after its database is configured)
cd auth-service
npm run start
```

## Validate before a pull request

After installing auth-service dependencies and starting the dedicated DMC vector
fixture, `python scripts/integration_auth_sessions.py` creates/drops a uniquely
named temporary database to check real Better Auth signed cookies and backend
revocation. It uses synthetic accounts, no email/provider calls, and never
targets the active auth database. CI runs this alongside the SQL integration.

### Coexistence with another local project

Do not stop another application's listener to reclaim a default port. For this
machine DMC uses frontend `http://127.0.0.1:5174`, auth on port 3002 and API on
8000; Shopbrain keeps 5173/3001. Set `DMC_AUTH_PROXY_TARGET=http://127.0.0.1:3002`
in ignored `frontend/.env.local` to override Vite's default auth proxy. In the
ignored auth environment set `AUTH_PORT=3002`, `BETTER_AUTH_URL` to that auth
origin and `APP_ORIGIN` to the frontend origin. Add the frontend origin to the
backend's `ALLOWED_ORIGINS` and start Vite with `--port 5174 --strictPort`.
Restart the affected services after environment changes. Production uses its
separate reviewed URLs; development proxy configuration does not configure TLS.

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q --basetemp .\.pytest-tmp

cd ..\frontend
npm run build

cd ..
git diff --check
git status
```

## Generate the sample test document

```powershell
python scripts\generate_nexus_test_case.py
```

Upload `examples/test-documents/nexus-tax-compliance-test-case.pdf` to exercise the full document workflow, including Timeline and Decision center.

The script requires `reportlab`; install it in your local developer environment if it is not already available.
