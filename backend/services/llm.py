"""
Thin wrapper around OpenAI / Anthropic so the rest of the app (agent,
evaluator, simple query endpoint) doesn't care which provider is active.
Switch via LLM_PROVIDER=openai|anthropic in .env.
"""
import os

from openai import OpenAI
from anthropic import Anthropic

OPENAI_MODEL = "gpt-4o-mini"
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = (
    "Απάντα ΜΟΝΟ βάσει των παρακάτω αποσπασμάτων εγγράφων (chunks). "
    "Αν η απάντηση δεν βρίσκεται σε αυτά, πες ρητά ότι δεν βρέθηκε στα έγγραφα. "
    "Μην χρησιμοποιείς εξωτερική γνώση. Αναφέρσου στις πηγές σου με [1], [2] κ.ο.κ., "
    "αντιστοιχώντας στη σειρά των chunks όπως δίνονται."
)

_openai_client = None
_anthropic_client = None


def _openai() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _openai_client


def _anthropic() -> Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _anthropic_client


def _build_context(chunks: list[dict]) -> str:
    parts = []
    for i, c in enumerate(chunks, start=1):
        parts.append(f"[{i}] (source: {c['filename']}, page {c['page_number']})\n{c['text']}")
    return "\n\n".join(parts)


def provider() -> str:
    return os.getenv("LLM_PROVIDER", "openai").lower()


def generate_answer(question: str, chunks: list[dict]) -> str:
    """Single-shot, non-streaming generation. Used by the basic /query endpoint
    (step 6) before the LangGraph agent (step 10) and streaming (step 8) land."""
    context = _build_context(chunks)
    user_message = f"Έγγραφα:\n{context}\n\nΕρώτηση: {question}"

    if provider() == "anthropic":
        resp = _anthropic().messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        return resp.content[0].text

    resp = _openai().chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    )
    return resp.choices[0].message.content


def stream_answer(question: str, chunks: list[dict]):
    """
    Token-by-token generator, used by the SSE /query endpoint (step 8) and
    the LangGraph agent's generate node (step 10). Yields plain text pieces
    as they arrive from the provider.
    """
    context = _build_context(chunks)
    user_message = f"Έγγραφα:\n{context}\n\nΕρώτηση: {question}"

    if provider() == "anthropic":
        with _anthropic().messages.stream(
            model=ANTHROPIC_MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            for text in stream.text_stream:
                yield text
        return

    stream = _openai().chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


def yes_no(prompt: str) -> bool:
    """Cheap YES/NO judgment call, used by the LangGraph evaluate node (step 10)
    and evaluator (step 12). Defaults to gpt-4o-mini regardless of LLM_PROVIDER
    per the brief ('evaluation calls use gpt-4o-mini — cheap')."""
    resp = _openai().chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=5,
    )
    answer = resp.choices[0].message.content.strip().upper()
    return answer.startswith("YES")


def score(prompt: str) -> float:
    """Asks for a 0.0-1.0 score, used by evaluator.py (step 12)."""
    resp = _openai().chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt + "\n\nRespond with ONLY a number between 0.0 and 1.0."}],
        max_tokens=10,
    )
    text = resp.choices[0].message.content.strip()
    try:
        return max(0.0, min(1.0, float(text)))
    except ValueError:
        return 0.5
