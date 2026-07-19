import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.debate import run_debate_stream
from services.security import limiter, RATE_LIMIT_DEBATE
from services.session_scope import get_session_id

router = APIRouter()


class DebateRequest(BaseModel):
    question: str
    document_filter: str | None = None


def _sse(event_type: str, payload: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **payload})}\n\n"


def _stream(question: str, document_filter: str | None, session_id: str):
    for kind, payload in run_debate_stream(question, document_filter, session_id):
        if kind == "citations":
            yield _sse("citations", {"citations": payload})
        else:
            yield _sse(kind, payload)


@router.post("/debate/run")
@limiter.limit(RATE_LIMIT_DEBATE)
async def run_debate(request: Request, req: DebateRequest, session_id: str = Depends(get_session_id)):
    """
    SSE stream for the Debate Agents (services/debate.py): two personas
    argue opposing, document-grounded positions on the question across
    MAX_ROUNDS rounds of direct rebuttal (each round runs both sides
    concurrently, since neither has an information advantage over the
    other within a round), followed by a Judge agent's final ruling.

    Emits: {"type":"citations","citations":[...]} once, then
    {"type":"argument","side":"for"|"against","round":n,"label":...,
    "emoji":...,"text":...} once per side per round (in completion
    order, not a fixed sequence), finally
    {"type":"verdict","summary":...}.
    """
    return StreamingResponse(
        _stream(req.question, req.document_filter, session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
