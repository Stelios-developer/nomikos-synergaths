from unittest.mock import patch

from fastapi.testclient import TestClient

import main
import services.auditor as auditor

client = TestClient(main.app)


def test_audit_run_returns_per_sentence_verdicts():
    body = {
        "answer": "The rate is 24% [1]. It applies to all spend [2].",
        "citations": [{"filename": "tax.pdf", "page": 2, "text": "The R&D deduction rate is 24%."}],
    }
    fake_response = (
        '[{"supported": true, "reason": "matches"}, {"supported": false, "reason": "not found"}]'
    )
    with patch.object(auditor, "complete", return_value=fake_response):
        resp = client.post("/audit/run", json=body)

    assert resp.status_code == 200
    sentences = resp.json()["sentences"]
    assert len(sentences) == 2
    assert sentences[0]["supported"] is True
    assert sentences[1]["supported"] is False


def test_audit_run_with_no_citations_marks_everything_unsupported():
    body = {"answer": "A claim with nothing to back it.", "citations": []}
    resp = client.post("/audit/run", json=body)

    assert resp.status_code == 200
    sentences = resp.json()["sentences"]
    assert len(sentences) == 1
    assert sentences[0]["supported"] is False


def test_audit_run_rejects_malformed_body():
    resp = client.post("/audit/run", json={"citations": []})  # missing required "answer"
    assert resp.status_code == 422
