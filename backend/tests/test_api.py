from unittest.mock import patch

from fastapi.testclient import TestClient

import main
import services.security as security
from services import agent, evaluator


client = TestClient(main.app)


def test_health_is_always_open():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_upload_rejects_non_pdf():
    resp = client.post("/upload", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert resp.status_code == 400
    assert "pdf" in resp.json()["detail"].lower()


def test_documents_empty_list_by_default():
    resp = client.get("/documents")
    assert resp.status_code == 200
    assert resp.json() == []


def test_evaluation_empty_by_default():
    resp = client.get("/evaluation")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_queries"] == 0


def test_query_streams_tokens_then_done_event_with_citations_and_eval():
    def fake_stream(question, chunks, history=None):
        for tok in ["Deloitte ", "uses ", "AI ", "[1]."]:
            yield tok

    with patch.object(agent, "hybrid_search", return_value=[
            {"text": "Deloitte Tax uses AI.", "filename": "tax.pdf", "page_number": 1, "chunk_index": 0}]), \
         patch.object(agent, "yes_no", return_value=True), \
         patch("routers.query.stream_answer", side_effect=fake_stream), \
         patch.object(evaluator, "score", side_effect=[0.9, 0.85]):
        with client.stream("POST", "/query", json={"question": "How does Deloitte use AI?"}) as resp:
            assert resp.status_code == 200
            lines = [line for line in resp.iter_lines() if line]

    assert any('"type": "token"' in l for l in lines)
    done_line = lines[-1]
    assert '"type": "done"' in done_line
    assert "tax.pdf" in done_line
    assert '"faithfulness": 0.9' in done_line


def test_query_emits_error_event_on_generation_failure():
    def failing_stream(question, chunks, history=None):
        raise RuntimeError("upstream LLM error")
        yield  # pragma: no cover — makes this a generator

    with patch.object(agent, "hybrid_search", return_value=[
            {"text": "irrelevant", "filename": "a.pdf", "page_number": 1, "chunk_index": 0}]), \
         patch.object(agent, "yes_no", return_value=True), \
         patch("routers.query.stream_answer", side_effect=failing_stream):
        with client.stream("POST", "/query", json={"question": "anything"}) as resp:
            lines = [line for line in resp.iter_lines() if line]

    assert any('"type": "error"' in l for l in lines)
    assert not any('"type": "done"' in l for l in lines)


def test_auth_blocks_protected_routes_when_api_key_set(monkeypatch):
    monkeypatch.setattr(security, "API_KEY", "secret123")

    resp = client.get("/documents")
    assert resp.status_code == 401

    resp = client.get("/documents", headers={"X-API-Key": "wrong"})
    assert resp.status_code == 401

    resp = client.get("/documents", headers={"X-API-Key": "secret123"})
    assert resp.status_code == 200


def test_auth_does_not_block_health_when_api_key_set(monkeypatch):
    monkeypatch.setattr(security, "API_KEY", "secret123")
    resp = client.get("/health")
    assert resp.status_code == 200


def test_upload_rate_limit_returns_429_after_default_threshold():
    # Default RATE_LIMIT_UPLOAD is 10/minute (services/security.py). Every
    # call here fails fast with 400 (non-pdf) before hitting any LLM code,
    # so this stays fast while still exercising the real slowapi decorator.
    files = {"file": ("notes.txt", b"hello", "text/plain")}
    statuses = [client.post("/upload", files=files).status_code for _ in range(11)]
    assert statuses[:10] == [400] * 10
    assert statuses[10] == 429


def test_upload_then_list_then_delete_document(sample_pdf_factory, fake_openai_embeddings):
    pdf_path = sample_pdf_factory(num_pages=2)
    with open(pdf_path, "rb") as f:
        resp = client.post("/upload", files={"file": ("report.pdf", f, "application/pdf")})
    assert resp.status_code == 200
    body = resp.json()
    assert body["filename"] == "report.pdf"
    assert body["method"] == "pymupdf"
    assert body["chunk_count"] > 0

    resp = client.get("/documents")
    docs = resp.json()
    assert len(docs) == 1
    assert docs[0]["filename"] == "report.pdf"
    assert docs[0]["chunk_count"] == body["chunk_count"]

    resp = client.delete("/documents/report.pdf")
    assert resp.status_code == 200
    assert resp.json() == {"filename": "report.pdf", "deleted": True}

    resp = client.get("/documents")
    assert resp.json() == []


def test_upload_corrupted_pdf_returns_400(tmp_path):
    bad_pdf = tmp_path / "corrupt.pdf"
    bad_pdf.write_bytes(b"%PDF-1.4 this is not a real pdf structure")
    with open(bad_pdf, "rb") as f:
        resp = client.post("/upload", files={"file": ("corrupt.pdf", f, "application/pdf")})
    assert resp.status_code == 400


def test_query_with_history_condenses_and_passes_history_through():
    captured = {}

    def fake_stream(question, chunks, history=None):
        captured["stream_question"] = question
        captured["stream_history"] = history
        yield "answer text"

    history_payload = [
        {"role": "user", "content": "What are the 2024 deduction rules?"},
        {"role": "assistant", "content": "They require X and Y [1]."},
    ]

    with patch.object(agent, "hybrid_search", return_value=[
            {"text": "X and Y details.", "filename": "tax.pdf", "page_number": 2, "chunk_index": 0}]) as mock_search, \
         patch.object(agent, "_openai") as mock_agent_openai, \
         patch.object(agent, "yes_no", return_value=True), \
         patch("routers.query.stream_answer", side_effect=fake_stream), \
         patch.object(evaluator, "score", side_effect=[0.9, 0.9]):
        mock_agent_openai.return_value.chat.completions.create.return_value.choices = [
            type("obj", (), {"message": type("m", (), {"content": "standalone: what is X?"})()})()
        ]
        with client.stream("POST", "/query", json={
            "question": "what about X specifically?",
            "history": history_payload,
        }) as resp:
            assert resp.status_code == 200
            lines = [line for line in resp.iter_lines() if line]

    # retrieval used the condensed query, not the raw follow-up
    mock_search.assert_called_once_with("standalone: what is X?", document_filter=None)
    # generation used the raw follow-up question + the history
    assert captured["stream_question"] == "what about X specifically?"
    assert captured["stream_history"] == history_payload
    assert any('"type": "token"' in l for l in lines)
