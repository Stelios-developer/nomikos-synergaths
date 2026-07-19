"""
Auth + rate limiting for public deployments.

API key check is opt-in: if API_KEY isn't set in the environment, auth
is disabled (so local dev / the test suite don't need to configure
anything). Set API_KEY before deploying anywhere public — see README.

Rate limits default fairly high (generous enough that the pytest suite
never trips them) and are overridable via env vars so a real deploy can
tighten them.

AGENT_API_KEY is a SEPARATE, deliberately fail-closed gate for the
code-execution surface (the standalone Action Agent) — see
require_agent_api_key below. This is intentionally NOT the same
on/off switch as the general API_KEY: a public deployment can
reasonably want the RAG features open to anonymous visitors while
keeping arbitrary code execution locked down, which a single
all-or-nothing API_KEY can't express on its own.
"""
import os

from fastapi import Header, HTTPException, status
from slowapi import Limiter
from slowapi.util import get_remote_address

API_KEY = os.getenv("API_KEY")

# Falls back to the general API_KEY if no dedicated one is set, so a
# single API_KEY still locks everything (including code execution) by
# default for anyone who just wants one simple switch. Set AGENT_API_KEY
# to a DIFFERENT value if you want code execution locked while the rest
# of the app stays open to the public.
AGENT_API_KEY = os.getenv("AGENT_API_KEY") or API_KEY

RATE_LIMIT_QUERY = os.getenv("RATE_LIMIT_QUERY", "20/minute")
RATE_LIMIT_UPLOAD = os.getenv("RATE_LIMIT_UPLOAD", "10/minute")
# Tighter than /query by default: each run does an LLM call *and* spawns a
# subprocess (services/sandbox.py), so it's the most expensive route in the app.
RATE_LIMIT_AGENT = os.getenv("RATE_LIMIT_AGENT", "10/minute")

limiter = Limiter(key_func=get_remote_address)


async def require_api_key(x_api_key: str | None = Header(default=None)):
    if not API_KEY:
        return  # auth disabled — no API_KEY configured
    if x_api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key. Send it as the X-API-Key header.",
        )


async def require_agent_api_key(x_api_key: str | None = Header(default=None)):
    """
    Guards the standalone Action Agent router (routers/agent_action.py).
    Deliberately fail-CLOSED, unlike require_api_key's fail-open default:
    code execution is the one feature in this app with a real security
    boundary attached to it (see services/sandbox.py's Docker-vs-subprocess
    tradeoff), so "nobody configured anything" must mean "disabled", not
    "wide open" — the opposite default from the general API_KEY, on purpose.
    """
    if not AGENT_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Code execution is disabled in this deployment. Set AGENT_API_KEY "
                "(or API_KEY) and send it as X-API-Key to enable it."
            ),
        )
    if x_api_key != AGENT_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Code execution requires the X-API-Key header.",
        )


def agent_enabled_for_request(x_api_key: str | None) -> bool:
    """
    Non-dependency helper for routes where code execution is OPTIONAL
    rather than a hard gate. Returns whether THIS specific request is
    authorized to trigger run_code, without raising — callers use this to
    decide whether to even offer run_code as a tool at all, or to reflect
    unlock state back via GET /config.
    """
    return bool(AGENT_API_KEY) and x_api_key == AGENT_API_KEY
