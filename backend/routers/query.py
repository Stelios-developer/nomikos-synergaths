import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.agent import agentic_retrieve
from services.llm import stream_answer
from services.evaluator import evaluate_and_store
from services.security import limiter, RATE_LIMIT_QUERY

router = APIRouter()


class HistoryTurn(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class QueryRequest(BaseModel):
    question: str
    document_filter: str | None = None
    history: list[HistoryTurn] | None = None  # prior turns, oldest first — see services/agent.py


def _sse(event_type: str, payload: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **payload})}\n\n"


def _stream_response(question: str, document_filter: str | None, history: list[dict] | None):
    # Agentic retrieval: [condense follow-up using history] -> hybrid search
    # -> LLM evaluates whether the chunks are enough -> rephrases + retries
    # (max 2 iterations) if not.
    final_query, chunks, iterations = agentic_retrieve(question, document_filter, history)
    citations = [
        {"filename": c["filename"], "page": c["page_number"], "text": c["text"]}
        for c in chunks
    ]

    full_answer = ""
    try:
        # Generation always uses the user's original question (not the
        # condensed/rephrased retrieval query) plus history, so the answer
        # resolves follow-ups naturally and matches what was actually asked.
        for token in stream_answer(question, chunks, history):
            full_answer += token
            yield _sse("token", {"content": token})
    except Exception as e:
        yield _sse("error", {"message": str(e)})
        return

    # Faithfulness + relevance scoring runs after the full answer is in,
    # and persists to SQLite for the GET /evaluation dashboard (step 12).
    try:
        eval_scores = evaluate_and_store(question, full_answer, chunks)
    except Exception:
        eval_scores = None

    yield _sse("done", {"citations": citations, "eval": eval_scores})


@router.post("/query")
@limiter.limit(RATE_LIMIT_QUERY)
async def query(request: Request, req: QueryRequest):
    """
    SSE streaming over the LangGraph agent's agentic retrieval (hybrid
    search + evaluate/rephrase loop, with a history-aware condense step
    for follow-up questions), followed by faithfulness/relevance
    evaluation once the full answer has streamed.
    """
    history = [h.model_dump() for h in req.history] if req.history else None
    return StreamingResponse(
        _stream_response(req.question, req.document_filter, history),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
