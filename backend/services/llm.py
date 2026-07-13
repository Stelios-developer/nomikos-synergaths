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

# Conversation history is only used to interpret follow-ups (coreference,
# "the second point", etc.) — it must never become a second source of
# facts. The system prompt says so explicitly so multi-turn chats don't
# quietly loosen the document-only guarantee.
SYSTEM_PROMPT = (
    "Απάντα ΜΟΝΟ βάσει των παρακάτω αποσπασμάτων εγγράφων (chunks). "
    "Αν η απάντηση δεν βρίσκεται σε αυτά, πες ρητά ότι δεν βρέθηκε στα έγγραφα. "
    "Μην χρησιμοποιείς εξωτερική γνώση. Αναφέρσου στις πηγές σου με [1], [2] κ.ο.κ., "
    "αντιστοιχώντας στη σειρά των chunks όπως δίνονται. "
    "Το ιστορικό της συνομιλίας (αν υπάρχει) είναι μόνο για να καταλαβαίνεις σε τι "
    "αναφέρεται μια follow-up ερώτηση (π.χ. 'αυτό', 'το δεύτερο σημείο') — ποτέ μην "
    "αντλείς γεγονότα από εκεί, μόνο από τα chunks της τρέχουσας ερώτησης."
)

# How many prior turns to include in the generation prompt. Kept small so
# a long chat session doesn't blow up token usage/cost per message.
MAX_HISTORY_MESSAGES = 10

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


def _history_messages(history: list[dict] | None) -> list[dict]:
    """Normalizes + truncates prior turns to plain {role, content} dicts,
    the shape both the OpenAI and Anthropic SDKs accept directly."""
    if not history:
        return []
    trimmed = history[-MAX_HISTORY_MESSAGES:]
    return [{"role": h["role"], "content": h["content"]} for h in trimmed]


def provider() -> str:
    return os.getenv("LLM_PROVIDER", "openai").lower()


def generate_answer(question: str, chunks: list[dict], history: list[dict] | None = None) -> str:
    """Single-shot, non-streaming generation. Used by the LangGraph agent's
    internal generate node (services/agent.py)."""
    context = _build_context(chunks)
    user_message = f"Έγγραφα:\n{context}\n\nΕρώτηση: {question}"
    history_msgs = _history_messages(history)

    if provider() == "anthropic":
        resp = _anthropic().messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[*history_msgs, {"role": "user", "content": user_message}],
        )
        return resp.content[0].text

    resp = _openai().chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            *history_msgs,
            {"role": "user", "content": user_message},
        ],
    )
    return resp.choices[0].message.content


def stream_answer(question: str, chunks: list[dict], history: list[dict] | None = None):
    """
    Token-by-token generator, used by the SSE /query endpoint. Yields
    plain text pieces as they arrive from the provider. `history` is the
    prior turns of the conversation (role/content dicts), used purely to
    resolve follow-up questions — see SYSTEM_PROMPT.
    """
    context = _build_context(chunks)
    user_message = f"Έγγραφα:\n{context}\n\nΕρώτηση: {question}"
    history_msgs = _history_messages(history)

    if provider() == "anthropic":
        with _anthropic().messages.stream(
            model=ANTHROPIC_MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[*history_msgs, {"role": "user", "content": user_message}],
        ) as stream:
            for text in stream.text_stream:
                yield text
        return

    stream = _openai().chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            *history_msgs,
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
