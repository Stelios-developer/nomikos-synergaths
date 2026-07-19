import contextvars
import json
import logging
from concurrent.futures import ThreadPoolExecutor

import pytest

from services import observability as obs


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Every test gets its own throwaway SQLite file so persistence tests
    never interfere with each other or with a real observability.db."""
    monkeypatch.setattr(obs, "OBS_DB_PATH", str(tmp_path / "observability_test.db"))
    yield


@pytest.fixture(autouse=True)
def _clean_request_context():
    """request_id_var/usage_accumulator_var default to None outside a
    request — reset after every test so one test's context never leaks
    into the next (contextvars are process-global by default)."""
    yield
    obs.request_id_var.set(None)
    obs.usage_accumulator_var.set(None)


# --- cost calculation ---

def test_cost_usd_known_model():
    cost = obs._cost_usd("claude-haiku-4-5-20251001", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == pytest.approx(1.00 + 5.00)


def test_cost_usd_zero_tokens_is_zero_cost():
    assert obs._cost_usd("claude-haiku-4-5-20251001", 0, 0) == 0.0


def test_cost_usd_unknown_model_falls_back_to_zero(caplog):
    with caplog.at_level(logging.WARNING, logger="app"):
        cost = obs._cost_usd("some-brand-new-model", 1000, 1000)
    assert cost == 0.0


def test_cost_usd_unknown_model_only_warns_once():
    obs._unknown_model_warned.discard("repeat-model-test")
    obs._cost_usd("repeat-model-test", 100, 100)
    assert "repeat-model-test" in obs._unknown_model_warned
    # Second call must not raise/crash and stays silently zero-cost.
    assert obs._cost_usd("repeat-model-test", 100, 100) == 0.0


# --- request id ---

def test_get_request_id_defaults_when_unset():
    obs.request_id_var.set(None)
    assert obs.get_request_id() == "no-request"


def test_new_request_id_is_unique_and_short():
    a, b = obs.new_request_id(), obs.new_request_id()
    assert a != b
    assert len(a) == 16


# --- usage accumulation ---

def test_record_llm_usage_without_request_context_does_not_crash():
    obs.usage_accumulator_var.set(None)
    record = obs.record_llm_usage("claude-haiku-4-5-20251001", "complete", 10, 20, 5.0)
    assert record["input_tokens"] == 10
    assert record["output_tokens"] == 20
    assert record["cost_usd"] > 0


def test_record_llm_usage_accumulates_into_request_context():
    obs.usage_accumulator_var.set([])
    obs.record_llm_usage("claude-haiku-4-5-20251001", "complete", 100, 50, 10.0)
    obs.record_llm_usage("claude-haiku-4-5-20251001", "generate_with_system", 200, 100, 20.0)

    summary = obs.get_request_usage_summary()
    assert summary["total_input_tokens"] == 300
    assert summary["total_output_tokens"] == 150
    assert len(summary["calls"]) == 2
    assert summary["total_cost_usd"] == pytest.approx(sum(c["cost_usd"] for c in summary["calls"]))


def test_get_request_usage_summary_all_zero_with_no_accumulator():
    obs.usage_accumulator_var.set(None)
    summary = obs.get_request_usage_summary()
    assert summary == {"total_input_tokens": 0, "total_output_tokens": 0, "total_cost_usd": 0.0, "calls": []}


# --- JSON structured logging ---

def test_json_formatter_produces_valid_json_with_expected_keys():
    formatter = obs.JsonFormatter()
    record = logging.LogRecord(
        name="app", level=logging.INFO, pathname=__file__, lineno=1,
        msg="something_happened", args=(), exc_info=None,
    )
    record.context = {"foo": "bar", "count": 3}
    formatted = formatter.format(record)
    parsed = json.loads(formatted)  # must not raise

    assert parsed["message"] == "something_happened"
    assert parsed["level"] == "INFO"
    assert parsed["foo"] == "bar"
    assert parsed["count"] == 3
    assert "request_id" in parsed
    assert "timestamp" in parsed


def test_json_formatter_includes_current_request_id():
    obs.request_id_var.set("req-xyz")
    formatter = obs.JsonFormatter()
    record = logging.LogRecord(
        name="app", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hello", args=(), exc_info=None,
    )
    parsed = json.loads(formatter.format(record))
    assert parsed["request_id"] == "req-xyz"


# --- SQLite persistence ---

def test_record_and_read_back_request_metrics():
    summary = {"total_input_tokens": 120, "total_output_tokens": 80, "total_cost_usd": 0.0042,
               "calls": [{"model": "x"}, {"model": "y"}]}
    obs.record_request_metrics("req-1", "POST", "/query", 200, 123.4, summary)

    recent = obs.get_recent_requests(limit=10)
    assert len(recent) == 1
    row = recent[0]
    assert row["request_id"] == "req-1"
    assert row["path"] == "/query"
    assert row["status_code"] == 200
    assert row["input_tokens"] == 120
    assert row["output_tokens"] == 80
    assert row["llm_calls"] == 2


def test_get_summary_aggregates_across_routes():
    empty_summary = {"total_input_tokens": 0, "total_output_tokens": 0, "total_cost_usd": 0.0, "calls": []}
    obs.record_request_metrics("r1", "GET", "/health", 200, 10.0, empty_summary)
    obs.record_request_metrics("r2", "POST", "/query", 200, 50.0,
                                {"total_input_tokens": 100, "total_output_tokens": 50,
                                 "total_cost_usd": 0.01, "calls": [{}]})
    obs.record_request_metrics("r3", "POST", "/query", 200, 150.0,
                                {"total_input_tokens": 200, "total_output_tokens": 100,
                                 "total_cost_usd": 0.02, "calls": [{}]})

    summary = obs.get_summary()
    assert summary["total_requests"] == 3
    assert summary["total_cost_usd"] == pytest.approx(0.03)

    query_route = next(r for r in summary["by_route"] if r["path"] == "/query")
    assert query_route["requests"] == 2
    assert query_route["avg_duration_ms"] == pytest.approx(100.0)


def test_get_summary_with_no_requests_yet_is_all_zero():
    summary = obs.get_summary()
    assert summary["total_requests"] == 0
    assert summary["total_cost_usd"] == 0.0
    assert summary["by_route"] == []


def test_get_recent_requests_respects_limit_and_orders_newest_first():
    empty = {"total_input_tokens": 0, "total_output_tokens": 0, "total_cost_usd": 0.0, "calls": []}
    for i in range(5):
        obs.record_request_metrics(f"req-{i}", "GET", "/health", 200, 1.0, empty)

    recent = obs.get_recent_requests(limit=2)
    assert len(recent) == 2
    assert recent[0]["request_id"] == "req-4"  # most recent first
    assert recent[1]["request_id"] == "req-3"


# --- contextvar propagation into ThreadPoolExecutor workers ---

def test_submit_with_context_propagates_request_id_into_worker_thread():
    obs.request_id_var.set("propagated-id")
    seen = {}

    def worker():
        seen["request_id"] = obs.get_request_id()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = obs.submit_with_context(executor, worker)
        future.result()

    assert seen["request_id"] == "propagated-id"


def test_plain_executor_submit_does_not_propagate_context_by_default():
    """Sanity check that the problem submit_with_context solves is real —
    without it, a worker thread does NOT see the parent's contextvars."""
    obs.request_id_var.set("should-not-leak")
    seen = {}

    def worker():
        seen["request_id"] = obs.get_request_id()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(worker)
        future.result()

    assert seen["request_id"] == "no-request"


def test_submit_with_context_propagates_usage_accumulator_for_cost_attribution():
    obs.usage_accumulator_var.set([])

    def worker():
        obs.record_llm_usage("claude-haiku-4-5-20251001", "generate_with_system", 10, 10, 1.0)

    with ThreadPoolExecutor(max_workers=1) as executor:
        obs.submit_with_context(executor, worker).result()

    summary = obs.get_request_usage_summary()
    assert len(summary["calls"]) == 1


# --- tracing setup is safe to call repeatedly / without an exporter ---

def test_configure_tracing_is_idempotent():
    obs.configure_tracing()
    obs.configure_tracing()  # must not raise or duplicate processors


def test_traced_span_yields_a_span_and_does_not_raise():
    with obs.traced_span("test.span", some_attr="value") as span:
        assert span is not None


def test_traced_span_records_exception_and_reraises():
    with pytest.raises(ValueError):
        with obs.traced_span("test.failing_span"):
            raise ValueError("boom")
