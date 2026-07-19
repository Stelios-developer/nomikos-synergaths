import base64
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.code_agent import run_agent_stream
from services.security import limiter, RATE_LIMIT_AGENT, require_agent_api_key

router = APIRouter()


class AgentGoalRequest(BaseModel):
    goal: str


def _sse(event_type: str, payload: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **payload})}\n\n"


def _stream(goal: str):
    for kind, payload in run_agent_stream(goal):
        if kind == "plan":
            yield _sse("plan", payload)
        elif kind == "code":
            yield _sse("code", payload)
        elif kind == "review":
            yield _sse("review", payload)
        elif kind == "error":
            yield _sse("error", payload)
        elif kind == "result":
            image_b64 = None
            if payload.get("image_bytes"):
                image_b64 = base64.b64encode(payload["image_bytes"]).decode("ascii")
            yield _sse("done", {
                "success": payload["success"],
                "stdout": payload["stdout"],
                "image_base64": image_b64,
                "attempts": payload["attempts"],
                "summary": payload.get("summary"),
                "error": payload.get("error"),
                "sandbox_backend": payload.get("sandbox_backend"),
            })


@router.post("/agent/run", dependencies=[Depends(require_agent_api_key)])
@limiter.limit(RATE_LIMIT_AGENT)
async def run_agent(request: Request, req: AgentGoalRequest):
    """
    SSE stream of the multi-agent Action Agent (services/code_agent.py):
    a Planner breaks `goal` into steps, a Coder decides via native
    tool-calling whether to run code or finish, a Reviewer vets every
    code snippet before it reaches the sandbox, and the sandbox
    (services/sandbox.py — Docker if available, subprocess fallback
    otherwise) reports real runtime errors back into the loop. Entirely
    independent of the document RAG pipeline — no retrieval, no ChromaDB.

    Gated by require_agent_api_key (services/security.py), which fails
    CLOSED by default — unlike the rest of the app's optional API_KEY,
    code execution requires AGENT_API_KEY (or API_KEY) to be explicitly
    set, since this is the one route with a real security boundary
    attached to it (arbitrary LLM-generated code execution).

    Emits, in order: {"type":"plan","steps":[...]}, then per Coder
    decision {"type":"code","attempt":n,"code":...},
    {"type":"review","attempt":n,"approved":bool,"feedback":...}, and on
    an approved-but-failing run {"type":"error","attempt":n,"message":...},
    finally {"type":"done","success":bool,"stdout":...,"image_base64":...,
    "attempts":n,"summary":...,"sandbox_backend":"docker"|"subprocess"}.
    """
    return StreamingResponse(
        _stream(req.goal),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
