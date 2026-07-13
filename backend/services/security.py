"""
Auth + rate limiting for public deployments.

API key check is opt-in: if API_KEY isn't set in the environment, auth
is disabled (so local dev / the test suite don't need to configure
anything). Set API_KEY before deploying anywhere public — see README.

Rate limits default fairly high (generous enough that the pytest suite
never trips them) and are overridable via env vars so a real deploy can
tighten them.
"""
import os

from fastapi import Header, HTTPException, status
from slowapi import Limiter
from slowapi.util import get_remote_address

API_KEY = os.getenv("API_KEY")

RATE_LIMIT_QUERY = os.getenv("RATE_LIMIT_QUERY", "20/minute")
RATE_LIMIT_UPLOAD = os.getenv("RATE_LIMIT_UPLOAD", "10/minute")

limiter = Limiter(key_func=get_remote_address)


async def require_api_key(x_api_key: str | None = Header(default=None)):
    if not API_KEY:
        return  # auth disabled — no API_KEY configured
    if x_api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key. Send it as the X-API-Key header.",
        )
