"""
LangGraph agent: retrieve -> evaluate -> rephrase (loop, max 2 iterations)
-> generate.

Design note on streaming: LangGraph node functions return plain state
dicts, which doesn't naturally carry token-by-token output out to an
HTTP response. So the graph's `generate` node (below) produces a full,
non-streaming answer via services.llm.generate_answer, and `run_agent`
is the entry point for that fully-agentic, non-streaming path.

The SSE /query endpoint wants streaming, so it uses `agentic_retrieve`
instead: the exact same _retrieve/_evaluate/_rephrase node functions,
driven by a plain while-loop rather than the compiled graph, stopping
right before generation. The router then streams the final answer via
services.llm.stream_answer. Both paths share the same node logic, so
retrieval behavior never drifts between the streaming and non-streaming
routes — only how generation is invoked differs.
"""
from typing import TypedDict

from langgraph.graph import StateGraph, END

from services.retrieval import hybrid_search
from services.llm import yes_no, generate_answer, _openai, OPENAI_MODEL

MAX_ITERATIONS = 2


class AgentState(TypedDict):
    question: str            # current (possibly rephrased) query used for retrieval
    original_question: str   # always used for the final generation prompt
    document_filter: str | None
    chunks: list[dict]
    answer: str
    iteration: int
    should_retry: bool


def _retrieve(state: AgentState) -> AgentState:
    chunks = hybrid_search(state["question"], document_filter=state["document_filter"])
    return {**state, "chunks": chunks}


def _evaluate(state: AgentState) -> AgentState:
    if not state["chunks"]:
        return {**state, "should_retry": state["iteration"] < MAX_ITERATIONS}

    context = "\n\n".join(c["text"] for c in state["chunks"])
    prompt = (
        f"Ερώτηση: {state['question']}\n\nΑποσπάσματα:\n{context}\n\n"
        "Μπορείς να απαντήσεις στην ερώτηση βάσει αυτών των αποσπασμάτων; Απάντα YES ή NO."
    )
    can_answer = yes_no(prompt)
    should_retry = (not can_answer) and state["iteration"] < MAX_ITERATIONS
    return {**state, "should_retry": should_retry}


def _rephrase(state: AgentState) -> AgentState:
    prompt = (
        f"Η ερώτηση '{state['question']}' δεν βρήκε αρκετά σχετικά αποσπάσματα σε ένα σύστημα RAG. "
        "Επαναδιατύπωσέ την σε μία εναλλακτική διατύπωση που θα βοηθήσει την αναζήτηση να βρει "
        "πιο σχετικό περιεχόμενο. Απάντα ΜΟΝΟ με την επαναδιατυπωμένη ερώτηση, χωρίς επιπλέον σχόλια."
    )
    resp = _openai().chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=100,
    )
    rephrased = resp.choices[0].message.content.strip()
    return {**state, "question": rephrased, "iteration": state["iteration"] + 1}


def _generate(state: AgentState) -> AgentState:
    answer = generate_answer(state["original_question"], state["chunks"])
    return {**state, "answer": answer}


def _route_after_evaluate(state: AgentState) -> str:
    return "rephrase" if state["should_retry"] else "generate"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("retrieve", _retrieve)
    graph.add_node("evaluate", _evaluate)
    graph.add_node("rephrase", _rephrase)
    graph.add_node("generate", _generate)

    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "evaluate")
    graph.add_conditional_edges("evaluate", _route_after_evaluate, {
        "rephrase": "rephrase",
        "generate": "generate",
    })
    graph.add_edge("rephrase", "retrieve")
    graph.add_edge("generate", END)
    return graph.compile()


_compiled_graph = None


def get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


def _initial_state(question: str, document_filter: str | None) -> AgentState:
    return {
        "question": question,
        "original_question": question,
        "document_filter": document_filter,
        "chunks": [],
        "answer": "",
        "iteration": 0,
        "should_retry": False,
    }


def run_agent(question: str, document_filter: str | None = None) -> AgentState:
    """Full agent run (non-streaming). Returns final state, including `answer`."""
    return get_graph().invoke(_initial_state(question, document_filter))


def agentic_retrieve(question: str, document_filter: str | None = None) -> tuple[str, list[dict], int]:
    """
    Runs retrieve -> evaluate -> rephrase (same node functions as the
    graph), stopping right before generation. Returns
    (final_query_used, chunks, iterations_taken).
    """
    state = _initial_state(question, document_filter)
    state = _retrieve(state)
    state = _evaluate(state)
    while state["should_retry"]:
        state = _rephrase(state)
        state = _retrieve(state)
        state = _evaluate(state)
    return state["question"], state["chunks"], state["iteration"]
