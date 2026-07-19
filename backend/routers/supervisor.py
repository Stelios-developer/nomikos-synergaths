import base64
import json

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.supervisor import run_supervisor_stream
from services.security import limiter, RATE_LIMIT_SUPERVISOR, agent_enabled_for_request
from services.session_scope import get_session_id

router = APIRouter()


class SupervisorRequest(BaseModel):
    question: str
    document_filter: str | None = None


def _sse(event_type: str, payload: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **payload})}\n\n"


def _stream(question: str, document_filter: str | None, agent_enabled: bool, session_id: str):
    for kind, payload in run_supervisor_stream(question, document_filter, None, agent_enabled, session_id):
        if kind == "rag_token":
            yield _sse("rag_token", {"content": payload})
        elif kind == "action_result":
            image_b64 = None
            if payload.get("image_bytes"):
                image_b64 = base64.b64encode(payload["image_bytes"]).decode("ascii")
            yield _sse("action_done", {
                "success": payload["success"],
                "stdout": payload["stdout"],
                "image_base64": image_b64,
                "attempts": payload["attempts"],
                "summary": payload.get("summary"),
                "error": payload.get("error"),
                "sandbox_backend": payload.get("sandbox_backend"),
            })
        else:
            yield _sse(kind, payload)


@router.post("/supervisor/run")
@limiter.limit(RATE_LIMIT_SUPERVISOR)
async def run_supervisor(
    request: Request,
    req: SupervisorRequest,
    x_api_key: str | None = Header(default=None),
    session_id: str = Depends(get_session_id),
):
    """
    SSE stream for the Supervisor agent (services/supervisor.py): decides,
    via native tool-calling, whether a request needs document retrieval
    (search_documents -> the existing agentic RAG pipeline), code
    execution (run_code -> the existing multi-agent Action Agent), or
    both chained together (e.g. "find X in the PDF, then compute Y from
    it"). Orchestrates the two existing subsystems rather than
    duplicating their logic — no new retrieval or execution code lives here.

    Code execution specifically requires a valid agent API key
    (services/security.py::agent_enabled_for_request) — an unauthenticated
    request degrades gracefully to documents-only (run_code is simply
    never offered to the LLM as a tool) rather than erroring, so the RAG
    half of this endpoint stays public even when code execution is locked.

    Emits: {"type":"route","tool":...,"input":...} before invoking a
    sub-agent, {"type":"rag_token","content":...} / {"type":"rag_done",
    "citations":[...]} for the document-search path, {"type":"action_plan"
    |"action_code"|"action_review"|"action_error",...} forwarded verbatim
    from the Action Agent's own trace, {"type":"action_done",...} when it
    finishes, and finally {"type":"done","summary":...}.
    """
    agent_enabled = agent_enabled_for_request(x_api_key)
    return StreamingResponse(
        _stream(req.question, req.document_filter, agent_enabled, session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
