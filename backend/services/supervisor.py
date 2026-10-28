"""Document-focused supervisor for the shared RAG knowledge base.

The supervisor is deliberately an orchestrator, not another document store.
It decides when a request needs evidence from uploaded PDFs, invokes the
shared RAG pipeline, and then turns that evidence into one final answer.
"""
from services.agent import agentic_retrieve_stream
from services.evaluator import evaluate_and_store
from services.llm import call_with_tools, stream_answer
from services.session_scope import DEFAULT_SESSION_ID

MAX_SUPERVISOR_STEPS = 4

SEARCH_DOCUMENTS_TOOL = {
    "name": "search_documents",
    "description": (
        "Search the user's uploaded documents and return a grounded answer with citations. "
        "Use this for facts, figures, rules, deadlines, and definitions in the PDFs."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The question to answer from the documents."},
        },
        "required": ["query"],
    },
}

FINISH_TOOL = {
    "name": "finish",
    "description": "Call this once you can give the user a final answer using the gathered evidence.",
    "parameters": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "The final answer to give the user."},
        },
        "required": ["summary"],
    },
}

SUPERVISOR_INSTRUCTIONS = """You are a supervisor for document analysis.
Use search_documents whenever the answer depends on uploaded documents. Do not
invent facts that are not supported by the retrieved evidence. Call finish only
when you have a concise, useful final answer for the user."""


def _build_supervisor_prompt(question: str, transcript: list[str]) -> str:
    history_text = "\n\n".join(transcript) if transcript else "No search has run yet."
    return f"{SUPERVISOR_INSTRUCTIONS}\n\nUser request: {question}\n\nWork completed:\n{history_text}"


def _run_document_search_stream(
    query: str,
    document_filter: str | None,
    history: list[dict] | None,
    session_id: str = DEFAULT_SESSION_ID,
):
    """Run the same grounded retrieval and answer path as the document assistant."""
    chunks: list[dict] = []
    for kind, payload in agentic_retrieve_stream(query, document_filter, history, session_id):
        if kind == "result":
            _final_query, chunks, _iterations = payload

    citations = [
        {"filename": chunk["filename"], "page": chunk["page_number"], "text": chunk["text"]}
        for chunk in chunks
    ]

    full_answer = ""
    for token in stream_answer(query, chunks, history):
        full_answer += token
        yield ("token", token)

    try:
        evaluate_and_store(query, full_answer, chunks, history)
    except Exception:
        pass

    yield ("done", {"answer": full_answer, "citations": citations})


def run_supervisor_stream(
    question: str,
    document_filter: str | None = None,
    history: list[dict] | None = None,
    session_id: str = DEFAULT_SESSION_ID,
):
    """Yield routing, grounded-answer, and final-summary events for one request."""
    transcript: list[str] = []
    tools = [SEARCH_DOCUMENTS_TOOL, FINISH_TOOL]

    for _ in range(MAX_SUPERVISOR_STEPS):
        response = call_with_tools(_build_supervisor_prompt(question, transcript), tools, max_tokens=500)
        tool_call = response["tool_call"]

        if tool_call is None or tool_call["name"] == "finish":
            summary = tool_call["input"].get("summary") if tool_call else None
            yield ("done", {"summary": summary or response["text"] or "Completed."})
            return

        if tool_call["name"] == "search_documents":
            query = tool_call["input"].get("query") or question
            yield ("route", {"tool": "search_documents", "input": query})

            answer, citations = "", []
            for kind, payload in _run_document_search_stream(query, document_filter, history, session_id):
                if kind == "token":
                    yield ("rag_token", payload)
                else:
                    answer = payload["answer"]
                    citations = payload["citations"]
            yield ("rag_done", {"citations": citations})
            transcript.append(f"search_documents({query!r}) -> {answer}")
            continue

        transcript.append("The requested tool is not available.")

    yield ("done", {
        "summary": "The supervisor could not complete the request within its step limit.",
        "error": True,
    })
