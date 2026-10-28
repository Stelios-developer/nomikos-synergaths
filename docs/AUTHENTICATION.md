# Documents Made Clear accounts and secure deployment

Documents Made Clear uses Better Auth for account creation and session management, PostgreSQL
for its account/session records, and FastAPI for every protected document/RAG
operation. The browser never receives an API key or stores a bearer token.

## Security model

1. Better Auth writes an HttpOnly, `Secure` (in production), `SameSite=Lax`
   session cookie after sign-up/sign-in.
2. FastAPI verifies the cookie HMAC with the shared server-side Better Auth
   secret, then looks up the opaque token in Better Auth's PostgreSQL `session`
   table. Expired sessions and unverified accounts are rejected before an
   upload, query, source page, or analysis can run.
3. The verified `userId` becomes the workspace scope used by PostgreSQL/pgvector, source
   PDF storage and stored case files. Client-provided `X-Session-ID` values are
   ignored whenever `AUTH_REQUIRED=true`.
4. The browser uses `credentials: include`; it never embeds `VITE_API_KEY`, a
   database password or an LLM key.

## Local development

1. Copy `auth-service/.env.example` to `auth-service/.env`.
2. Generate a new `BETTER_AUTH_SECRET` with at least 32 random characters.
3. Start PostgreSQL:

   ```powershell
   cd auth-service
   docker compose up -d postgres
   npm install
   npm run db:migrate
   npm run dev
   ```

4. In `backend/.env`, set:

   ```dotenv
   APP_ENV=development
   AUTH_REQUIRED=true
   DATABASE_URL=postgresql://nexus:nexus-local-only@localhost:5432/nexus_auth
   BETTER_AUTH_SECRET=the-exact-same-secret-used-by-auth-service
   AUTH_COOKIE_PREFIX=nexus
   REQUIRE_VERIFIED_EMAIL=false
   ALLOWED_ORIGINS=http://localhost:5173
   ALLOWED_HOSTS=localhost,127.0.0.1
   ```

5. Start FastAPI on port 8000 and the Vite frontend on port 5173. Vite routes
   `/api/auth/*` to Better Auth on port 3001 and routes all other `/api/*`
   requests to FastAPI.

Set `REQUIRE_EMAIL_VERIFICATION=true` only after configuring a real Resend
account (`RESEND_API_KEY` and `EMAIL_FROM`) in `auth-service/.env`.

## Production checklist

- Use HTTPS for the app, API and auth service.
- Set `APP_ENV=production` and `NODE_ENV=production` in Better Auth. Either
  flag enables secure cookies and mandatory verification, even if the other
  flag is accidentally set to development. The Docker image defaults to
  production; localhost compose explicitly overrides both to development.
- Keep them on one parent domain, e.g. `app.example.com`, `api.example.com`,
  `auth.example.com`; set `COOKIE_DOMAIN=.example.com` in the auth service.
- Set `BETTER_AUTH_URL=https://auth.example.com`,
  `APP_ORIGIN=https://app.example.com`, `VITE_AUTH_BASE_URL=https://auth.example.com`,
  and `VITE_API_BASE_URL=https://api.example.com`.
- Set `APP_ENV=production`, `AUTH_REQUIRED=true`,
  `REQUIRE_VERIFIED_EMAIL=true`, a non-wildcard `ALLOWED_ORIGINS`, and exact
  `ALLOWED_HOSTS` in FastAPI. FastAPI refuses to start in production without
  accounts, PostgreSQL or an exact CORS origin.
- Set a high-entropy `BETTER_AUTH_SECRET`, `N8N_WEBHOOK_API_KEY`,
  `ADMIN_API_KEY`, and LLM provider keys through the host's secret manager;
  never place them in a Vite `VITE_*` variable or commit them.
- Configure `N8N_ORCHESTRATOR_URL` and use the exact same
  `BETTER_AUTH_SECRET` and `DATABASE_URL` in FastAPI and Better Auth.
- Configure Resend (or replace `sendEmail` with your approved provider) before
  enabling email verification or password reset.
- Run `npm audit`, pin/update dependencies, and deploy PostgreSQL with daily
  backups and restricted network access.
- Restrict CORS to the exact frontend origins; do not use `*` with cookies.
- All browser-facing mutations require `X-CSRF-Protection: nexus-v1` and reject
  any supplied Origin not in `ALLOWED_ORIGINS`, before processing the body.
  The frontend API client sends this header automatically; authenticated
  scripts must send it too. It is a preflight-enforcing header, not a secret
  or authentication credential. The n8n integration continues to require its
  separate server-held key and workspace scope.
- Use the dedicated `X-Admin-API-Key` only in an internal admin client for
  telemetry/evaluation endpoints. It must not be put in the public frontend.
- Complete the [security release gate](SECURITY_RELEASE_GATE.md) before
  handling real customer or regulated documents.

## Request limits and spend protection

Better Auth stores cross-instance rate-limit counters in PostgreSQL and limits
sign-in to 5 attempts/15 minutes, sign-up to 5/hour, and reset requests to
3/hour. FastAPI separately rate-limits uploads and AI-intensive routes, checks
PDF signature/page count/size, and limits each workspace's document count and
raw PDF storage. Set the limits in `backend/.env` to match the plan you sell.

## What must be migrated before public launch

Anonymous documents already uploaded under old browser `X-Session-ID` values
do not automatically belong to newly created accounts. Treat them as local demo
data or migrate them with a one-time, audited administrator process that maps
each legacy scope to the verified account owner. Do not guess ownership.
