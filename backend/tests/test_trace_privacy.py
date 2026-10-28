"""Exercise exported spans rather than only asserting calls on mocks."""

import json

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from services import observability


def test_exported_failure_retains_status_without_document_or_provider_message(
    monkeypatch,
):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(
        observability, "_tracer", lambda: provider.get_tracer("privacy-test")
    )
    secret = "PRIVATE-DOCUMENT-EXCERPT AND API-KEY-FIXTURE"
    try:
        with pytest.raises(ValueError, match="PRIVATE-DOCUMENT"):
            with observability.traced_span("synthetic.failure", operation="test"):
                raise ValueError(secret)
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].status.status_code == StatusCode.ERROR
        assert spans[0].status.description == "ValueError"
        assert len(spans[0].events) == 1
        assert "ValueError" in spans[0].to_json()
        assert secret not in spans[0].to_json()
        assert "API-KEY-FIXTURE" not in json.dumps(dict(spans[0].events[0].attributes))
    finally:
        provider.shutdown()
