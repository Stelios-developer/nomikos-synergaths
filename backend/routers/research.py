import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from contracts import ConversationRequest as ResearchRequest

from services.multihop import run_research_stream
from services.security import limiter, RATE_LIMIT_RESEARCH
from services.session_scope import get_session_id

router = APIRouter()


def _sse(event_type: str, payload: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **payload})}\n\n"


def _stream(question: str, document_filter: str | None, history: list[dict] | None, session_id: str):
    for kind, payload in run_research_stream(question, document_filter, history, session_id):
        if kind == "subquestions":
            yield _sse("subquestions", {"subquestions": payload})
        elif kind == "token":
            yield _sse("token", {"content": payload})
        else:
            yield _sse(kind, payload)


@router.post("/research/run")
@limiter.limit(RATE_LIMIT_RESEARCH)
async def run_research(request: Request, req: ResearchRequest, session_id: str = Depends(get_session_id)):
    """
    SSE stream for the Multi-hop Research Agent (services/multihop.py):
    decomposes a compound question into standalone sub-questions, runs
    retrieval + Corrective RAG grading per sub-question CONCURRENTLY,
    merges the results, and streams one final synthesized answer.

    Emits: {"type":"subquestions","subquestions":[...]} once, then
    {"type":"subretrieval","sub_question":...,"citations":[...]} once
    per sub-question (completion order, not a fixed sequence), then
    {"type":"token","content":...} as the final answer streams, finally
    {"type":"done","citations":[...]}.
    """
    history = [h.model_dump() for h in req.history] if req.history else None
    return StreamingResponse(
        _stream(req.question, req.document_filter, history, session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
