import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from contracts import AgentRequest as SupervisorRequest

from services.security import limiter, RATE_LIMIT_SUPERVISOR
from services.session_scope import get_session_id
from services.supervisor import run_supervisor_stream

router = APIRouter()


def _sse(event_type: str, payload: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **payload})}\n\n"


def _stream(question: str, document_filter: str | None, session_id: str):
    for kind, payload in run_supervisor_stream(question, document_filter, None, session_id):
        if kind == "rag_token":
            yield _sse("rag_token", {"content": payload})
        else:
            yield _sse(kind, payload)


@router.post("/supervisor/run")
@limiter.limit(RATE_LIMIT_SUPERVISOR)
async def run_supervisor(
    request: Request,
    req: SupervisorRequest,
    session_id: str = Depends(get_session_id),
):
    """Stream the document supervisor's routing trace and grounded answer."""
    return StreamingResponse(
        _stream(req.question, req.document_filter, session_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
