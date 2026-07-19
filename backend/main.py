import os
import time

from fastapi import FastAPI, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from routers import upload, documents, query, evaluation, agent_action, supervisor, advisory_panel, debate, research, audit, observability
from services.security import limiter, require_api_key, agent_enabled_for_request
from services.observability import (
    configure_logging,
    configure_tracing,
    new_request_id,
    request_id_var,
    usage_accumulator_var,
    get_request_usage_summary,
    record_request_metrics,
    traced_span,
)

load_dotenv()
configure_logging()
configure_tracing()

app = FastAPI(title="Document RAG Assistant API")

# Rate limiting (per-IP, slowapi). Limits are set per-route in each router
# (see routers/upload.py, routers/query.py) so upload/query — the calls
# that spend LLM credits — get a tighter limit than read-only routes.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS - defaults to "*" for local dev. In production, set ALLOWED_ORIGINS
# to a comma-separated list (e.g. "https://your-app.vercel.app") so the API
# isn't wide open to any origin.
_allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "*")
allowed_origins = (
    ["*"] if _allowed_origins_env == "*" else [o.strip() for o in _allowed_origins_env.split(",")]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    """
    Gives every request a correlation ID (X-Request-ID, generated unless
    the caller already supplied one), a root OTel span, and a per-request
    cost/token accumulator (services/observability.py's contextvars) that
    concurrent LLM calls fired via services.observability.submit_with_context
    still attribute back to correctly. Persists one row of aggregate
    metrics per request to SQLite in a `finally` block — wrapped in its
    own try/except so a metrics-recording bug can never turn into a 500
    for an otherwise-successful response.
    """
    request_id = request.headers.get("X-Request-ID") or new_request_id()
    request_id_token = request_id_var.set(request_id)
    usage_token = usage_accumulator_var.set([])
    start = time.perf_counter()
    response = None
    try:
        with traced_span(f"{request.method} {request.url.path}", http_method=request.method):
            response = await call_next(request)
        return response
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        try:
            record_request_metrics(
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status_code=response.status_code if response is not None else 500,
                duration_ms=duration_ms,
                summary=get_request_usage_summary(),
            )
            if response is not None:
                response.headers["X-Request-ID"] = request_id
        except Exception:
            pass
        request_id_var.reset(request_id_token)
        usage_accumulator_var.reset(usage_token)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/config")
async def get_config(x_api_key: str | None = Header(default=None)):
    """
    Public, unauthenticated config probe for the frontend. Deliberately
    NOT behind require_api_key/require_agent_api_key — a visitor with no
    key at all must still be able to call this to learn that the Action
    Agent's code-execution tool is locked in this deployment, so the UI
    can render a locked state instead of a raw 401/403 after the fact.
    """
    return {"agent_enabled": agent_enabled_for_request(x_api_key)}


# API key auth (see services/security.py — no-op unless API_KEY is set).
# /health and /config are deliberately left open so load balancers/uptime
# checks and the frontend's pre-flight capability probe don't need a key.
#
# agent_action is intentionally NOT in this list: it carries its own
# require_agent_api_key dependency (routers/agent_action.py), a separate,
# independently-configured, fail-closed key (AGENT_API_KEY) — see
# services/security.py.
_auth = [Depends(require_api_key)]
app.include_router(upload.router, dependencies=_auth)
app.include_router(documents.router, dependencies=_auth)
app.include_router(query.router, dependencies=_auth)
app.include_router(evaluation.router, dependencies=_auth)
app.include_router(agent_action.router)
app.include_router(supervisor.router, dependencies=_auth)
app.include_router(advisory_panel.router, dependencies=_auth)
app.include_router(debate.router, dependencies=_auth)
app.include_router(research.router, dependencies=_auth)
app.include_router(audit.router, dependencies=_auth)
app.include_router(observability.router, dependencies=_auth)
