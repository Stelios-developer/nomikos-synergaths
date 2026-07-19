import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.advisory_panel import run_panel_stream
from services.security import limiter, RATE_LIMIT_PANEL
from services.session_scope import get_session_id

router = APIRouter()


class PanelRequest(BaseModel):
    question: str
    document_filter: str | None = None


def _sse(event_type: str, payload: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **payload})}\n\n"


def _stream(question: str, document_filter: str | None, session_id: str):
    for kind, payload in run_panel_stream(question, document_filter, session_id):
        if kind == "citations":
            yield _sse("citations", {"citations": payload})
        else:
            yield _sse(kind, payload)


@router.post("/panel/run")
@limiter.limit(RATE_LIMIT_PANEL)
async def run_panel(request: Request, req: PanelRequest, session_id: str = Depends(get_session_id)):
    """
    SSE stream for the Advisory Panel (services/advisory_panel.py): three
    advisor personas (Aggressive Tax Optimizer, Conservative Compliance
    Officer, Risk Assessor) run CONCURRENTLY over the same retrieved
    document chunks, then a Moderator synthesizes their agreement and
    disagreement into one final recommendation.

    Emits: {"type":"citations","citations":[...]} once at the start,
    {"type":"advisor","id":...,"label":...,"emoji":...,"answer":...} once
    per advisor in COMPLETION order (not a fixed sequence — proves the
    three run in parallel rather than one after another), and finally
    {"type":"done","moderator_summary":...}.
    """
    return StreamingResponse(
        _stream(req.question, req.document_filter, session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
