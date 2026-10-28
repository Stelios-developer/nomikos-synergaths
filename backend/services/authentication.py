"""Server-side Better Auth session verification for FastAPI.

The browser only sends the secure, HttpOnly Better Auth cookie. This module
looks up that opaque session token in the Better Auth PostgreSQL tables and
returns its immutable user ID. No client-provided workspace/session header is
trusted in an authenticated deployment.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass
from urllib.parse import unquote

import asyncpg
from fastapi import HTTPException, Request, status


AUTH_REQUIRED = os.getenv("AUTH_REQUIRED", "false").lower() == "true"
REQUIRE_VERIFIED_EMAIL = os.getenv("REQUIRE_VERIFIED_EMAIL", "true").lower() == "true"
DATABASE_URL = os.getenv("DATABASE_URL", "")
COOKIE_PREFIX = os.getenv("AUTH_COOKIE_PREFIX", "nexus")
COOKIE_SIGNING_SECRET = os.getenv("BETTER_AUTH_SECRET", "")


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    email: str | None = None
    name: str | None = None


def _cookie_token(request: Request) -> str | None:
    # Better Auth uses the regular name locally and a __Secure- prefixed name
    # when HTTPS is enabled. Supporting both lets exactly the same API code run
    # locally and in production without weakening the production cookie policy.
    signed_value = (
        request.cookies.get(f"__Secure-{COOKIE_PREFIX}.session_token")
        or request.cookies.get(f"{COOKIE_PREFIX}.session_token")
        or request.cookies.get(f"{COOKIE_PREFIX}-session_token")
    )
    if not signed_value or not COOKIE_SIGNING_SECRET or "." not in signed_value:
        return None
    # Better Call percent-encodes signed cookie values before the browser
    # stores them (the Base64 padding becomes ``%3D``).  Starlette returns
    # that stored representation unchanged, so decode it before comparing
    # the signature.
    signed_value = unquote(signed_value)
    token, signature = signed_value.rsplit(".", 1)
    # Better Auth's session-token cookie uses Better Call's signed-cookie
    # format: a standard Base64 HMAC including its trailing padding.
    expected = base64.b64encode(
        hmac.new(COOKIE_SIGNING_SECRET.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).digest()
    ).decode("ascii")
    return token if hmac.compare_digest(signature, expected) else None


async def _pool(request: Request) -> asyncpg.Pool:
    pool = getattr(request.app.state, "auth_db_pool", None)
    if pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is temporarily unavailable.",
        )
    return pool


async def require_authenticated_user(request: Request) -> AuthenticatedUser:
    """Validate a Better Auth database session and cache it for this request."""
    existing = getattr(request.state, "auth_user", None)
    if existing is not None:
        return existing

    if not AUTH_REQUIRED:
        # Deliberately for local demos/tests only. Production startup refuses
        # this setting so it can never become an accidental public bypass.
        user = AuthenticatedUser(id="__local_development__", email="local@example.invalid")
        request.state.auth_user = user
        return user

    token = _cookie_token(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in is required.")

    pool = await _pool(request)
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            '''
            SELECT s."userId" AS user_id, u.email, u.name, u."emailVerified" AS email_verified
            FROM "session" AS s
            INNER JOIN "user" AS u ON u.id = s."userId"
            WHERE s.token = $1 AND s."expiresAt" > NOW()
            LIMIT 1
            ''',
            token,
        )

    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Your session has expired. Please sign in again.")
    if REQUIRE_VERIFIED_EMAIL and not row["email_verified"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Verify your email before accessing your workspace.")

    user = AuthenticatedUser(id=row["user_id"], email=row["email"], name=row["name"])
    request.state.auth_user = user
    return user


async def start_auth_pool(app) -> None:
    if not AUTH_REQUIRED:
        app.state.auth_db_pool = None
        return
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required when AUTH_REQUIRED=true.")
    if not COOKIE_SIGNING_SECRET or len(COOKIE_SIGNING_SECRET) < 32:
        raise RuntimeError("BETTER_AUTH_SECRET must be shared with Better Auth and contain at least 32 characters.")
    app.state.auth_db_pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=int(os.getenv("AUTH_DB_POOL_SIZE", "10")),
        command_timeout=5,
    )


async def close_auth_pool(app) -> None:
    pool = getattr(app.state, "auth_db_pool", None)
    if pool is not None:
        await pool.close()
