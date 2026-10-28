from concurrent.futures import ThreadPoolExecutor
import threading
from urllib.error import URLError

import pytest

from services.resilience import DependencyGuard, DependencyRejected
from services import n8n_orchestrator as bridge, security


def test_bulkhead_rejects_without_queueing_and_recovers():
    guard = DependencyGuard(capacity=1)
    entered, release = threading.Event(), threading.Event()

    def hold():
        with guard.call():
            entered.set()
            assert release.wait(2)

    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(hold)
        assert entered.wait(2)
        try:
            with pytest.raises(DependencyRejected, match="capacity"):
                with guard.call():
                    pytest.fail("busy dependency was called")
        finally:
            release.set()
        future.result()
    with guard.call():
        pass


def test_failed_calls_release_capacity():
    guard = DependencyGuard(capacity=1, threshold=10)
    with pytest.raises(ValueError):
        with guard.call():
            raise ValueError("offline")
    with guard.call():
        pass


def test_open_half_open_and_successful_recovery():
    now = [0.0]
    guard = DependencyGuard(threshold=2, cooldown=10, clock=lambda: now[0])
    for _ in range(2):
        with pytest.raises(ValueError):
            with guard.call():
                raise ValueError("offline")
    with pytest.raises(DependencyRejected) as blocked:
        with guard.call():
            pytest.fail("OPEN must fail before transport")
    assert blocked.value.retry_after == 10
    now[0] = 11
    with guard.call():
        with pytest.raises(DependencyRejected):
            with guard.call():
                pytest.fail("only one HALF_OPEN probe")
    with guard.call():
        pass


def test_failed_probe_reopens_the_circuit():
    now = [0.0]
    guard = DependencyGuard(threshold=1, cooldown=10, clock=lambda: now[0])
    for instant in (0.0, 11.0):
        now[0] = instant
        with pytest.raises(ValueError):
            with guard.call():
                raise ValueError("still offline")
    with pytest.raises(DependencyRejected):
        with guard.call():
            pass


def test_expected_errors_do_not_poison_the_circuit():
    guard = DependencyGuard(threshold=1, count_failure=lambda exc: not isinstance(exc, ValueError))
    for _ in range(4):
        with pytest.raises(ValueError):
            with guard.call():
                raise ValueError("invalid input")
    with guard.call():
        pass


def test_late_success_cannot_close_a_newer_open_generation():
    guard = DependencyGuard(capacity=2, threshold=1)
    late = guard.call()
    late.__enter__()
    with pytest.raises(ValueError):
        with guard.call():
            raise ValueError("offline")
    late.__exit__(None, None, None)
    with pytest.raises(DependencyRejected):
        with guard.call():
            pytest.fail("old success incorrectly closed the circuit")


def test_real_bridge_uses_guard_and_never_retries_webhook(monkeypatch):
    monkeypatch.setattr(bridge, "N8N_ORCHESTRATOR_URL", "http://n8n.test/case")
    monkeypatch.setattr(security, "N8N_WEBHOOK_API_KEY", "fixture-secret")
    monkeypatch.setattr(bridge, "_workflow_guard", DependencyGuard(threshold=1))
    calls = []

    def unavailable(*args, **kwargs):
        calls.append(True)
        raise bridge.N8nOrchestratorError("could not be reached", retryable=True, uncertain=True)

    monkeypatch.setattr(bridge, "_post_case_workflow", unavailable)
    with pytest.raises(bridge.N8nOrchestratorError, match="reached"):
        bridge.trigger_case_workflow("source.pdf", "workspace")
    with pytest.raises(bridge.N8nOrchestratorError, match="recovering"):
        bridge.trigger_case_workflow("source.pdf", "workspace")
    assert len(calls) == 1
