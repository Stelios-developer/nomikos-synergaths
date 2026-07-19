from fastapi import APIRouter

from services.observability import get_summary, get_recent_requests

router = APIRouter()


@router.get("/observability/summary")
async def observability_summary():
    """Aggregate cost/latency across every request the process has handled
    (persisted in SQLite — see services/observability.py), broken down by
    route. This is the "what is this app costing me, and which feature is
    driving it" view — the Advisory Panel/Debate/Research agents fire
    several LLM calls per request, so their per-route cost is expected to
    dominate this table."""
    return get_summary()


@router.get("/observability/requests")
async def observability_requests(limit: int = 50):
    """Most recent individual requests with their request_id, latency,
    token counts, and cost — the "why did THIS specific query behave the
    way it did" view. Cross-reference a request_id here against the
    structured JSON logs to see every LLM call that request made."""
    return {"requests": get_recent_requests(limit)}
