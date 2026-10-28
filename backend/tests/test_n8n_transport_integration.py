"""Real loopback HTTP faults. No running n8n, external API or document store."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time

import pytest

from services import n8n_orchestrator as bridge, security
from services.resilience import DependencyGuard


@contextmanager
def upstream(monkeypatch, mode):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            received.append((self.path, dict(self.headers), json.loads(body)))
            if mode[0] == "stall":
                time.sleep(1.0)
            status = {"ok": 200, "fail": 503, "unauthorized": 401, "redirect": 307}.get(mode[0], 200)
            self.send_response(status)
            if status == 307:
                self.send_header("Location", "/must-not-receive-credentials")
            data = b"x" * 2048 if mode[0] == "oversize" else b'{"ok":true}'
            self.send_header("Content-Length", str(len(data)))
            try:
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    monkeypatch.setattr(bridge, "N8N_ORCHESTRATOR_URL", f"http://127.0.0.1:{server.server_port}/webhook")
    monkeypatch.setattr(security, "N8N_WEBHOOK_API_KEY", "synthetic-test-credential")
    try:
        yield received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_real_http_opens_circuit_without_retries_and_recovers(monkeypatch):
    now = [100.0]
    guard = DependencyGuard(clock=lambda: now[0], count_failure=lambda exc: getattr(exc, "retryable", False))
    monkeypatch.setattr(bridge, "_workflow_guard", guard)
    mode = ["fail"]
    with upstream(monkeypatch, mode) as received:
        for _ in range(3):
            with pytest.raises(bridge.N8nOrchestratorError, match="HTTP 503"):
                bridge.trigger_case_workflow("synthetic.pdf", "synthetic-workspace")
        with pytest.raises(bridge.N8nOrchestratorError, match="recovering"):
            bridge.trigger_case_workflow("synthetic.pdf", "synthetic-workspace")
        assert len(received) == 3
        now[0] += 31
        mode[0] = "ok"
        bridge.trigger_case_workflow("synthetic.pdf", "synthetic-workspace")
        assert len(received) == 4
        _, headers, body = received[-1]
        assert {key.lower(): value for key, value in headers.items()}["x-n8n-api-key"] == "synthetic-test-credential"
        assert body == {"filename": "synthetic.pdf", "workspace_id": "synthetic-workspace"}


def test_real_http_unauthorized_does_not_trip_dependency_circuit(monkeypatch):
    with upstream(monkeypatch, ["unauthorized"]) as received:
        for _ in range(4):
            with pytest.raises(bridge.N8nOrchestratorError, match="HTTP 401"):
                bridge.trigger_case_workflow("synthetic.pdf", "synthetic-workspace")
        assert len(received) == 4


def test_real_http_timeout_releases_capacity_without_a_retry(monkeypatch):
    monkeypatch.setattr(bridge, "N8N_ORCHESTRATOR_TIMEOUT_SECONDS", 0.5)
    mode = ["stall"]
    with upstream(monkeypatch, mode) as received:
        with pytest.raises(bridge.N8nOrchestratorError, match="timed out"):
            bridge.trigger_case_workflow("synthetic.pdf", "synthetic-workspace")
        assert len(received) == 1
        mode[0] = "ok"
        bridge.trigger_case_workflow("synthetic.pdf", "synthetic-workspace")
        assert len(received) == 2


def test_real_http_redirect_never_forwards_integration_credentials(monkeypatch):
    with upstream(monkeypatch, ["redirect"]) as received:
        with pytest.raises(bridge.N8nOrchestratorError, match="HTTP 307"):
            bridge.trigger_case_workflow("synthetic.pdf", "synthetic-workspace")
        assert [item[0] for item in received] == ["/webhook"]


def test_real_http_response_is_bounded(monkeypatch):
    monkeypatch.setattr(bridge, "N8N_RESPONSE_LIMIT_BYTES", 1024)
    with upstream(monkeypatch, ["oversize"]) as received:
        with pytest.raises(bridge.N8nOrchestratorError, match="size limit"):
            bridge.trigger_case_workflow("synthetic.pdf", "synthetic-workspace")
        assert len(received) == 1


def test_dispatcher_shutdown_kills_only_local_transport_without_replaying(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    stopped=threading.Event()
    with upstream(monkeypatch,['stall']) as received:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(bridge.trigger_case_workflow,'synthetic.pdf','synthetic-workspace',
                               cancel_event=stopped,timeout_seconds=10)
            deadline=time.monotonic()+3
            while not received and time.monotonic()<deadline:time.sleep(0.01)
            assert len(received)==1
            stopped.set()
            with pytest.raises(bridge.N8nOrchestratorError) as error:
                future.result(timeout=2)
            assert error.value.uncertain
        assert len(received)==1
