"""
Per-visitor document isolation for a public, multi-user deployment.

Without this, every uploaded PDF lands in one shared ChromaDB collection
with no owner concept at all (see db/chroma_client.py) — any visitor could
list, query, or delete ANY other visitor's documents. Real user accounts
would be the "complete" fix, but a lightweight anonymous session
identifier is enough to give each browser its own private document set
without requiring signup/login for what's meant to be an open public demo.

The frontend generates a random UUID on first load (see
frontend/src/utils/session.ts), persists it in localStorage, and sends it
as the X-Session-ID header on every request. Every chunk gets stamped with
that session_id at ingestion time (services/ingestion.py), and every
read/delete is filtered by it (services/retrieval.py, routers/documents.py).

DEFAULT_SESSION_ID is the fallback used when the header is absent (direct
API calls, curl, the test suite) — this preserves the exact
pre-isolation behavior (one shared bucket) for anything that doesn't opt
into per-session scoping, so existing tests and local/manual API usage
keep working unchanged; only real browser traffic (which always sends a
real UUID) gets actual isolation.
"""
from fastapi import Header

DEFAULT_SESSION_ID = "__default__"


def get_session_id(x_session_id: str | None = Header(default=None)) -> str:
    return x_session_id or DEFAULT_SESSION_ID


def where_clause(session_id: str, document_filter: str | None = None) -> dict:
    """
    Builds a ChromaDB `where` filter scoped to `session_id`, optionally
    ANDed with a specific filename. Centralized here so every retrieval
    path (vector search, keyword search, document listing/deletion,
    citation page rendering) applies the exact same isolation rule instead
    of five slightly-different hand-rolled filters.
    """
    if document_filter:
        return {"$and": [{"session_id": session_id}, {"filename": document_filter}]}
    return {"session_id": session_id}
