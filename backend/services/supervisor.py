"""
Supervisor agent — orchestrates the two previously-independent subsystems
(the document RAG pipeline and the Action Agent) instead of duplicating
either one's logic.

Given a user request, the Supervisor decides via native tool-calling
(services.llm.call_with_tools — the same mechanism the Action Agent's
Coder uses) whether it needs:
  - `search_documents` — the existing agentic RAG pipeline
    (services.agent.agentic_retrieve_stream + services.llm.stream_answer),
    for facts/figures/rules that live in the uploaded PDFs.
  - `run_code` — the existing multi-agent Action Agent
    (services.code_agent.run_agent_stream), for real computation,
    simulation, or charts.
  - both, chained — e.g. "find the depreciation rate in the PDF, then
    compute a 5-year schedule from it". The Supervisor's own ReAct loop
    re-sends the running transcript on each turn (same pattern as the
    Coder loop in services/code_agent.py), so the second tool call
    naturally has the first tool's result available as context and can
    fold it directly into the `run_code` goal text.

This module intentionally contains no retrieval or code-execution logic
of its own — it only decides *when* to call the two existing subsystems
and stitches their outputs together.

Design note on agent_enabled: `run_code` is the one tool here with a real
security boundary attached (arbitrary LLM-generated code execution — see
services/sandbox.py). For a public multi-user deployment where the RAG
half should stay open but code execution should not, run_supervisor_stream
accepts `agent_enabled` and simply OMITS run_code from the tool schema
handed to the LLM when it's False — the model is never offered the tool
at all, so it can only ever choose search_documents/finish, and degrades
to a documents-only assistant rather than erroring. routers/supervisor.py
computes this per-request from whether a valid agent API key was sent
(services/security.py::agent_enabled_for_request); direct callers of this
function (tests, scripts) default to True, matching pre-existing behavior.
"""
from services.agent import agentic_retrieve_stream
from services.code_agent import run_agent_stream as run_action_agent_stream
from services.evaluator import evaluate_and_store
from services.llm import call_with_tools, stream_answer
from services.session_scope import DEFAULT_SESSION_ID

MAX_SUPERVISOR_STEPS = 4

SEARCH_DOCUMENTS_TOOL = {
    "name": "search_documents",
    "description": (
        "Search the user's uploaded documents and get back a grounded, cited answer. "
        "Use this for facts, figures, rules, or definitions that live in the uploaded PDFs."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The question to answer from the documents."},
        },
        "required": ["query"],
    },
}

RUN_CODE_TOOL = {
    "name": "run_code",
    "description": (
        "Runs a self-correcting code agent that writes and executes real Python to compute "
        "something (calculations, simulations, charts). If you already learned a fact or number "
        "from search_documents, state it explicitly in the goal text so the code agent doesn't "
        "have to guess it."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "goal": {
                "type": "string",
                "description": "A precise, self-contained natural-language goal, including any known facts/numbers.",
            },
        },
        "required": ["goal"],
    },
}

FINISH_TOOL = {
    "name": "finish",
    "description": "Call this once you can give the user a final answer using everything learned so far.",
    "parameters": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "The final answer to give the user."},
        },
        "required": ["summary"],
    },
}


def _tools_for(agent_enabled: bool) -> list[dict]:
    tools = [SEARCH_DOCUMENTS_TOOL]
    if agent_enabled:
        tools.append(RUN_CODE_TOOL)
    tools.append(FINISH_TOOL)
    return tools


SUPERVISOR_INSTRUCTIONS = (
    "Είσαι ένας supervisor agent με δύο ειδικευμένους υφισταμένους: 'search_documents' "
    "(αναζητά στα uploaded έγγραφα του χρήστη και επιστρέφει τεκμηριωμένη, με παραπομπές απάντηση) "
    "και 'run_code' (τρέχει έναν self-correcting code agent για πραγματικούς υπολογισμούς/προσομοιώσεις/"
    "γραφήματα). Αποφάσισε ποιο χρειάζεσαι — μπορεί να χρειαστείς και τα δύο σε σειρά (π.χ. πρώτα βρες "
    "ένα στοιχείο στα έγγραφα, μετά χρησιμοποίησέ το σε υπολογισμό). Όταν καλείς 'run_code' αφού έχεις "
    "ήδη μάθει κάτι από το 'search_documents', συμπεριέλαβε ρητά το στοιχείο/αριθμό στο goal — μην τον "
    "αφήσεις να το μαντέψει. Κάλεσε 'finish' μόνο όταν έχεις πλήρη, τελική απάντηση για τον χρήστη."
)

SUPERVISOR_INSTRUCTIONS_DOCS_ONLY = (
    "Είσαι ένας supervisor agent με έναν ειδικευμένο υφιστάμενο: 'search_documents' (αναζητά στα "
    "uploaded έγγραφα του χρήστη και επιστρέφει τεκμηριωμένη, με παραπομπές απάντηση). Η εκτέλεση "
    "κώδικα δεν είναι διαθέσιμη σε αυτή τη συνεδρία. Αν το αίτημα χρειάζεται μόνο υπολογισμό χωρίς "
    "κανένα στοιχείο από έγγραφα, εξήγησε στον χρήστη ότι ο υπολογισμός δεν είναι διαθέσιμος δημόσια "
    "και πρότεινε να το τρέξει τοπικά. Κάλεσε 'finish' μόνο όταν έχεις πλήρη, τελική απάντηση."
)


def _build_supervisor_prompt(question: str, transcript: list[str], agent_enabled: bool) -> str:
    instructions = SUPERVISOR_INSTRUCTIONS if agent_enabled else SUPERVISOR_INSTRUCTIONS_DOCS_ONLY
    history_text = "\n\n".join(transcript) if transcript else "(καμία ενέργεια ακόμα)"
    return f"{instructions}\n\nΑίτημα χρήστη: {question}\n\nΜέχρι στιγμής:\n{history_text}"


def _run_document_search_stream(
    query: str,
    document_filter: str | None,
    history: list[dict] | None,
    session_id: str = DEFAULT_SESSION_ID,
):
    """
    Runs the same agentic retrieval + generation pipeline as the /query
    endpoint (routers/query.py), reused here as the Supervisor's
    `search_documents` tool. Yields ("token", str) as the answer streams,
    then exactly one ("done", {"answer": str, "citations": list[dict]}).
    Also persists to the evaluation DB, same as a normal /query call,
    so questions answered via the Supervisor still show up on the
    Evaluation dashboard.
    """
    chunks: list[dict] = []
    for kind, payload in agentic_retrieve_stream(query, document_filter, history, session_id):
        if kind == "result":
            _final_query, chunks, _iterations = payload

    citations = [
        {"filename": c["filename"], "page": c["page_number"], "text": c["text"]}
        for c in chunks
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
    agent_enabled: bool = True,
    session_id: str = DEFAULT_SESSION_ID,
):
    """
    Generator over the Supervisor's full trace. Yields:
      ("route", {"tool": "search_documents"|"run_code", "input": str})  — before invoking a sub-agent
      ("rag_token", str)                                                 — RAG sub-agent answer, streaming
      ("rag_done", {"citations": [...]})                                 — RAG sub-agent finished
      ("action_plan"|"action_code"|"action_review"|"action_error", dict) — forwarded verbatim from the
                                                                            Action Agent's own trace
      ("action_result", dict)                                            — Action Agent finished
      ("done", {"summary": str, "error"?: bool})                         — exactly once, last
    """
    transcript: list[str] = []
    tools = _tools_for(agent_enabled)

    for _ in range(MAX_SUPERVISOR_STEPS):
        prompt = _build_supervisor_prompt(question, transcript, agent_enabled)
        response = call_with_tools(prompt, tools, max_tokens=500)
        tool_call = response["tool_call"]

        if tool_call is None or tool_call["name"] == "finish":
            summary = tool_call["input"].get("summary") if tool_call else None
            summary = summary or response["text"] or "Ολοκληρώθηκε."
            yield ("done", {"summary": summary})
            return

        if tool_call["name"] == "search_documents":
            query = tool_call["input"].get("query") or question
            yield ("route", {"tool": "search_documents", "input": query})

            answer, citations = "", []
            for kind, payload in _run_document_search_stream(query, document_filter, history, session_id):
                if kind == "token":
                    yield ("rag_token", payload)
                else:  # "done"
                    answer = payload["answer"]
                    citations = payload["citations"]
            yield ("rag_done", {"citations": citations})
            transcript.append(f"search_documents('{query}') -> {answer}")
            continue

        if tool_call["name"] == "run_code" and agent_enabled:
            goal = tool_call["input"].get("goal") or question
            yield ("route", {"tool": "run_code", "input": goal})

            result = None
            for kind, payload in run_action_agent_stream(goal):
                if kind == "result":
                    result = payload
                    yield ("action_result", payload)
                else:
                    yield (f"action_{kind}", payload)

            outcome = result.get("summary") or result.get("stdout") or "(χωρίς έξοδο)"
            transcript.append(f"run_code('{goal}') -> success={result['success']}, αποτέλεσμα: {outcome}")
            continue

        # run_code requested but not enabled (shouldn't happen since it's
        # excluded from `tools`, but defensive against a stale/mocked
        # response in case something upstream still returns it).
        transcript.append("run_code(...) -> μη διαθέσιμο σε αυτή τη συνεδρία")

    yield ("done", {
        "summary": "Ο supervisor δεν κατάφερε να ολοκληρώσει μέσα στο όριο βημάτων.",
        "error": True,
    })
