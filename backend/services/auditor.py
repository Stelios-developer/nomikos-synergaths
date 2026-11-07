"""
Hallucination Auditor — a dedicated post-generation verification agent
that asks a model to assess sentences against source chunks. A positive model
verdict is not independent verification and always requires human review.

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

_SENTENCE_BOUNDARY_RE = re.compile(r"[.!?]\s+")
_MAX_AUDIT_UNITS = 30


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
    parts = []
    for line in stripped.splitlines():
        start = 0
        for match in _SENTENCE_BOUNDARY_RE.finditer(line):
            end = match.end()
            if end < len(line) and ("Α" <= line[end] <= "Ω" or "A" <= line[end] <= "Z" or "0" <= line[end] <= "9"):
                parts.append(line[start:match.start() + 1].strip())
                start = end
        parts.append(line[start:].strip())
    return [part for part in parts if part]


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
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("supported"), bool)
            or not isinstance(item.get("reason"), str)
            or not item["reason"].strip()
        ):
            return None
    return parsed


def audit_answer(answer: str, chunks: list[dict]) -> list[dict]:
    """
    Assesses each sentence of `answer` against `chunks` in one LLM call. Returns
    [{"text": str, "supported": bool, "reason": str}, ...], one entry per
    sentence, same order as they appear in `answer`.

    Fail closed: positive model verdicts and unavailable or malformed responses
    are unverifiable without human source review, never confirmed support.
    """
    sentences = _split_sentences(answer)
    if not sentences:
        return []

    if not chunks:
        return [
            {"text": s, "supported": False, "reason": "Δεν υπήρχαν αποσπάσματα εγγράφων για επαλήθευση.", "verification_unavailable": True}
            for s in sentences
        ]

    # Bound provider output: never turn an incomplete verdict into a pass.
    if len(sentences) > _MAX_AUDIT_UNITS:
        return [
            {"text": s, "supported": False, "reason": "Η απάντηση είναι πολύ μεγάλη για αυτόματο έλεγχο· ελέγξτε την πηγή.", "verification_unavailable": True}
            for s in sentences
        ]

    context = "\n\n".join(f"[{i + 1}] {c['text']}" for i, c in enumerate(chunks))
    numbered_sentences = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sentences))
    prompt = (
        f"Αποσπάσματα εγγράφων:\n{context}\n\n"
        f"Απάντηση προς έλεγχο (ανά πρόταση):\n{numbered_sentences}\n\n"
        "Για ΚΑΘΕ πρόταση ξεχωριστά, έλεγξε αν τεκμηριώνεται από τα αποσπάσματα. Αγνόησε παραπομπές "
        "όπως [1], [2] μέσα στις προτάσεις — αυτές είναι μέρος της μορφοποίησης, όχι περιεχόμενο προς "
        "έλεγχο. Μια πρόταση τεκμηριώνεται μόνο αν κάθε ισχυρισμός της υποστηρίζεται ρητά. "
        "Διάκρινε υπεύθυνο, εγκρίνοντα, ελεγκτή και παραλήπτη ενημέρωσης: η έγκριση δεν σημαίνει "
        "ευθύνη εκτέλεσης. Για ανακριβή ή μη ρητό ρόλο απάντησε false. "
        f"Απάντα ΜΟΝΟ με μία JSON λίστα με ΑΚΡΙΒΩΣ {len(sentences)} στοιχεία, στην ίδια σειρά με "
        'τις προτάσεις, της μορφής [{"supported": true, "reason": "σύντομη αιτιολόγηση"}, ...].'
    )
    try:
        response = complete(prompt, max_tokens=800)
        parsed = _extract_verdict_list(response, expected_length=len(sentences))
    except Exception:
        parsed = None

    if parsed is None:
        return [
            {"text": s, "supported": False, "reason": "Δεν ήταν δυνατή η αυτόματη επαλήθευση.", "verification_unavailable": True}
            for s in sentences
        ]

    results = []
    for sentence, verdict in zip(sentences, parsed):
        if verdict["supported"]:
            results.append({"text": sentence, "supported": False, "reason": "Το AI εντόπισε πιθανή υποστήριξη, αλλά απαιτείται ανθρώπινος έλεγχος στην αρχική πηγή.", "verification_unavailable": True})
        else:
            results.append({"text": sentence, "supported": verdict["supported"], "reason": verdict["reason"]})
    return results
