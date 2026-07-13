import os

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from routers import upload, documents, query, evaluation
from services.security import limiter, require_api_key

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


# API key auth (see services/security.py — no-op unless API_KEY is set).
# /health is deliberately left open so load balancers/uptime checks don't
# need a key.
_auth = [Depends(require_api_key)]
app.include_router(upload.router, dependencies=_auth)
app.include_router(documents.router, dependencies=_auth)
app.include_router(query.router, dependencies=_auth)
app.include_router(evaluation.router, dependencies=_auth)
