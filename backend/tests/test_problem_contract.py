from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
import pytest

import main
from services.problems import correlation_id, install_problem_handlers


def test_public_health_contract_stays_compatible():
    client = TestClient(main.app)
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/livez").json() == {"status": "alive"}


def test_errors_have_rfc9457_shape_and_correlation():
    response = TestClient(main.app).get("/missing-contract-route", headers={"X-Request-ID": "fixture-request"})
    body = response.json()
    assert response.status_code == body["status"] == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert body["type"] == "about:blank"
    assert body["request_id"] == response.headers["X-Request-ID"] == "fixture-request"
    assert body["instance"] == "urn:request:fixture-request"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("value", ["x" * 1000, "header\r\ninjection", "private data", ""])
def test_untrusted_correlation_ids_are_bounded(value):
    assert correlation_id(value) != value
    assert len(correlation_id(value)) <= 64


def test_validation_does_not_echo_rejected_input():
    app = FastAPI()
    install_problem_handlers(app)

    class Payload(BaseModel):
        count: int

    @app.post("/validate")
    def validate(payload: Payload):
        return payload

    response = TestClient(app).post("/validate", json={"count": "private-document-content"})
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_REQUEST"
    assert "private-document-content" not in response.text
    assert response.json()["invalid_params"][0]["name"] == "body.count"


def test_readiness_fails_closed_without_auth_pool(monkeypatch):
    monkeypatch.setattr(main, "AUTH_REQUIRED", True)
    monkeypatch.setattr(main.app.state, "auth_db_pool", None, raising=False)
    response = TestClient(main.app).get("/readyz")
    assert response.status_code == 503
    assert response.headers["retry-after"] == "3"


def test_readiness_checks_real_pool_interface_without_exposing_db_errors(monkeypatch):
    class Pool:
        async def fetchval(self, query, timeout):
            assert query == "SELECT 1" and timeout == 2
            return 1

    monkeypatch.setattr(main, "AUTH_REQUIRED", True)
    monkeypatch.setattr(main.app.state, "auth_db_pool", Pool(), raising=False)
    assert TestClient(main.app).get("/readyz").status_code == 200


def test_unexpected_errors_do_not_expose_tracebacks_or_credentials(monkeypatch):
    logged = []
    monkeypatch.setattr(main.logger, "error", lambda message, **kwargs: logged.append((message, kwargs)))
    @main.app.get("/__test_failure_contract")
    async def fail():
        raise RuntimeError("private-document-and-password")

    route = main.app.routes[-1]
    try:
        response = TestClient(main.app).get("/__test_failure_contract")
        assert response.status_code == 500
        assert response.json()["status"] == 500
        assert "private-document-and-password" not in response.text
        assert response.headers.get("X-Request-ID")
        assert logged == [("request_failed", {"extra": {"context": {"error_type": "RuntimeError"}}})]
        assert "private-document-and-password" not in str(logged)
    finally:
        main.app.routes.remove(route)


@pytest.mark.parametrize('uncertain', [True, False])
def test_json_analysis_error_preserves_uncertainty_without_private_message(uncertain):
    @main.app.get('/__test_analysis_failure')
    async def fail():
        raise main.N8nOrchestratorError('private-provider-detail', retryable=True, uncertain=uncertain)

    route=main.app.routes[-1]
    try:
        response=TestClient(main.app).get('/__test_analysis_failure')
        assert response.status_code==503
        assert response.json()['uncertain']==uncertain
        assert response.json()['retryable']==(not uncertain)
        assert response.json()['code']==('ANALYSIS_UNCERTAIN' if uncertain else 'ANALYSIS_FAILED')
        assert 'private-provider-detail' not in response.text
    finally:
        main.app.routes.remove(route)
