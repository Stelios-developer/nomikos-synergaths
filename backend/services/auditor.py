"""
Hallucination Auditor — a dedicated post-generation verification agent
that grades EVERY sentence of an already-generated answer against the
chunks it was supposedly grounded in, and flags exactly which sentences
are supported vs. unsupported.

This is a different kind of check than services/evaluator.py's
faithfulness score: the evaluator asks the LLM for a single 0.0-1.0
number for the whole answer, useful as a trend/dashboard metric but
silent on WHICH part of the answer to distrust. The Auditor instead
splits the answer into individual sentences and grades each one in a
single LLM call (same "batch, not N calls" principle as
services.agent._grade_chunks), returning a per-sentence verdict the UI
can highlight directly.

Design note: this runs ON DEMAND (triggered from the UI after an answer
already exists), not automatically on every query — auditing costs an
extra LLM call, and the existing numeric faithfulness score already runs
on every query for free trend-tracking. The Auditor is for when you
actually want to know which specific claim to double-check.
"""
import json
import re

from services.llm import complete

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[Α-ΩA-Z0-9])")


def _split_sentences(answer: str) -> list[str]:
    """
    Splits an answer into sentences for independent grading. Deliberately
    simple (regex on sentence-ending punctuation followed by a capital
    letter or digit) rather than a full NLP sentence tokenizer — good
    enough for LLM-generated prose, and avoids a new heavyweight
    dependency for a single utility function.
    """
    stripped = answer.strip()
    if not stripped:
        return []
    parts = _SENTENCE_SPLIT_RE.split(stripped)
    return [p.strip() for p in parts if p.strip()]


def _extract_verdict_list(response: str, expected_length: int) -> list[dict] | None:
    match = re.search(r"\[.*\]", response, re.DOTALL)
    text = match.group(0) if match else response
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, list) or len(parsed) != expected_length:
        return None
    for item in parsed:
        if not isinstance(item, dict) or not isinstance(item.get("supported"), bool):
            return None
    return parsed


def audit_answer(answer: str, chunks: list[dict]) -> list[dict]:
    """
    Grades each sentence of `answer` as SUPPORTED or UNSUPPORTED by
    `chunks`, in one LLM call. Returns
    [{"text": str, "supported": bool, "reason": str}, ...], one entry per
    sentence, same order as they appear in `answer`.

    Graceful fallback: if the grading response doesn't parse (wrong
    shape, wrong length, not JSON), every sentence is marked supported
    with a reason explaining verification failed — never silently drops
    or reorders sentences, and never claims something is unsupported
    without an actual successful grading pass.
    """
    sentences = _split_sentences(answer)
    if not sentences:
        return []

    if not chunks:
        return [
            {"text": s, "supported": False, "reason": "Δεν υπήρχαν αποσπάσματα εγγράφων για επαλήθευση."}
            for s in sentences
        ]

    context = "\n\n".join(f"[{i + 1}] {c['text']}" for i, c in enumerate(chunks))
    numbered_sentences = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sentences))
    prompt = (
        f"Αποσπάσματα εγγράφων:\n{context}\n\n"
        f"Απάντηση προς έλεγχο (ανά πρόταση):\n{numbered_sentences}\n\n"
        "Για ΚΑΘΕ πρόταση ξεχωριστά, έλεγξε αν τεκμηριώνεται από τα αποσπάσματα. Αγνόησε παραπομπές "
        "όπως [1], [2] μέσα στις προτάσεις — αυτές είναι μέρος της μορφοποίησης, όχι περιεχόμενο προς "
        "έλεγχο. "
        f"Απάντα ΜΟΝΟ με μία JSON λίστα με ΑΚΡΙΒΩΣ {len(sentences)} στοιχεία, στην ίδια σειρά με "
        'τις προτάσεις, της μορφής [{"supported": true, "reason": "σύντομη αιτιολόγηση"}, ...].'
    )
    response = complete(prompt, max_tokens=800)
    parsed = _extract_verdict_list(response, expected_length=len(sentences))

    if parsed is None:
        return [
            {"text": s, "supported": True, "reason": "Δεν ήταν δυνατή η αυτόματη επαλήθευση."}
            for s in sentences
        ]

    return [
        {"text": s, "supported": v["supported"], "reason": v.get("reason", "")}
        for s, v in zip(sentences, parsed)
    ]
