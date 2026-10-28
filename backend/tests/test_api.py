import json
from pathlib import Path
from unittest.mock import patch

import fitz
from fastapi.testclient import TestClient

import main
import services.security as security
from routers import documents as document_routes, upload as upload_router
from services import agent, case_store, evaluator, supervisor
from services.pdf_storage import pdf_path
from services.session_scope import DEFAULT_SESSION_ID


client = TestClient(main.app)


def test_health_is_open():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_n8n_analysis_fails_closed_without_integration_key(monkeypatch):
    monkeypatch.setattr(security, "N8N_WEBHOOK_API_KEY", "")
    response = client.post("/integrations/n8n/analyze", headers={"X-Workspace-ID": "acme"}, json={"question": "Summarize"})
    assert response.status_code == 403


def test_n8n_analysis_returns_grounded_workflow_result(monkeypatch):
    monkeypatch.setattr(security, "N8N_WEBHOOK_API_KEY", "n8n-secret")
    state = {
        "question": "standalone question",
        "answer": "The document requires a filing [1].",
        "chunks": [{"filename": "memo.pdf", "page_number": 3, "text": "A filing is required."}],
        "iteration": 1,
    }
    with patch("routers.n8n.run_agent", return_value=state):
        response = client.post(
            "/integrations/n8n/analyze",
            headers={"X-N8N-API-Key": "n8n-secret", "X-Workspace-ID": "acme"},
            json={"question": "What action is required?"},
        )

    assert response.status_code == 200
    assert response.json()["citations"] == [{"filename": "memo.pdf", "page": 3, "text": "A filing is required."}]


def test_n8n_supervisor_adapter_returns_the_real_stream_trace(monkeypatch):
    monkeypatch.setattr(security, "N8N_WEBHOOK_API_KEY", "n8n-secret")
    events = iter([
        ("route", {"tool": "search_documents", "input": "What deadline applies?"}),
        ("rag_token", "The filing is due "),
        ("rag_token", "on 30 June [1]."),
        ("rag_done", {"citations": [{"filename": "memo.pdf", "page": 2, "text": "Due 30 June."}]}),
        ("done", {"summary": "File by 30 June."}),
    ])
    with patch("routers.n8n.run_supervisor_stream", return_value=events) as stream:
        response = client.post(
            "/integrations/n8n/agents/supervisor",
            headers={"X-N8N-API-Key": "n8n-secret", "X-Workspace-ID": "acme"},
            json={"question": "What deadline applies?", "document_filter": "memo.pdf"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "workspace_id": "acme",
        "agent": "supervisor",
        "question": "What deadline applies?",
        "route_trace": [{"tool": "search_documents", "input": "What deadline applies?"}],
        "answer": "The filing is due on 30 June [1].",
        "summary": "File by 30 June.",
        "citations": [{"filename": "memo.pdf", "page": 2, "text": "Due 30 June."}],
    }
    stream.assert_called_once_with("What deadline applies?", "memo.pdf", None, "acme")


def test_n8n_research_adapter_accumulates_the_real_multihop_trace(monkeypatch):
    monkeypatch.setattr(security, "N8N_WEBHOOK_API_KEY", "n8n-secret")
    events = iter([
        ("subquestions", ["What is the deadline?", "Who owns the filing?"]),
        ("subretrieval", {"sub_question": "Who owns the filing?", "citations": [{"filename": "memo.pdf", "page": 3, "text": "Legal owns it."}]}),
        ("subretrieval", {"sub_question": "What is the deadline?", "citations": [{"filename": "memo.pdf", "page": 2, "text": "Due 30 June."}]}),
        ("token", "Legal owns the filing; it is due 30 June [1][2]."),
        ("done", {"citations": [{"filename": "memo.pdf", "page": 2, "text": "Due 30 June."}]}),
    ])
    with patch("routers.n8n.run_research_stream", return_value=events) as stream:
        response = client.post(
            "/integrations/n8n/agents/research",
            headers={"X-N8N-API-Key": "n8n-secret", "X-Workspace-ID": "acme"},
            json={"question": "What is the deadline and who owns the filing?"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["agent"] == "research"
    assert body["workspace_id"] == "acme"
    assert body["subquestions"] == ["What is the deadline?", "Who owns the filing?"]
    assert body["retrieval_trace"][0]["sub_question"] == "Who owns the filing?"
    assert body["answer"] == "Legal owns the filing; it is due 30 June [1][2]."
    assert body["citations"] == [{"filename": "memo.pdf", "page": 2, "text": "Due 30 June."}]
    stream.assert_called_once_with("What is the deadline and who owns the filing?", None, None, "acme")


def test_n8n_expert_review_adapter_returns_real_advisor_outputs(monkeypatch):
    monkeypatch.setattr(security, "N8N_WEBHOOK_API_KEY", "n8n-secret")
    events = iter([
        ("citations", [{"filename": "memo.pdf", "page": 2, "text": "Due 30 June."}]),
        ("advisor", {"id": "risk", "label": "Risk Assessor", "emoji": "⚠️", "answer": "Missing owner evidence is high risk."}),
        ("advisor", {"id": "conservative", "label": "Compliance", "emoji": "🛡️", "answer": "Confirm ownership before filing."}),
        ("done", {"moderator_summary": "Confirm ownership, then file by 30 June."}),
    ])
    with patch("routers.n8n.run_panel_stream", return_value=events) as stream:
        response = client.post(
            "/integrations/n8n/agents/expert-review",
            headers={"X-N8N-API-Key": "n8n-secret", "X-Workspace-ID": "acme"},
            json={"question": "Should we file now?", "document_filter": "memo.pdf"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "workspace_id": "acme",
        "agent": "expert_review",
        "question": "Should we file now?",
        "citations": [{"filename": "memo.pdf", "page": 2, "text": "Due 30 June."}],
        "advisor_opinions": [
            {"id": "risk", "label": "Risk Assessor", "emoji": "⚠️", "answer": "Missing owner evidence is high risk."},
            {"id": "conservative", "label": "Compliance", "emoji": "🛡️", "answer": "Confirm ownership before filing."},
        ],
        "moderator_summary": "Confirm ownership, then file by 30 June.",
    }
    stream.assert_called_once_with("Should we file now?", "memo.pdf", "acme")


def test_n8n_case_start_uses_the_integration_key_and_workspace(monkeypatch):
    monkeypatch.setattr(security, "N8N_WEBHOOK_API_KEY", "n8n-secret")
    case = {
        "case_id": "case-1",
        "workspace_id": "acme",
        "document": {"filename": "contract.pdf", "chunk_count": 3},
        "citations": [{"id": "C1", "page": 1}],
        "status": "in_progress",
        "stage": "started",
        "warnings": [],
    }
    with patch("routers.n8n.document_case.start_case", return_value=case) as start_case:
        response = client.post(
            "/integrations/n8n/cases/start",
            headers={"X-N8N-API-Key": "n8n-secret", "X-Workspace-ID": "acme"},
            json={"filename": "contract.pdf"},
        )

    assert response.status_code == 200
    assert response.json()["case_id"] == "case-1"
    assert response.json()["citations"] == [{"id": "C1", "page": 1}]
    start_case.assert_called_once_with("contract.pdf", "acme")


def test_n8n_case_stage_fails_closed_for_another_workspace(monkeypatch):
    monkeypatch.setattr(security, "N8N_WEBHOOK_API_KEY", "n8n-secret")
    with patch("routers.n8n.document_case.run_document_dna", side_effect=ValueError("Document case was not found in this workspace.")):
        response = client.post(
            "/integrations/n8n/cases/document-dna",
            headers={"X-N8N-API-Key": "n8n-secret", "X-Workspace-ID": "other-workspace"},
            json={"case_id": "case-1"},
        )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_upload_rejects_non_pdf():
    response = client.post("/upload", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert response.status_code == 400


def test_upload_rejects_spoofed_pdf_and_embedded_files():
    assert client.post("/upload", files={"file": ("fake.pdf", b"not a PDF", "application/pdf")}).status_code == 400
    document = fitz.open()
    document.new_page()
    document.embfile_add("payload.txt", b"hidden attachment")
    with_attachment = document.tobytes()
    document.close()
    response = client.post("/upload", files={"file": ("attached.pdf", with_attachment, "application/pdf")})
    assert response.status_code == 400
    assert "embedded files" in response.json()["detail"].lower()


def test_n8n_pdf_ingress_uses_the_same_validation(monkeypatch, sample_pdf_factory, fake_embeddings):
    monkeypatch.setattr(security, "N8N_WEBHOOK_API_KEY", "n8n-secret")
    headers = {"X-N8N-API-Key": "n8n-secret", "X-Workspace-ID": "n8n-owner"}
    rejected = client.post(
        "/integrations/n8n/documents", headers=headers,
        files={"file": ("fake.pdf", b"not a PDF", "application/pdf")},
    )
    assert rejected.status_code == 400
    source = Path(sample_pdf_factory(num_pages=1)).read_bytes()
    accepted = client.post(
        "/integrations/n8n/documents", headers=headers,
        files={"file": ("real.pdf", source, "application/pdf")},
    )
    assert accepted.status_code == 200
    assert accepted.json()["workspace_id"] == "n8n-owner"


def test_failed_reupload_keeps_prior_pdf_index_and_case(sample_pdf_factory, fake_embeddings):
    original = Path(sample_pdf_factory(num_pages=1, sentence="Original source. ")).read_bytes()
    assert client.post("/upload", files={"file": ("memo.pdf", original, "application/pdf")}).status_code == 200
    case_store.create_case({
        "case_id": "original-case", "workspace_id": DEFAULT_SESSION_ID,
        "document": {"filename": "memo.pdf"}, "status": "finalized", "stage": "finalized",
    })
    replacement = Path(sample_pdf_factory(num_pages=1, sentence="Replacement source. ")).read_bytes()
    with patch("services.document_publication.prepare_pdf", side_effect=RuntimeError("extraction failed")):
        response = client.post("/upload", files={"file": ("memo.pdf", replacement, "application/pdf")})
    assert response.status_code == 400
    assert Path(pdf_path("memo.pdf")).read_bytes() == original
    assert client.get("/documents").json()[0]["filename"] == "memo.pdf"
    assert case_store.get_latest_case("memo.pdf", DEFAULT_SESSION_ID) is not None


def test_api_key_protects_application_routes(monkeypatch):
    monkeypatch.setattr(security, "API_KEY", "secret123")
    monkeypatch.setattr(security, "LEGACY_API_KEY_ENABLED", True)
    assert client.get("/documents").status_code == 401
    assert client.get("/documents", headers={"X-API-Key": "secret123"}).status_code == 200
    assert client.get("/health").status_code == 200


def test_upload_list_and_delete_document(sample_pdf_factory, fake_embeddings):
    pdf_path = sample_pdf_factory(num_pages=2)
    with open(pdf_path, "rb") as pdf:
        response = client.post("/upload", files={"file": ("report.pdf", pdf, "application/pdf")})
    assert response.status_code == 200
    assert response.json()["chunk_count"] > 0

    response = client.get("/documents")
    assert [document["filename"] for document in response.json()] == ["report.pdf"]
    assert client.delete("/documents/report.pdf").json() == {"filename": "report.pdf", "deleted": True}
    assert client.get("/documents").json() == []


def test_document_session_isolation(sample_pdf_factory, fake_embeddings):
    pdf_path = sample_pdf_factory(num_pages=1)
    with open(pdf_path, "rb") as pdf:
        response = client.post("/upload", files={"file": ("private.pdf", pdf, "application/pdf")}, headers={"X-Session-ID": "a"})
    assert response.status_code == 200
    assert client.get("/documents", headers={"X-Session-ID": "b"}).json() == []
    assert client.delete("/documents/private.pdf", headers={"X-Session-ID": "b"}).status_code == 404
    assert client.get("/documents", headers={"X-Session-ID": "a"}).json()[0]["filename"] == "private.pdf"


def test_delete_document_removes_source_index_and_all_cases(sample_pdf_factory, fake_embeddings):
    source = sample_pdf_factory(num_pages=1)
    with open(source, "rb") as pdf:
        assert client.post(
            "/upload", files={"file": ("private.pdf", pdf, "application/pdf")},
            headers={"X-Session-ID": "owner"},
        ).status_code == 200
    for index in range(2):
        case_store.create_case({
            "case_id": f"case-{index}", "workspace_id": "owner",
            "document": {"filename": "private.pdf"},
            "status": "finalized", "stage": "finalized",
        })
    assert pdf_path("private.pdf", "owner") is not None
    assert client.delete("/documents/private.pdf", headers={"X-Session-ID": "other"}).status_code == 404
    assert case_store.get_latest_case("private.pdf", "owner") is not None

    response = client.delete("/documents/private.pdf", headers={"X-Session-ID": "owner"})
    assert response.status_code == 200
    assert client.get("/documents", headers={"X-Session-ID": "owner"}).json() == []
    assert pdf_path("private.pdf", "owner") is None
    assert case_store.get_latest_case("private.pdf", "owner") is None
    assert client.get("/documents/private.pdf/intelligence", headers={"X-Session-ID": "owner"}).status_code == 404


def test_delete_document_never_claims_success_if_source_removal_fails(sample_pdf_factory, fake_embeddings):
    source = sample_pdf_factory(num_pages=1)
    with open(source, "rb") as pdf:
        assert client.post("/upload", files={"file": ("private.pdf", pdf, "application/pdf")}).status_code == 200
    with patch("routers.documents.delete_pdf", side_effect=PermissionError("locked")):
        response = client.delete("/documents/private.pdf")
    assert response.status_code == 500
    assert client.get("/documents").json()[0]["filename"] == "private.pdf"


def test_browser_document_intelligence_runs_all_stages_in_order():
    base_case = {
        "case_id": "case-ui",
        "workspace_id": "browser-session",
        "document": {"filename": "report.pdf"},
        "status": "in_progress",
        "stage": "started",
        "document_profile": {},
        "facts": [],
        "obligations": [],
        "deadlines": [],
        "risks": [],
        "draft_action_pack": {},
        "audit": {},
        "final_action_pack": {"verification_status": "verified"},
        "warnings": [],
        "citations": [],
    }
    final_case = {**base_case, "status": "ready_for_human_review", "stage": "finalized"}
    with patch("routers.documents.document_case.start_case", return_value=base_case) as start, \
         patch("routers.documents.document_case.run_document_dna", return_value=base_case) as dna, \
         patch("routers.documents.document_case.run_facts_obligations", return_value=base_case) as facts, \
         patch("routers.documents.document_case.run_risk_prioritisation", return_value=base_case) as risks, \
         patch("routers.documents.document_case.run_draft_action_pack", return_value=base_case) as brief, \
         patch("routers.documents.document_case.run_mandatory_audit", return_value=base_case) as audit, \
         patch("routers.documents.document_case.finalize_case", return_value=final_case) as finalize, \
         patch("routers.documents.n8n_orchestrator.stream_durable_case", side_effect=document_routes._run_case_stages):
        response = client.post(
            "/documents/report.pdf/intelligence/run",
            headers={"X-Session-ID": "browser-session"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "ready_for_human_review"
    start.assert_called_once_with("report.pdf", "browser-session")
    for call in (dna, facts, risks, brief, audit, finalize):
        call.assert_called_once_with("case-ui", "browser-session")


def test_browser_document_intelligence_streams_real_stage_events():
    base_case = {
        "case_id": "case-ui-stream",
        "workspace_id": "browser-session",
        "document": {"filename": "report.pdf"},
        "status": "in_progress",
        "stage": "started",
        "document_profile": {},
        "facts": [],
        "obligations": [],
        "deadlines": [],
        "risks": [],
        "draft_action_pack": {},
        "audit": {},
        "final_action_pack": {"verification_status": "verified"},
        "warnings": [],
        "citations": [],
    }
    final_case = {**base_case, "status": "ready_for_human_review", "stage": "finalized"}
    n8n_stages = iter([
        ("started", base_case),
        ("dna_complete", base_case),
        ("facts_complete", base_case),
        ("risks_complete", base_case),
        ("brief_complete", base_case),
        ("audit_complete", base_case),
        ("finalized", final_case),
    ])
    with patch("routers.documents.n8n_orchestrator.stream_durable_case", return_value=n8n_stages):
        with client.stream(
            "POST",
            "/documents/report.pdf/intelligence/stream",
            headers={"X-Session-ID": "browser-session"},
        ) as response:
            events = [json.loads(line.removeprefix("data: ")) for line in response.iter_lines() if line]

    assert response.status_code == 200
    assert [event["stage"] for event in events[:-1]] == [
        "started",
        "dna_complete",
        "facts_complete",
        "risks_complete",
        "brief_complete",
        "audit_complete",
    ]
    assert events[-1]["type"] == "done"
    assert events[-1]["case"]["stage"] == "finalized"


def test_query_streams_tokens_citations_and_scores():
    chunks = [{"text": "The firm's tax practice uses AI.", "filename": "tax.pdf", "page_number": 1, "chunk_index": 0}]
    with patch.object(agent, "hybrid_search", return_value=chunks), \
         patch.object(agent, "_grade_chunks", return_value=[True]), \
         patch("routers.query.stream_answer", return_value=iter(["The firm uses AI [1]."])), \
         patch.object(evaluator, "score", side_effect=[0.9, 0.85]):
        with client.stream("POST", "/query", json={"question": "How does the firm use AI?"}) as response:
            lines = [line for line in response.iter_lines() if line]

    assert any('"type": "token"' in line for line in lines)
    assert '"type": "done"' in lines[-1]
    assert "tax.pdf" in lines[-1]


def test_supervisor_streams_only_document_analysis_events():
    responses = [
        {"tool_call": {"name": "search_documents", "input": {"query": "deduction rate"}}, "text": ""},
        {"tool_call": {"name": "finish", "input": {"summary": "The rate is 24%."}}, "text": ""},
    ]
    chunks = [{"text": "The rate is 24%.", "filename": "tax.pdf", "page_number": 2, "chunk_index": 0}]
    with patch.object(supervisor, "call_with_tools", side_effect=responses), \
         patch.object(agent, "hybrid_search", return_value=chunks), \
         patch.object(agent, "_grade_chunks", return_value=[True]), \
         patch.object(supervisor, "stream_answer", return_value=iter(["The rate is 24%." ])), \
         patch.object(evaluator, "score", return_value=0.9):
        with client.stream("POST", "/supervisor/run", json={"question": "What is the rate?"}) as response:
            lines = [line for line in response.iter_lines() if line]

    assert any('"type": "rag_token"' in line for line in lines)
    assert any('"type": "rag_done"' in line for line in lines)
    assert not any('"type": "action_' in line for line in lines)


def test_upload_rejects_oversized_file(monkeypatch, sample_pdf_factory):
    monkeypatch.setattr(upload_router, "MAX_UPLOAD_SIZE_BYTES", 10)
    pdf_path = sample_pdf_factory(num_pages=1)
    with open(pdf_path, "rb") as pdf:
        response = client.post("/upload", files={"file": ("big.pdf", pdf, "application/pdf")})
    assert response.status_code == 413
    assert "too large" in response.json()["detail"].lower()
