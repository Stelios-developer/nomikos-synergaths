import os
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

load_dotenv()

from routers import advisory_panel, analysis, audit, documents, evaluation, n8n, observability, query, research, supervisor, upload
from services.observability import (
    configure_logging, configure_tracing, get_request_usage_summary, logger,
    record_request_metrics, request_id_var, traced_span,
    usage_accumulator_var,
)
from services.authentication import AUTH_REQUIRED, close_auth_pool, require_authenticated_user, start_auth_pool
from services.security import limiter, require_admin_api_key, require_api_key
from services.request_security import RequestSecurityMiddleware
from services.workspace_lock import WorkspaceUnavailable
from services.runtime import is_production
from services.problems import correlation_id, install_problem_handlers, problem_response
from services.case_store import CaseWriteConflict
from db.vector_store import VectorStoreUnavailable
from psycopg import OperationalError
from psycopg_pool import PoolTimeout
from services.n8n_orchestrator import N8nOrchestratorError
from services.analysis_dispatcher import start_dispatcher,stop_dispatcher,DispatcherUnavailable

configure_logging()
configure_tracing()


def _validate_production_configuration() -> None:
    if not is_production():
        return
    if not AUTH_REQUIRED:
        raise RuntimeError("AUTH_REQUIRED=true is mandatory in production.")
    if not os.getenv("DATABASE_URL"):
        raise RuntimeError("DATABASE_URL is mandatory in production.")
    if len(os.getenv("BETTER_AUTH_SECRET", "")) < 32:
        raise RuntimeError("A shared BETTER_AUTH_SECRET of at least 32 characters is mandatory in production.")
    if os.getenv("REQUIRE_VERIFIED_EMAIL", "true").lower() != "true":
        raise RuntimeError("REQUIRE_VERIFIED_EMAIL=true is mandatory in production.")
    origins = [value.strip() for value in os.getenv("ALLOWED_ORIGINS", "").split(",") if value.strip()]
    if not origins or any(not value.startswith("https://") or "*" in value or "example.com" in value for value in origins):
        raise RuntimeError("ALLOWED_ORIGINS must list real HTTPS frontend origins in production.")
    hosts = [value.strip() for value in os.getenv("ALLOWED_HOSTS", "").split(",") if value.strip()]
    if not hosts or any(value in {"*", "localhost", "127.0.0.1"} or "example.com" in value for value in hosts):
        raise RuntimeError("ALLOWED_HOSTS must list real API hostnames in production.")
    if not os.getenv("N8N_WEBHOOK_API_KEY"):
        raise RuntimeError("N8N_WEBHOOK_API_KEY is mandatory in production.")
    if not os.getenv("N8N_ORCHESTRATOR_URL"):
        raise RuntimeError("N8N_ORCHESTRATOR_URL is mandatory in production.")
    if not os.getenv("PDF_SECURITY_URL") or len(os.getenv("PDF_SECURITY_TOKEN", "")) < 32:
        raise RuntimeError("A private PDF_SECURITY_URL and 32+ character PDF_SECURITY_TOKEN are mandatory in production.")
    from db.vector_store import validate_production_vector_store
    validate_production_vector_store()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _validate_production_configuration()
    await start_auth_pool(app)
    try:
        start_dispatcher()
        yield
    finally:
        stop_dispatcher()
        await close_auth_pool(app)
        from db.vector_store import close_vector_store
        close_vector_store()

app = FastAPI(title="NOMIKOS SYNERGATHS API", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
install_problem_handlers(app)


@app.exception_handler(DispatcherUnavailable)
async def dispatcher_failure(_request,exc):
    return problem_response(503,'Background analysis is unavailable. Check saved progress.',code='ANALYSIS_DISPATCH_UNAVAILABLE',retryable=True)


@app.exception_handler(N8nOrchestratorError)
async def analysis_failure(_request, exc):
    detail = ('The analysis may still be running. Check saved progress before starting again.'
              if exc.uncertain else 'The analysis could not complete. Check service configuration and saved progress.')
    return problem_response(503, detail,
                            code='ANALYSIS_UNCERTAIN' if exc.uncertain else 'ANALYSIS_FAILED',
                            retryable=exc.retryable and not exc.uncertain, uncertain=exc.uncertain)


@app.exception_handler(VectorStoreUnavailable)
@app.exception_handler(OperationalError)
@app.exception_handler(PoolTimeout)
async def document_database_unavailable(_request, _exc):
    return problem_response(503, 'Document storage is temporarily unavailable.', headers={'Retry-After': '3'})

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(WorkspaceUnavailable)
async def workspace_unavailable(request, exc):
    return problem_response(503, "This workspace is temporarily unavailable. Please retry later.", headers={"Retry-After": "3"})


@app.exception_handler(CaseWriteConflict)
async def case_write_conflict(_request, _exc):
    return problem_response(409, "The case changed. Reload it before retrying this stage.", code="CASE_CHANGED")

allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173")
allowed_origins = [origin.strip() for origin in allowed_origins_env.split(",") if origin.strip()]
app.add_middleware(RequestSecurityMiddleware, allowed_origins=allowed_origins, auth_required=AUTH_REQUIRED)
# CORS wraps the guard so trusted cross-origin clients can read 403/413
# responses. Neither CORS nor the guard consumes multipart input downstream.
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Request-ID", "X-API-Key", "X-Admin-API-Key", "X-CSRF-Protection"],
    expose_headers=["X-Request-ID", "Retry-After"],
)
allowed_hosts = [host.strip() for host in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",") if host.strip()]
if not is_production() and "testserver" not in allowed_hosts:
    allowed_hosts.append("testserver")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    request_id = correlation_id(request.headers.get("X-Request-ID"))
    request_id_token = request_id_var.set(request_id)
    usage_token = usage_accumulator_var.set([])
    start = time.perf_counter()
    response = None
    try:
        with traced_span(f"HTTP {request.method}", http_method=request.method):
            response = await call_next(request)
        return response
    except Exception as exc:
        # Keep unexpected implementation details and document contents off the wire.
        logger.error("request_failed", extra={"context": {"error_type": type(exc).__name__}})
        response = problem_response(500, "The service could not complete this request.")
        if request.headers.get("origin") in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = request.headers["origin"]
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Vary"] = "Origin"
        return response
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        try:
            record_request_metrics(
                request_id=request_id,
                method=request.method,
                path=getattr(request.scope.get("route"), "path", "/unmatched"),
                status_code=response.status_code if response is not None else 500,
                duration_ms=duration_ms,
                summary=get_request_usage_summary(),
            )
            if response is not None:
                response.headers["X-Request-ID"] = request_id
                response.headers.setdefault("X-Content-Type-Options", "nosniff")
                response.headers.setdefault("Referrer-Policy", "no-referrer")
                response.headers.setdefault("Cache-Control", "no-store")
                response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        except Exception:
            pass
        request_id_var.reset(request_id_token)
        usage_accumulator_var.reset(usage_token)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/livez")
async def liveness():
    """Process health only; does not claim that dependencies are available."""
    return {"status": "alive"}


@app.get("/readyz")
async def readiness():
    """Authentication DB readiness, not an LLM/n8n/CDR end-to-end promise."""
    if AUTH_REQUIRED:
        pool = getattr(app.state, "auth_db_pool", None)
        try:
            if pool is None:
                raise RuntimeError("unavailable")
            await pool.fetchval("SELECT 1", timeout=2)
        except Exception:
            return problem_response(503, "The service is not ready.", headers={"Retry-After": "3"})
    if os.getenv('ANALYSIS_DISPATCH_ENABLED','false').lower()=='true':
        from services.analysis_dispatcher import require_dispatcher
        try:require_dispatcher()
        except DispatcherUnavailable:
            return problem_response(503,'Background analysis is not ready.',headers={'Retry-After':'3'})
    scope='api-auth-and-analysis-dispatcher' if os.getenv('ANALYSIS_DISPATCH_ENABLED','false').lower()=='true' else 'api-and-auth-database'
    return {"status": "ready", "scope": scope}


# Every browser-facing route requires a Better Auth session. The optional
# legacy API key remains only to avoid silently opening an old deployment
# before its deprecated config is removed; it must never be shipped to Vite.
browser_auth = [Depends(require_api_key), Depends(require_authenticated_user)]
admin_auth = [Depends(require_api_key), Depends(require_authenticated_user), Depends(require_admin_api_key)]
app.include_router(upload.router, dependencies=browser_auth)
app.include_router(documents.router, dependencies=browser_auth)
app.include_router(analysis.router, dependencies=browser_auth)
app.include_router(query.router, dependencies=browser_auth)
app.include_router(supervisor.router, dependencies=browser_auth)
app.include_router(advisory_panel.router, dependencies=browser_auth)
app.include_router(research.router, dependencies=browser_auth)
app.include_router(audit.router, dependencies=browser_auth)
app.include_router(evaluation.router, dependencies=admin_auth)
app.include_router(observability.router, dependencies=admin_auth)
app.include_router(n8n.router)
