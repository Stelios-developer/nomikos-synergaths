from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
import pytest

from services import budget, llm


def test_nested_budgets_cannot_extend_the_parent(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(budget.time, "monotonic", lambda: now[0])
    with budget.operation_budget(10):
        assert budget.remaining() == 10
        now[0] += 3
        with budget.operation_budget(120):
            assert budget.remaining() == 7
        now[0] += 8
        with pytest.raises(budget.BudgetExpired):
            budget.remaining()
    assert budget.remaining() == 120


def test_expired_durable_job_cannot_start_another_provider_call():
    with pytest.raises(budget.BudgetExpired):
        with budget.operation_budget(
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
        ):
            pytest.fail("Expired work was admitted")


def test_provider_clients_disable_hidden_retries_and_have_timeouts(monkeypatch):
    for constructor, field, factory in [
        ("OpenAI", "_openai_client", llm._openai),
        ("Anthropic", "_anthropic_client", llm._anthropic),
    ]:
        mock = MagicMock()
        monkeypatch.setattr(llm, constructor, mock)
        monkeypatch.setattr(llm, field, None)
        factory()
        assert mock.call_args.kwargs["max_retries"] == 0
        assert mock.call_args.kwargs["timeout"] == 120


@pytest.mark.parametrize(
    "stop", ["disconnect", "deadline", "provider_error", "complete"]
)
def test_openai_stream_closes_connection_on_every_exit(monkeypatch, stop):
    from types import SimpleNamespace

    class Stream:
        closed = False

        def __iter__(self):
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="first"))],
                usage=None,
            )
            if stop == "provider_error":
                raise OSError("synthetic transport failure")
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="second"))],
                usage=None,
            )

        def close(self):
            self.closed = True

    stream = Stream()
    client = MagicMock()
    client.chat.completions.create.return_value = stream
    monkeypatch.setattr(llm, "_openai", lambda: client)
    clock = [100.0]
    monkeypatch.setattr(budget.time, "monotonic", lambda: clock[0])
    with budget.operation_budget(10):
        generator = llm.stream_answer("synthetic question", [])
        assert next(generator) == "first"
        if stop == "disconnect":
            generator.close()
        elif stop == "deadline":
            clock[0] += 11
            with pytest.raises(budget.BudgetExpired):
                next(generator)
        elif stop == "provider_error":
            with pytest.raises(OSError):
                next(generator)
        else:
            assert list(generator) == ["second"]
    assert stream.closed
