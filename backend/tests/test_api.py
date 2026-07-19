from unittest.mock import patch

from fastapi.testclient import TestClient

import main
import services.security as security
from routers import upload as upload_router
from services import agent, evaluator, code_agent, supervisor


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
        for tok in ["The firm ", "uses ", "AI ", "[1]."]:
            yield tok

    with patch.object(agent, "hybrid_search", return_value=[
            {"text": "The firm's tax practice uses AI.", "filename": "tax.pdf", "page_number": 1, "chunk_index": 0}]), \
         patch.object(agent, "_grade_chunks", return_value=[True]), \
         patch("routers.query.stream_answer", side_effect=fake_stream), \
         patch.object(evaluator, "score", side_effect=[0.9, 0.85]):
        with client.stream("POST", "/query", json={"question": "How does the firm use AI?"}) as resp:
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
         patch.object(agent, "_grade_chunks", return_value=[True]), \
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


def test_upload_then_list_then_delete_document(sample_pdf_factory, fake_embeddings):
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
         patch.object(agent, "complete", return_value="standalone: what is X?"), \
         patch.object(agent, "_grade_chunks", return_value=[True]), \
         patch("routers.query.stream_answer", side_effect=fake_stream), \
         patch.object(evaluator, "score") as mock_score:
        mock_score.side_effect = [0.9, 0.9]
        with client.stream("POST", "/query", json={
            "question": "what about X specifically?",
            "history": history_payload,
        }) as resp:
            assert resp.status_code == 200
            lines = [line for line in resp.iter_lines() if line]

    # retrieval used the condensed query, not the raw follow-up
    mock_search.assert_called_once_with(
        "standalone: what is X?", document_filter=None, session_id=agent.DEFAULT_SESSION_ID
    )
    # generation used the raw follow-up question + the history
    assert captured["stream_question"] == "what about X specifically?"
    assert captured["stream_history"] == history_payload
    assert any('"type": "token"' in l for l in lines)

    # evaluator's relevance call (2nd call to score()) got the history too,
    # so a raw follow-up question doesn't get penalized for looking
    # unrelated to its chunks in isolation.
    relevance_prompt = mock_score.call_args_list[1].args[0]
    assert "2024 deduction rules" in relevance_prompt


def test_page_image_returns_png_after_upload(sample_pdf_factory, fake_embeddings):
    pdf_path = sample_pdf_factory(num_pages=2)
    with open(pdf_path, "rb") as f:
        client.post("/upload", files={"file": ("with_page.pdf", f, "application/pdf")})

    resp = client.get("/documents/with_page.pdf/page", params={"page": 1, "snippet": "sample text"})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"

    client.delete("/documents/with_page.pdf")


def test_page_image_404_when_pdf_never_uploaded():
    resp = client.get("/documents/never-uploaded.pdf/page", params={"page": 1})
    assert resp.status_code == 404


def test_page_image_404_after_document_deleted(sample_pdf_factory, fake_embeddings):
    pdf_path = sample_pdf_factory(num_pages=1)
    with open(pdf_path, "rb") as f:
        client.post("/upload", files={"file": ("deleted.pdf", f, "application/pdf")})
    client.delete("/documents/deleted.pdf")

    resp = client.get("/documents/deleted.pdf/page", params={"page": 1})
    assert resp.status_code == 404


def test_page_image_400_for_out_of_range_page(sample_pdf_factory, fake_embeddings):
    pdf_path = sample_pdf_factory(num_pages=1)
    with open(pdf_path, "rb") as f:
        client.post("/upload", files={"file": ("onepage.pdf", f, "application/pdf")})

    resp = client.get("/documents/onepage.pdf/page", params={"page": 5})
    assert resp.status_code == 400

    client.delete("/documents/onepage.pdf")


def test_query_emits_status_event_on_rephrase_retry():
    call_count = {"n": 0}

    def fake_grade_chunks(question, chunks):
        call_count["n"] += 1
        return [call_count["n"] > 1]  # first retrieval insufficient, second is fine

    def fake_stream(question, chunks, history=None):
        yield "answer"

    with patch.object(agent, "hybrid_search", return_value=[
            {"text": "x", "filename": "a.pdf", "page_number": 1, "chunk_index": 0}]), \
         patch.object(agent, "_grade_chunks", side_effect=fake_grade_chunks), \
         patch.object(agent, "complete", return_value="rephrased query"), \
         patch("routers.query.stream_answer", side_effect=fake_stream), \
         patch.object(evaluator, "score", side_effect=[0.9, 0.85]):
        with client.stream("POST", "/query", json={"question": "vague question"}) as resp:
            lines = [line for line in resp.iter_lines() if line]

    status_lines = [l for l in lines if '"type": "status"' in l]
    assert len(status_lines) == 1
    assert "rephrased query" in status_lines[0]
    # status event must arrive before any token/done events
    assert lines.index(status_lines[0]) < next(i for i, l in enumerate(lines) if '"type": "token"' in l)


def _agent_tool_call(name, **input_kwargs):
    return {"tool_call": {"name": name, "input": input_kwargs}, "text": ""}


def test_agent_run_streams_plan_code_and_success_result(monkeypatch):
    monkeypatch.setattr(security, "AGENT_API_KEY", "agent-secret")
    coder_responses = [
        _agent_tool_call("run_code", code="print('answer: 42')"),
        _agent_tool_call("finish", summary="The answer is 42."),
    ]
    with patch.object(code_agent, "complete", side_effect=['["compute the answer"]', "APPROVE"]), \
         patch.object(code_agent, "call_with_tools", side_effect=coder_responses):
        with client.stream(
            "POST", "/agent/run",
            json={"goal": "compute the answer"},
            headers={"X-API-Key": "agent-secret"},
        ) as resp:
            assert resp.status_code == 200
            lines = [line for line in resp.iter_lines() if line]

    plan_line = lines[0]
    code_lines = [l for l in lines if '"type": "code"' in l]
    review_lines = [l for l in lines if '"type": "review"' in l]
    done_line = lines[-1]

    assert '"type": "plan"' in plan_line
    assert len(code_lines) == 1
    assert len(review_lines) == 1
    assert '"type": "done"' in done_line
    assert '"success": true' in done_line
    assert "answer: 42" in done_line
    assert '"sandbox_backend": "subprocess"' in done_line


def test_agent_run_streams_error_then_self_correction(monkeypatch):
    monkeypatch.setattr(security, "AGENT_API_KEY", "agent-secret")
    coder_responses = [
        _agent_tool_call("run_code", code="print(undefined_name)"),
        _agent_tool_call("run_code", code="print('recovered')"),
        _agent_tool_call("finish", summary="recovered fine"),
    ]
    with patch.object(code_agent, "complete", side_effect=['["flaky step"]', "APPROVE", "APPROVE"]), \
         patch.object(code_agent, "call_with_tools", side_effect=coder_responses):
        with client.stream(
            "POST", "/agent/run",
            json={"goal": "flaky goal"},
            headers={"X-API-Key": "agent-secret"},
        ) as resp:
            lines = [line for line in resp.iter_lines() if line]

    error_lines = [l for l in lines if '"type": "error"' in l]
    assert len(error_lines) == 1
    assert "NameError" in error_lines[0]
    assert '"success": true' in lines[-1]


def test_agent_run_reports_failure_after_max_tool_calls(monkeypatch):
    monkeypatch.setattr(security, "AGENT_API_KEY", "agent-secret")
    always_run_code = _agent_tool_call("run_code", code="print(still_broken)")
    responses = ['["impossible"]'] + ["APPROVE"] * code_agent.MAX_TOOL_CALLS
    with patch.object(code_agent, "complete", side_effect=responses), \
         patch.object(code_agent, "call_with_tools", return_value=always_run_code):
        with client.stream(
            "POST", "/agent/run",
            json={"goal": "impossible"},
            headers={"X-API-Key": "agent-secret"},
        ) as resp:
            lines = [line for line in resp.iter_lines() if line]

    done_line = lines[-1]
    assert '"type": "done"' in done_line
    assert '"success": false' in done_line


def test_agent_run_reviewer_blocks_disallowed_code_without_executing(monkeypatch):
    monkeypatch.setattr(security, "AGENT_API_KEY", "agent-secret")
    coder_responses = [
        _agent_tool_call("run_code", code="import os\nos.system('echo hi')"),
        _agent_tool_call("finish", summary="stopped"),
    ]
    with patch.object(code_agent, "complete", side_effect=['["sneaky step"]', "REJECT: disallowed import"]), \
         patch.object(code_agent, "call_with_tools", side_effect=coder_responses):
        with client.stream(
            "POST", "/agent/run",
            json={"goal": "do something sneaky"},
            headers={"X-API-Key": "agent-secret"},
        ) as resp:
            lines = [line for line in resp.iter_lines() if line]

    review_lines = [l for l in lines if '"type": "review"' in l]
    assert '"approved": false' in review_lines[0]
    # rejected code never reaches the sandbox, so there must be no "error" event for it
    assert not any('"type": "error"' in l for l in lines)


def _sup_tool_call(name, **input_kwargs):
    return {"tool_call": {"name": name, "input": input_kwargs}, "text": ""}


def test_supervisor_run_docs_only_streams_rag_events():
    responses = [
        _sup_tool_call("search_documents", query="depreciation rate"),
        _sup_tool_call("finish", summary="The rate is 24%."),
    ]
    with patch.object(supervisor, "call_with_tools", side_effect=responses), \
         patch.object(agent, "hybrid_search", return_value=[
             {"text": "The rate is 24%.", "filename": "tax.pdf", "page_number": 2, "chunk_index": 0}]), \
         patch.object(agent, "_grade_chunks", return_value=[True]), \
         patch.object(supervisor, "stream_answer", side_effect=lambda q, c, history=None: iter(["The rate is 24%."])), \
         patch.object(evaluator, "score", return_value=0.9):
        with client.stream("POST", "/supervisor/run", json={"question": "what is the depreciation rate?"}) as resp:
            assert resp.status_code == 200
            lines = [line for line in resp.iter_lines() if line]

    assert '"type": "route"' in lines[0]
    assert any('"type": "rag_token"' in l for l in lines)
    assert any('"type": "rag_done"' in l for l in lines)
    assert '"type": "done"' in lines[-1]
    assert "24%" in lines[-1]


def test_supervisor_run_chains_docs_then_code(monkeypatch):
    monkeypatch.setattr(security, "AGENT_API_KEY", "agent-secret")
    responses = [
        _sup_tool_call("search_documents", query="depreciation rate"),
        _sup_tool_call("run_code", goal="compute schedule using 24% rate"),
        _sup_tool_call("finish", summary="Computed with the 24% rate."),
    ]
    coder_responses = [
        _sup_tool_call("run_code", code="print('schedule computed')"),
        _sup_tool_call("finish", summary="done"),
    ]
    with patch.object(supervisor, "call_with_tools", side_effect=responses), \
         patch.object(agent, "hybrid_search", return_value=[
             {"text": "The rate is 24%.", "filename": "tax.pdf", "page_number": 2, "chunk_index": 0}]), \
         patch.object(agent, "_grade_chunks", return_value=[True]), \
         patch.object(supervisor, "stream_answer", side_effect=lambda q, c, history=None: iter(["24%."])), \
         patch.object(evaluator, "score", return_value=0.9), \
         patch.object(code_agent, "complete", side_effect=['["one step"]', "APPROVE"]), \
         patch.object(code_agent, "call_with_tools", side_effect=coder_responses):
        with client.stream(
            "POST", "/supervisor/run",
            json={"question": "find and compute"},
            headers={"X-API-Key": "agent-secret"},
        ) as resp:
            lines = [line for line in resp.iter_lines() if line]

    assert any('"type": "rag_done"' in l for l in lines)
    assert any('"type": "action_plan"' in l for l in lines)
    assert any('"type": "action_done"' in l for l in lines)
    done_line = lines[-1]
    assert '"type": "done"' in done_line
    assert "24% rate" in done_line


def test_supervisor_run_rate_limit_returns_429_after_default_threshold():
    # Default RATE_LIMIT_SUPERVISOR is 5/minute. A 422 (pydantic validation
    # failure) never reaches the endpoint body at all, so slowapi's
    # decorator wouldn't count it — the request has to actually reach the
    # handler to exercise the real rate limiter, hence mocking an instant
    # "finish" decision rather than sending a malformed body.
    with patch.object(supervisor, "call_with_tools", return_value={"tool_call": None, "text": "ok"}):
        statuses = [
            client.post("/supervisor/run", json={"question": "hi"}).status_code for _ in range(6)
        ]
    assert statuses[:5] == [200] * 5
    assert statuses[5] == 429


# --- Public-deployment hardening: session isolation ---------------------

def test_session_isolation_prevents_cross_visitor_access(sample_pdf_factory, fake_embeddings):
    pdf_path = sample_pdf_factory(num_pages=1)
    with open(pdf_path, "rb") as f:
        resp = client.post(
            "/upload",
            files={"file": ("private.pdf", f, "application/pdf")},
            headers={"X-Session-ID": "session-a"},
        )
    assert resp.status_code == 200

    # The uploader sees their own document.
    resp = client.get("/documents", headers={"X-Session-ID": "session-a"})
    assert [d["filename"] for d in resp.json()] == ["private.pdf"]

    # A different visitor's library is empty — they never see session A's file.
    resp = client.get("/documents", headers={"X-Session-ID": "session-b"})
    assert resp.json() == []

    # Session B can't delete session A's document. 404 (not 403), so the
    # response never confirms the filename exists under someone else.
    resp = client.delete("/documents/private.pdf", headers={"X-Session-ID": "session-b"})
    assert resp.status_code == 404

    # Session B can't render a page from session A's PDF either.
    resp = client.get(
        "/documents/private.pdf/page",
        params={"page": 1},
        headers={"X-Session-ID": "session-b"},
    )
    assert resp.status_code == 404

    # The real owner still can — proves this is ownership-scoped, not
    # just globally broken.
    resp = client.delete("/documents/private.pdf", headers={"X-Session-ID": "session-a"})
    assert resp.status_code == 200


# --- Public-deployment hardening: Action Agent fail-closed gating -------

def test_agent_api_key_gate_fails_closed_then_rejects_wrong_key(monkeypatch):
    # Test env's backend/.env sets API_KEY= (blank) and defines no
    # AGENT_API_KEY at all, so services.security.AGENT_API_KEY is falsy at
    # import time -> code execution refuses outright for anyone, rather
    # than silently running unsandboxed code for an unauthenticated public
    # visitor. (Asserted first, before any monkeypatch, to prove this is
    # the real default and not just an artifact of test ordering.)
    resp = client.post("/agent/run", json={"goal": "anything"})
    assert resp.status_code == 403

    # Once an operator sets a key, callers without it or with the wrong
    # one are still rejected (401) rather than let through.
    monkeypatch.setattr(security, "AGENT_API_KEY", "agent-secret")
    resp = client.post("/agent/run", json={"goal": "anything"})
    assert resp.status_code == 401

    resp = client.post("/agent/run", json={"goal": "anything"}, headers={"X-API-Key": "wrong"})
    assert resp.status_code == 401


def test_config_reflects_agent_key_state_per_request(monkeypatch):
    monkeypatch.setattr(security, "AGENT_API_KEY", "")
    resp = client.get("/config")
    assert resp.status_code == 200
    assert resp.json() == {"agent_enabled": False}

    monkeypatch.setattr(security, "AGENT_API_KEY", "agent-secret")
    # No key sent -> locked for this caller even though a key is configured.
    resp = client.get("/config")
    assert resp.json() == {"agent_enabled": False}

    resp = client.get("/config", headers={"X-API-Key": "wrong"})
    assert resp.json() == {"agent_enabled": False}

    resp = client.get("/config", headers={"X-API-Key": "agent-secret"})
    assert resp.json() == {"agent_enabled": True}


def test_supervisor_degrades_to_docs_only_without_agent_key(monkeypatch):
    # AGENT_API_KEY is configured, but this request sends no X-API-Key, so
    # agent_enabled_for_request() is False for it specifically — run_code
    # is never offered to the LLM, and even a stale/mocked response naming
    # it is treated as unavailable rather than executed.
    monkeypatch.setattr(security, "AGENT_API_KEY", "agent-secret")
    responses = [
        _sup_tool_call("run_code", goal="compute something"),
        _sup_tool_call("finish", summary="done without code execution"),
    ]
    with patch.object(supervisor, "call_with_tools", side_effect=responses):
        with client.stream("POST", "/supervisor/run", json={"question": "compute something"}) as resp:
            assert resp.status_code == 200
            lines = [line for line in resp.iter_lines() if line]

    assert not any('"type": "route"' in l for l in lines)
    assert not any('"type": "action_plan"' in l for l in lines)
    assert not any('"type": "action_done"' in l for l in lines)
    assert '"type": "done"' in lines[-1]
    assert "done without code execution" in lines[-1]


# --- Public-deployment hardening: upload size limit ---------------------

def test_upload_rejects_oversized_file(monkeypatch, sample_pdf_factory):
    monkeypatch.setattr(upload_router, "MAX_UPLOAD_SIZE_BYTES", 10)
    pdf_path = sample_pdf_factory(num_pages=1)
    with open(pdf_path, "rb") as f:
        resp = client.post("/upload", files={"file": ("big.pdf", f, "application/pdf")})
    assert resp.status_code == 400
    assert "too large" in resp.json()["detail"].lower()
