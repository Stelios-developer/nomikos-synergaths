import json
import threading

import pytest

from services import n8n_orchestrator, security


def test_trigger_case_workflow_posts_only_server_side_contract(monkeypatch):
    from subprocess import CompletedProcess
    captured = {}
    monkeypatch.setattr(n8n_orchestrator, 'N8N_ORCHESTRATOR_URL', 'http://n8n.test/webhook/case')
    monkeypatch.setattr(security, 'N8N_WEBHOOK_API_KEY', 'bridge-secret')
    def child(args, **kwargs):
        captured.update(kwargs)
        assert 'bridge-secret' not in repr(args)
        return CompletedProcess(args,0,stdout=b'{"kind":"http","status":200}')
    monkeypatch.setattr(n8n_orchestrator.subprocess,'run',child)
    n8n_orchestrator.trigger_case_workflow('contract.pdf','workspace-a')
    packet=json.loads(captured['input'])
    assert packet['url']=='http://n8n.test/webhook/case'
    assert packet['body']=={'filename':'contract.pdf','workspace_id':'workspace-a'}
    assert packet['headers']['X-N8N-API-Key']=='bridge-secret'
    assert packet['headers']['X-Workspace-ID']=='workspace-a'
    assert captured['timeout']==n8n_orchestrator.N8N_ORCHESTRATOR_TIMEOUT_SECONDS


def test_stream_case_via_n8n_maps_only_new_persisted_case_stages(monkeypatch):
    previous_case = {"case_id": "old-case", "stage": "finalized"}
    final_case = {"case_id": "new-case", "stage": "finalized", "status": "ready_for_human_review"}
    persisted_updates = [
        {"case_id": "new-case", "stage": "started"},
        {"case_id": "new-case", "stage": "dna_complete"},
        {"case_id": "new-case", "stage": "facts_complete"},
        {"case_id": "new-case", "stage": "risks_complete"},
        {"case_id": "new-case", "stage": "draft_complete"},
        {"case_id": "new-case", "stage": "audited"},
        final_case,
    ]
    responses = iter([previous_case, *persisted_updates])
    release_webhook = threading.Event()

    monkeypatch.setattr(n8n_orchestrator, "N8N_ORCHESTRATOR_URL", "http://n8n.test/webhook/case")
    monkeypatch.setattr(security, "N8N_WEBHOOK_API_KEY", "bridge-secret")
    monkeypatch.setattr(n8n_orchestrator, "N8N_ORCHESTRATOR_POLL_INTERVAL_SECONDS", 0.001)
    monkeypatch.setattr(n8n_orchestrator, "N8N_ORCHESTRATOR_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(n8n_orchestrator, "N8N_COMPLETION_GRACE_SECONDS", 0.1)

    def fake_latest_case(_filename, _workspace_id):
        try:
            current = next(responses)
        except StopIteration:
            current = final_case
        if current["stage"] == "finalized" and current["case_id"] == "new-case":
            release_webhook.set()
        return current

    def fake_trigger(_filename, _workspace_id):
        assert release_webhook.wait(timeout=1)

    monkeypatch.setattr(n8n_orchestrator.case_store, "get_latest_case", fake_latest_case)
    monkeypatch.setattr(n8n_orchestrator, "trigger_case_workflow", fake_trigger)

    events = list(n8n_orchestrator.stream_case_via_n8n("contract.pdf", "workspace-a"))

    assert [stage for stage, _case in events] == [
        "started",
        "dna_complete",
        "facts_complete",
        "risks_complete",
        "brief_complete",
        "audit_complete",
        "finalized",
    ]
    assert events[-1][1] == final_case


def test_stream_case_via_n8n_fails_closed_without_a_webhook_url(monkeypatch):
    monkeypatch.setattr(n8n_orchestrator, "N8N_ORCHESTRATOR_URL", "")
    monkeypatch.setattr(security, "N8N_WEBHOOK_API_KEY", "bridge-secret")

    with pytest.raises(n8n_orchestrator.N8nOrchestratorError, match="not configured"):
        next(n8n_orchestrator.stream_case_via_n8n("contract.pdf", "workspace-a"))
