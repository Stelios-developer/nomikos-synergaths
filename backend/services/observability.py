"""
Observability: structured logging, per-request cost/token tracking, and
distributed tracing — the three things you need to answer "why did this
specific request behave the way it did?" in production, none of which a
plain print statement or the /evaluation dashboard (services/evaluator.py,
which grades answer quality, not system health) can give you.

Three pieces, all threaded through the single request lifecycle:

1. Structured JSON logging — every log line is one JSON object (timestamp,
   level, message, request_id, + arbitrary context) instead of a free-text
   string, so it's grep/jq-able and ships cleanly to any log aggregator
   (Datadog, CloudWatch, Loki) without a parsing layer in front of it.

2. Token/cost accounting — every LLM call in the app funnels through
   services/llm.py, which is instrumented here (see record_llm_usage) to
   log its token counts and compute a cost in USD from MODEL_PRICING. Costs
   are accumulated per-request (via a contextvar) and persisted to SQLite
   so /observability/summary can answer "what is this app costing me"
   instead of that being invisible until the provider's monthly invoice.

3. Tracing — a real OpenTelemetry TracerProvider (not a hand-rolled
   substitute). Every HTTP request gets a root span; every LLM call gets a
   child span with model/token/cost attributes. With no exporter configured
   this is a zero-cost no-op; point OTEL_EXPORTER_OTLP_ENDPOINT at a
   collector (Jaeger, Honeycomb, Grafana Tempo, etc.) and the exact same
   code produces a full trace tree for every request with no further
   changes — that's the point of instrumenting against the vendor-neutral
   OTel API rather than a specific vendor SDK.

LangSmith is deliberately NOT wired up here as code: LangGraph (used by
services/agent.py) auto-instruments itself the moment LANGCHAIN_TRACING_V2=
true / LANGCHAIN_API_KEY are set in the environment — see .env.example.
That's a genuine zero-code integration, not a gap.
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import sqlite3
import uuid
from concurrent.futures import Executor, Future
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace import Status, StatusCode

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Request-scoped context
# ---------------------------------------------------------------------------
# usage_accumulator_var holds a list (not None) only while a request is in
# flight (set by main.py's middleware); record_llm_usage appends to it so
# the middleware can sum total tokens/cost once the request finishes. It
# defaults to None so calling llm.py functions outside a request (scripts,
# tests) never crashes — usage is simply not accumulated/attributed.
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
usage_accumulator_var: contextvars.ContextVar[list[dict] | None] = contextvars.ContextVar(
    "usage_accumulator", default=None
)


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def get_request_id() -> str:
    return request_id_var.get() or "no-request"


# ---------------------------------------------------------------------------
# Structured JSON logging
# ---------------------------------------------------------------------------
class JsonFormatter(logging.Formatter):
    """Renders each log record as one JSON line. Extra context passed via
    `logger.info(msg, extra={"context": {...}})` is merged in flat so it's
    directly queryable (e.g. `jq 'select(.total_cost_usd > 0.01)'`)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": get_request_id(),
        }
        context = getattr(record, "context", None)
        if isinstance(context, dict):
            payload.update(context)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


_logging_configured = False


def configure_logging() -> None:
    """Idempotent — safe to call from main.py at import time even though
    module import (and therefore this call) only happens once per process,
    and safe to call again from tests without duplicating handlers."""
    global _logging_configured
    logger = logging.getLogger("app")
    if _logging_configured:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    logger.propagate = False
    _logging_configured = True


logger = logging.getLogger("app")


# ---------------------------------------------------------------------------
# OpenTelemetry tracing
# ---------------------------------------------------------------------------
_tracing_configured = False


def configure_tracing() -> None:
    """
    Sets up a real OTel TracerProvider once per process.

    No exporter is attached unless explicitly configured, so tracing is a
    genuine no-op by default (no console spam in tests/local dev, no
    network calls with nowhere to send them):
      - OTEL_EXPORTER_OTLP_ENDPOINT set -> spans ship to that OTLP collector.
      - OTEL_CONSOLE_EXPORT=true -> spans print to stdout (handy to see the
        span tree locally without standing up a collector).
    Both can be enabled at once.
    """
    global _tracing_configured
    if _tracing_configured:
        return
    provider = TracerProvider(
        resource=Resource.create({"service.name": "document-rag-assistant-api"})
    )

    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint:
        # Imported lazily: the OTLP exporter package is an optional extra
        # (requirements.txt includes it, but this keeps the import failure
        # mode local to "you set the endpoint but not the package").
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))

    if os.getenv("OTEL_CONSOLE_EXPORT", "false").lower() == "true":
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _tracing_configured = True


def _tracer():
    return trace.get_tracer("document-rag-assistant")


@contextmanager
def traced_span(name: str, **attributes: Any):
    """
    Thin wrapper around `tracer.start_as_current_span` that:
      - tags every span with the current request_id automatically, so a
        trace can always be joined back to its request's log lines.
      - records exceptions on the span and marks it ERROR before re-raising,
        instead of the span silently reporting success.
    """
    span = _tracer().start_span(name)
    span.set_attribute("request_id", get_request_id())
    for key, value in attributes.items():
        if value is not None:
            span.set_attribute(key, value)
    try:
        with trace.use_span(span, end_on_exit=True):
            yield span
    except Exception as exc:
        span.record_exception(exc)
        span.set_status(Status(StatusCode.ERROR, str(exc)))
        raise


def submit_with_context(executor: Executor, fn: Callable[..., T], *args: Any, **kwargs: Any) -> Future:
    """
    concurrent.futures.ThreadPoolExecutor does NOT copy the calling thread's
    contextvars into worker threads by default — a plain `executor.submit`
    would silently drop request_id/usage-accumulator/OTel-span context, so
    concurrent LLM calls (Advisory Panel, Debate Agents, Multi-hop Research)
    would still work, but their cost wouldn't be attributed to the parent
    request and their spans wouldn't nest under the parent trace.

    Used at every ThreadPoolExecutor.submit call site instead of calling it
    directly — see services/advisory_panel.py, services/debate.py,
    services/multihop.py.
    """
    ctx = contextvars.copy_context()
    return executor.submit(ctx.run, fn, *args, **kwargs)


# ---------------------------------------------------------------------------
# Token/cost accounting
# ---------------------------------------------------------------------------
# USD per 1,000,000 tokens. Verified against provider pricing pages as of
# July 2026 — update alongside ANTHROPIC_MODEL/OPENAI_MODEL in
# services/llm.py if the default model changes. Unknown models fall back to
# a $0 rate (logged once as a warning) rather than crashing a request.
#
# claude-sonnet-5 is at INTRODUCTORY pricing ($2.00/$10.00) through
# 2026-08-31; standard pricing ($3.00/$15.00) starts 2026-09-01 — bump this
# if the default model/date ever changes.
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},
    "claude-opus-4-8": {"input": 5.00, "output": 25.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
}

_unknown_model_warned: set[str] = set()


def _cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = MODEL_PRICING.get(model)
    if rates is None:
        if model not in _unknown_model_warned:
            logger.warning(
                "unknown_model_pricing",
                extra={"context": {"model": model, "note": "cost will report as 0.0 until MODEL_PRICING is updated"}},
            )
            _unknown_model_warned.add(model)
        return 0.0
    return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000


def record_llm_usage(
    model: str, call_name: str, input_tokens: int, output_tokens: int, latency_ms: float
) -> dict[str, Any]:
    """
    Call once per completed LLM API call (services/llm.py) with whatever
    token counts the provider's response reported. Logs a structured
    `llm_call` event and, if a request is in flight (see main.py's
    middleware), appends to that request's running cost/token total.
    """
    cost = round(_cost_usd(model, input_tokens, output_tokens), 6)
    record = {
        "model": model,
        "call_name": call_name,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost,
        "latency_ms": round(latency_ms, 1),
    }
    logger.info("llm_call", extra={"context": record})

    accumulator = usage_accumulator_var.get()
    if accumulator is not None:
        accumulator.append(record)
    return record


def get_request_usage_summary() -> dict[str, Any]:
    """Sums the current request's accumulated LLM calls. Safe to call even
    with no request in flight (returns all-zero totals)."""
    calls = usage_accumulator_var.get() or []
    return {
        "total_input_tokens": sum(c["input_tokens"] for c in calls),
        "total_output_tokens": sum(c["output_tokens"] for c in calls),
        "total_cost_usd": round(sum(c["cost_usd"] for c in calls), 6),
        "calls": calls,
    }


# ---------------------------------------------------------------------------
# Persistence — one row per completed HTTP request (SQLite, same pattern as
# services/evaluator.py's evaluations table).
# ---------------------------------------------------------------------------
OBS_DB_PATH = os.getenv("OBSERVABILITY_DB_PATH", "./observability.db")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(OBS_DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS request_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL,
            method TEXT NOT NULL,
            path TEXT NOT NULL,
            status_code INTEGER NOT NULL,
            duration_ms REAL NOT NULL,
            input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            cost_usd REAL NOT NULL,
            llm_calls INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    return conn


def record_request_metrics(
    request_id: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    summary: dict[str, Any],
) -> None:
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO request_metrics "
            "(request_id, method, path, status_code, duration_ms, input_tokens, output_tokens, "
            "cost_usd, llm_calls, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                request_id,
                method,
                path,
                status_code,
                round(duration_ms, 1),
                summary["total_input_tokens"],
                summary["total_output_tokens"],
                summary["total_cost_usd"],
                len(summary["calls"]),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_recent_requests(limit: int = 50) -> list[dict[str, Any]]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT request_id, method, path, status_code, duration_ms, input_tokens, "
            "output_tokens, cost_usd, llm_calls, created_at FROM request_metrics "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()

    columns = [
        "request_id", "method", "path", "status_code", "duration_ms",
        "input_tokens", "output_tokens", "cost_usd", "llm_calls", "created_at",
    ]
    return [dict(zip(columns, row)) for row in rows]


def get_summary() -> dict[str, Any]:
    conn = _get_conn()
    try:
        total, total_cost, total_in, total_out, avg_duration = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(cost_usd), 0), COALESCE(SUM(input_tokens), 0), "
            "COALESCE(SUM(output_tokens), 0), COALESCE(AVG(duration_ms), 0) FROM request_metrics"
        ).fetchone()

        by_route = conn.execute(
            "SELECT path, COUNT(*), COALESCE(SUM(cost_usd), 0), COALESCE(AVG(duration_ms), 0) "
            "FROM request_metrics GROUP BY path ORDER BY 3 DESC"
        ).fetchall()
    finally:
        conn.close()

    return {
        "total_requests": total or 0,
        "total_cost_usd": round(total_cost or 0.0, 6),
        "total_input_tokens": total_in or 0,
        "total_output_tokens": total_out or 0,
        "avg_duration_ms": round(avg_duration or 0.0, 1),
        "by_route": [
            {"path": path, "requests": count, "cost_usd": round(cost, 6), "avg_duration_ms": round(dur, 1)}
            for path, count, cost, dur in by_route
        ],
    }
