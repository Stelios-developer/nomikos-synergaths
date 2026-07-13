import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.agent import agentic_retrieve
from services.llm import stream_answer
from services.evaluator import evaluate_and_store
from services.security import limiter, RATE_LIMIT_QUERY

router = APIRouter()


class QueryRequest(BaseModel):
    question: str
    document_filter: str | None = None


def _sse(event_type: str, payload: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **payload})}\n\n"


def _stream_response(question: str, document_filter: str | None):
    # Agentic retrieval: hybrid search -> LLM evaluates whether the chunks
    # are enough -> rephrases + retries (max 2 iterations) if not.
    final_query, chunks, iterations = agentic_retrieve(question, document_filter)
    citations = [
        {"filename": c["filename"], "page": c["page_number"], "text": c["text"]}
        for c in chunks
    ]

    full_answer = ""
    try:
        # Generation always uses the user's original question (not the
        # rephrased retrieval query) so the answer's phrasing matches
        # what was actually asked.
        for token in stream_answer(question, chunks):
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
    SSE streaming (step 8) over the LangGraph agent's agentic retrieval
    (step 10: hybrid search + evaluate/rephrase loop, step 9: hybrid
    search itself), followed by faithfulness/relevance evaluation
    (step 12) once the full answer has streamed.
    """
    return StreamingResponse(
        _stream_response(req.question, req.document_filter),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
