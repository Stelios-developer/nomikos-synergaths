"""
Multi-hop Research Agent — decomposes a compound question into
standalone sub-questions, runs retrieval + Corrective RAG grading for
EACH sub-question CONCURRENTLY (reusing services.agent._grade_chunks, so
the same per-chunk relevance filtering applies here too), merges the
results, and streams one final answer synthesized across all of them.

Why this matters for RAG quality specifically: the existing agentic
pipeline (services/agent.py) issues exactly ONE retrieval per question
(with up to 2 rephrase-retries if it comes back empty). That's fine for
atomic questions, but a compound question like "what's the R&D deduction
rate, and how does it compare to the equipment depreciation rate, and
which is better for a company with this profile?" packs 2-3 distinct
information needs into a single query — one embedding of the whole
question dilutes each sub-need's signal in vector search, and BM25 has
no way to window over just one clause either. Decomposing first and
retrieving per sub-question gives each one its own clean, un-diluted
search instead of one blurred one.

Design note on concurrency: sub-questions are decomposed once, then
retrieved+graded independently — no sub-question depends on another's
result — so they run through a shared ThreadPoolExecutor, the same
pattern used by the Advisory Panel for the same
underlying reason: no ordering dependency, no reason to force serial
execution.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from services.agent import _grade_chunks
from services.retrieval import hybrid_search
from services.llm import complete, stream_answer
from services.evaluator import evaluate_and_store
from services.observability import submit_with_context
from services.session_scope import DEFAULT_SESSION_ID

MAX_SUBQUESTIONS = 4

DECOMPOSE_INSTRUCTIONS = (
    "Ανάλυσε την παρακάτω ερώτηση: αν περιέχει πάνω από ένα διακριτό ερώτημα/υπο-θέμα, σπάσ' την σε "
    f"ΑΥΤΟΤΕΛΗ sub-questions (το πολύ {MAX_SUBQUESTIONS}), καθένα από τα οποία βγάζει νόημα μόνο του "
    "και είναι χρήσιμο για ξεχωριστή αναζήτηση σε έγγραφα. Αν η ερώτηση είναι ήδη ατομική/απλή, "
    "επίστρεψέ την ως το ΜΟΝΑΔΙΚΟ στοιχείο μιας λίστας ενός στοιχείου. "
    'Απάντα ΜΟΝΟ με μία JSON λίστα από strings, π.χ. ["πρώτη υποερώτηση", "δεύτερη υποερώτηση"].'
)


def _decompose(question: str) -> list[str]:
    """
    Splits a compound question into standalone sub-questions in ONE LLM
    call. Falls back to treating the question as atomic (a list of just
    itself) on any parse failure or out-of-bounds result — the same
    graceful-degradation philosophy as services.agent._grade_chunks:
    never let a parsing glitch break the request, just fall back to the
    simpler/coarser behavior.
    """
    prompt = f"{DECOMPOSE_INSTRUCTIONS}\n\nΕρώτηση: {question}"
    response = complete(prompt, max_tokens=300)
    match = re.search(r"\[.*\]", response, re.DOTALL)
    text = match.group(0) if match else response
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return [question]
    if (
        isinstance(parsed, list)
        and 1 <= len(parsed) <= MAX_SUBQUESTIONS
        and all(isinstance(x, str) and x.strip() for x in parsed)
    ):
        return parsed
    return [question]


def _research_subquestion(sub_question: str, document_filter: str | None, session_id: str = DEFAULT_SESSION_ID) -> list[dict]:
    """Retrieval + Corrective RAG grading for ONE sub-question, reusing
    the exact same _grade_chunks used by the main agentic pipeline."""
    chunks = hybrid_search(sub_question, document_filter=document_filter, session_id=session_id)
    if not chunks:
        return chunks
    flags = _grade_chunks(sub_question, chunks)
    relevant = [c for c, keep in zip(chunks, flags) if keep]
    # If grading drops everything, fall back to the unfiltered batch —
    # same tradeoff services.agent._evaluate makes on give-up: a
    # sub-question contributing some noisy context beats contributing
    # nothing at all to the final synthesis.
    return relevant if relevant else chunks


def run_research_stream(
    question: str,
    document_filter: str | None = None,
    history: list[dict] | None = None,
    session_id: str = DEFAULT_SESSION_ID,
):
    """
    Generator over the Research Agent's full trace. Yields:
      ("subquestions", [str, ...])                                 — once, right after decomposition
      ("subretrieval", {"sub_question": str, "citations": [...]})  — once per sub-question, in
                                                                       COMPLETION order (concurrent —
                                                                       not a fixed sequence)
      ("token", str)                                                — final synthesized answer, streaming
      ("done", {"citations": [...]})                                — exactly once, last
    """
    subquestions = _decompose(question)
    yield ("subquestions", subquestions)

    chunks_by_subquestion: dict[str, list[dict]] = {}

    if len(subquestions) == 1:
        # Trivial/atomic case: no concurrency machinery needed for a
        # single sub-question.
        sq = subquestions[0]
        chunks_by_subquestion[sq] = _research_subquestion(sq, document_filter, session_id)
        yield ("subretrieval", {
            "sub_question": sq,
            "citations": [
                {"filename": c["filename"], "page": c["page_number"], "text": c["text"]}
                for c in chunks_by_subquestion[sq]
            ],
        })
    else:
        with ThreadPoolExecutor(max_workers=len(subquestions)) as executor:
            future_to_sq = {
                submit_with_context(executor, _research_subquestion, sq, document_filter, session_id): sq
                for sq in subquestions
            }
            for future in as_completed(future_to_sq):
                sq = future_to_sq[future]
                try:
                    sq_chunks = future.result()
                except Exception:
                    sq_chunks = []
                chunks_by_subquestion[sq] = sq_chunks
                yield ("subretrieval", {
                    "sub_question": sq,
                    "citations": [
                        {"filename": c["filename"], "page": c["page_number"], "text": c["text"]}
                        for c in sq_chunks
                    ],
                })

    # Merge in stable sub-question order, deduping repeated chunks (the
    # same page can legitimately answer more than one sub-question).
    all_chunks: list[dict] = []
    seen: set[tuple] = set()
    for sq in subquestions:
        for c in chunks_by_subquestion[sq]:
            key = (c["filename"], c["page_number"], c["chunk_index"])
            if key not in seen:
                seen.add(key)
                all_chunks.append(c)

    if not all_chunks:
        yield ("token", "Δεν βρέθηκαν σχετικά αποσπάσματα στα έγγραφα για κανένα από τα υπο-ερωτήματα.")
        yield ("done", {"citations": []})
        return

    full_answer = ""
    for token in stream_answer(question, all_chunks, history):
        full_answer += token
        yield ("token", token)

    citations = [
        {"filename": c["filename"], "page": c["page_number"], "text": c["text"]}
        for c in all_chunks
    ]

    try:
        evaluate_and_store(question, full_answer, all_chunks, history)
    except Exception:
        pass

    yield ("done", {"citations": citations})
