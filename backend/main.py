import os

from fastapi import FastAPI, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from routers import upload, documents, query, evaluation, agent_action, supervisor, advisory_panel
from services.security import limiter, require_api_key, agent_enabled_for_request

load_dotenv()

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
