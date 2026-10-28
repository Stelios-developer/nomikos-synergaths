"""
Thin wrapper around OpenAI / Anthropic so the rest of the app (agent,
evaluator, query endpoint) doesn't care which provider is active.
Switch via LLM_PROVIDER=openai|anthropic in .env — every LLM call in the
app (generation, the agent's evaluate/rephrase/condense steps, and the
faithfulness/relevance evaluator) follows that one setting.

Every provider call in this module is wrapped with a tracing span
(services.observability.traced_span) and reports its token usage/cost
(record_llm_usage) — this is the single choke point all LLM calls in the
app pass through, so instrumenting it here covers every service (agent,
advisory panel, debate, multi-hop research, action agent) for free.
"""
import json
import os
import time

from openai import OpenAI
from anthropic import Anthropic


from opentelemetry import trace as _otel_trace
from opentelemetry.trace import Status, StatusCode
from services.observability import traced_span, record_llm_usage, _tracer, get_request_id
from services.budget import remaining

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
        _openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), max_retries=0, timeout=120)
    return _openai_client


def _anthropic() -> Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=0, timeout=120)
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


# Usage extraction is deliberately defensive: test doubles (MagicMock) and
# occasional provider responses without usage info must never crash a real
# request over what's purely a cost-accounting side channel. Any failure
# just means this call is undercounted as 0/0 tokens.
def _anthropic_usage(resp) -> tuple[int, int]:
    try:
        return int(resp.usage.input_tokens), int(resp.usage.output_tokens)
    except Exception:
        return 0, 0


def _openai_usage(resp) -> tuple[int, int]:
    try:
        return int(resp.usage.prompt_tokens), int(resp.usage.completion_tokens)
    except Exception:
        return 0, 0


def complete(prompt: str, max_tokens: int = 100) -> str:
    """
    Single-turn, no-system-prompt completion, following LLM_PROVIDER just
    like generate_answer/stream_answer. Used for every small utility call
    in the app that doesn't need the full document-grounded system prompt:
    the agent's evaluate (yes/no), rephrase, and condense-question steps
    (services/agent.py), and the faithfulness/relevance evaluator
    (services/evaluator.py).
    """
    start = time.perf_counter()
    with traced_span("llm.complete", provider=provider()):
        if provider() == "anthropic":
            resp = _anthropic().messages.create(
                timeout=remaining(),
                model=ANTHROPIC_MODEL,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text.strip()
            in_tok, out_tok = _anthropic_usage(resp)
            record_llm_usage(ANTHROPIC_MODEL, "complete", in_tok, out_tok, (time.perf_counter() - start) * 1000)
            return text

        resp = _openai().chat.completions.create(
            timeout=remaining(),
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
        text = resp.choices[0].message.content.strip()
        in_tok, out_tok = _openai_usage(resp)
        record_llm_usage(OPENAI_MODEL, "complete", in_tok, out_tok, (time.perf_counter() - start) * 1000)
        return text


def generate_with_system(
    question: str, chunks: list[dict], system_prompt: str, history: list[dict] | None = None
) -> str:
    """
    Single-shot, non-streaming generation with a caller-supplied system
    prompt, instead of the hardcoded document-QA SYSTEM_PROMPT. The
    underlying provider calls are otherwise identical to generate_answer
    (which delegates here), so this is a strict generalization — not a
    behavior change for the default case.

    Used directly by the Advisory Panel (services/advisory_panel.py) to
    run several differently-instructed advisor personas over the exact
    same retrieved chunks.
    """
    context = _build_context(chunks)
    user_message = f"Έγγραφα:\n{context}\n\nΕρώτηση: {question}"
    history_msgs = _history_messages(history)

    start = time.perf_counter()
    with traced_span("llm.generate_with_system", provider=provider()):
        if provider() == "anthropic":
            resp = _anthropic().messages.create(
                timeout=remaining(),
                model=ANTHROPIC_MODEL,
                max_tokens=1024,
                system=system_prompt,
                messages=[*history_msgs, {"role": "user", "content": user_message}],
            )
            in_tok, out_tok = _anthropic_usage(resp)
            record_llm_usage(ANTHROPIC_MODEL, "generate_with_system", in_tok, out_tok, (time.perf_counter() - start) * 1000)
            return resp.content[0].text

        resp = _openai().chat.completions.create(
            timeout=remaining(),
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                *history_msgs,
                {"role": "user", "content": user_message},
            ],
        )
        in_tok, out_tok = _openai_usage(resp)
        record_llm_usage(OPENAI_MODEL, "generate_with_system", in_tok, out_tok, (time.perf_counter() - start) * 1000)
        return resp.choices[0].message.content


def generate_answer(question: str, chunks: list[dict], history: list[dict] | None = None) -> str:
    """Single-shot, non-streaming generation. Used by the LangGraph agent's
    internal generate node (services/agent.py)."""
    return generate_with_system(question, chunks, SYSTEM_PROMPT, history)


def stream_answer(question: str, chunks: list[dict], history: list[dict] | None = None):
    """
    Token-by-token generator, used by the SSE /query endpoint. Yields
    plain text pieces as they arrive from the provider. `history` is the
    prior turns of the conversation (role/content dicts), used purely to
    resolve follow-up questions — see SYSTEM_PROMPT.

    Usage/cost is only knowable once the stream is fully drained (the
    provider reports it in the final chunk/message), so it's recorded
    after the last token is yielded rather than up front.
    """
    context = _build_context(chunks)
    user_message = f"Έγγραφα:\n{context}\n\nΕρώτηση: {question}"
    history_msgs = _history_messages(history)

    start = time.perf_counter()

    # Use a manually managed span instead of the `with traced_span(...)` context
    # manager here. stream_answer is a synchronous generator: FastAPI consumes it
    # inside an async streaming response, which means the `yield` resumes in a
    # different contextvars Context than where the span was opened. OpenTelemetry
    # stores the attach token in a ContextVar, so trying to detach it from the
    # wrong context raises:
    #   ValueError: <Token ...> was created in a different Context
    # Manually starting/ending the span avoids any context-attach/detach entirely.
    span = _tracer().start_span("llm.stream_answer")
    span.set_attribute("request_id", get_request_id())
    span.set_attribute("provider", provider())
    try:
        if provider() == "anthropic":
            with _anthropic().messages.stream(
                timeout=remaining(),
                model=ANTHROPIC_MODEL,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[*history_msgs, {"role": "user", "content": user_message}],
            ) as stream:
                for text in stream.text_stream:
                    remaining()
                    yield text
                try:
                    final_message = stream.get_final_message()
                    in_tok, out_tok = _anthropic_usage(final_message)
                except Exception:
                    in_tok, out_tok = 0, 0
                record_llm_usage(ANTHROPIC_MODEL, "stream_answer", in_tok, out_tok, (time.perf_counter() - start) * 1000)

        else:
            stream = _openai().chat.completions.create(
                timeout=remaining(),
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    *history_msgs,
                    {"role": "user", "content": user_message},
                ],
                stream=True,
                stream_options={"include_usage": True},
            )
            in_tok, out_tok = 0, 0
            try:
                for chunk in stream:
                    remaining()
                    if chunk.choices:
                        delta = chunk.choices[0].delta.content
                        if delta:
                            yield delta
                    usage = getattr(chunk, "usage", None)
                    if usage:
                        in_tok, out_tok = _openai_usage(chunk)
            finally:
                # Generator.close(), deadline expiry and provider failures must
                # all release the local HTTP connection, including partial reads.
                stream.close()
            record_llm_usage(OPENAI_MODEL, "stream_answer", in_tok, out_tok, (time.perf_counter() - start) * 1000)
    except Exception as exc:
        span.record_exception(RuntimeError(type(exc).__name__))
        span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
        raise
    finally:
        span.end()























def yes_no(prompt: str) -> bool:
    """Cheap YES/NO judgment call, used by the LangGraph evaluate node.
    Follows LLM_PROVIDER via complete()."""
    answer = complete(prompt, max_tokens=5).upper()
    return answer.startswith("YES")


def score(prompt: str) -> float:
    """Asks for a 0.0-1.0 score, used by evaluator.py. Follows
    LLM_PROVIDER via complete()."""
    text = complete(prompt + "\n\nRespond with ONLY a number between 0.0 and 1.0.", max_tokens=10)
    try:
        return max(0.0, min(1.0, float(text)))
    except ValueError:
        return 0.5


def _anthropic_tool_schema(tools: list[dict]) -> list[dict]:
    return [
        {"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
        for t in tools
    ]


def _openai_tool_schema(tools: list[dict]) -> list[dict]:
    return [
        {"type": "function", "function": {
            "name": t["name"], "description": t["description"], "parameters": t["parameters"],
        }}
        for t in tools
    ]


def call_with_tools(prompt: str, tools: list[dict], max_tokens: int = 1000) -> dict:
    """
    Single-turn, provider-aware tool-calling request — used by the Action
    Supervisor when it selects an allowed document-analysis tool: the
    model itself decides, via the provider's native tool-use mechanism,
    whether to invoke a tool (and which one, with what arguments) or just
    respond with text.

    Each call in the agent's ReAct loop re-sends the full running
    transcript as one text block (built by the caller into `prompt`)
    rather than maintaining a stateful native tool-conversation across
    turns. That's a deliberate simplification: it keeps this function
    provider-agnostic and easy to reason about/test, at the cost of a
    slightly larger prompt on later iterations — acceptable given the
    loop's small iteration cap.

    Returns {"tool_call": {"name": str, "input": dict} | None, "text": str}.
    tool_call is None when the model responded with plain text instead of
    invoking a tool — the ReAct loop treats that the same as an explicit
    "finish" call.
    """
    start = time.perf_counter()
    with traced_span("llm.call_with_tools", provider=provider()):
        if provider() == "anthropic":
            resp = _anthropic().messages.create(
                timeout=remaining(),
                model=ANTHROPIC_MODEL,
                max_tokens=max_tokens,
                tools=_anthropic_tool_schema(tools),
                messages=[{"role": "user", "content": prompt}],
            )
            in_tok, out_tok = _anthropic_usage(resp)
            record_llm_usage(ANTHROPIC_MODEL, "call_with_tools", in_tok, out_tok, (time.perf_counter() - start) * 1000)

            tool_use_blocks = [b for b in resp.content if b.type == "tool_use"]
            text_blocks = [b.text for b in resp.content if b.type == "text"]
            if tool_use_blocks:
                block = tool_use_blocks[0]
                return {"tool_call": {"name": block.name, "input": block.input}, "text": "\n".join(text_blocks)}
            return {"tool_call": None, "text": "\n".join(text_blocks)}

        resp = _openai().chat.completions.create(
            timeout=remaining(),
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            tools=_openai_tool_schema(tools),
            max_tokens=max_tokens,
        )
        in_tok, out_tok = _openai_usage(resp)
        record_llm_usage(OPENAI_MODEL, "call_with_tools", in_tok, out_tok, (time.perf_counter() - start) * 1000)

        msg = resp.choices[0].message
        if msg.tool_calls:
            tc = msg.tool_calls[0]
            return {"tool_call": {"name": tc.function.name, "input": json.loads(tc.function.arguments)}, "text": msg.content or ""}
        return {"tool_call": None, "text": msg.content or ""}
