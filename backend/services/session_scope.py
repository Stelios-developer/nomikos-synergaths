"""Workspace scoping backed by an authenticated Better Auth user.

The name ``get_session_id`` remains for the existing RAG pipeline, but the
value is now an immutable account ID verified on the server. ``X-Session-ID``
is intentionally ignored in authenticated deployments.
"""
from fastapi import Depends, Header, Request

from services.authentication import AUTH_REQUIRED, AuthenticatedUser, require_authenticated_user

DEFAULT_SESSION_ID = "__local_development__"


async def get_session_id(
    request: Request,
    user: AuthenticatedUser = Depends(require_authenticated_user),
    x_session_id: str | None = Header(default=None),
) -> str:
    # Retain anonymous scopes only for explicit local-development/test mode so
    # existing sample data can be exercised without starting PostgreSQL. This
    # header is ignored the moment AUTH_REQUIRED=true (mandatory in production).
    workspace_id = x_session_id or DEFAULT_SESSION_ID if not AUTH_REQUIRED else user.id
    request.state.workspace_id = workspace_id
    return workspace_id
