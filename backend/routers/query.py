import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from contracts import ConversationRequest as QueryRequest

from services.agent import agentic_retrieve_stream
from services.llm import stream_answer
from services.evaluator import evaluate_and_store
from services.security import limiter, RATE_LIMIT_QUERY
from services.session_scope import DEFAULT_SESSION_ID, get_session_id

router = APIRouter()


def _sse(event_type: str, payload: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **payload})}\n\n"


def _stream_response(
    question: str,
    document_filter: str | None,
    history: list[dict] | None,
    session_id: str = DEFAULT_SESSION_ID,
):
    # Agentic retrieval: [condense follow-up using history] -> hybrid search
    # -> LLM evaluates whether the chunks are enough -> rephrases + retries
    # (max 2 iterations) if not. Streamed as a generator (rather than
    # calling agentic_retrieve directly) so each rephrase attempt can be
    # surfaced to the UI as a "status" SSE event before generation starts —
    # otherwise the retry loop is invisible backend behavior.
    chunks: list[dict] = []
    for kind, payload in agentic_retrieve_stream(question, document_filter, history, session_id):
        if kind == "status":
            yield _sse("status", {
                "message": f"Δεν βρέθηκαν αρκετά σχετικά αποσπάσματα — αναδιατυπώνω την ερώτηση (προσπάθεια {payload['iteration']})…",
                "query": payload["query"],
            })
        else:
            _final_query, chunks, _iterations = payload

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
    except Exception:
        yield _sse("error", {"message": "Answer generation is temporarily unavailable. Please retry later."})
        return

    # Faithfulness + relevance scoring runs after the full answer is in,
    # and persists to SQLite for the GET /evaluation dashboard (step 12).
    try:
        eval_scores = evaluate_and_store(question, full_answer, chunks, history)
    except Exception:
        eval_scores = None

    yield _sse("done", {"citations": citations, "eval": eval_scores})


@router.post("/query")
@limiter.limit(RATE_LIMIT_QUERY)
async def query(request: Request, req: QueryRequest, session_id: str = Depends(get_session_id)):
    """
    SSE streaming over the LangGraph agent's agentic retrieval (hybrid
    search + evaluate/rephrase loop, with a history-aware condense step
    for follow-up questions), followed by faithfulness/relevance
    evaluation once the full answer has streamed.
    """
    history = [h.model_dump() for h in req.history] if req.history else None
    return StreamingResponse(
        _stream_response(req.question, req.document_filter, history, session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
