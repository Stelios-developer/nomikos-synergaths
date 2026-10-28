from concurrent.futures import ThreadPoolExecutor
import os

import psycopg
import pytest

from services.analysis_jobs import AnalysisJobConflict, JobLedger
from integration_tests.test_pgvector import add, store


def seed(store, filename, key):
    store.add(
        workspace_id="alice",
        ids=[key],
        documents=["Synthetic evidence"],
        metadatas=[{"filename": filename, "session_id": "alice"}],
        embeddings=[[1, 0, 0]],
    )


def test_concurrent_admission_has_one_durable_dispatch(store):
    add(store)
    jobs = JobLedger(store)
    with ThreadPoolExecutor(max_workers=8) as pool:
        admitted = list(pool.map(lambda _: jobs.admit("alice", "memo.pdf"), range(16)))
    assert len({job["job_id"] for job in admitted}) == 1
    job_id = admitted[0]["job_id"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(lambda _: jobs.claim("alice", job_id), range(16)))
    assert claims.count(True) == 1
    assert jobs.get("alice", job_id)["attempts"] == 1


def test_uncertain_delivery_never_dispatches_again_after_new_ledger_instance(store):
    add(store)
    jobs = JobLedger(store)
    job = jobs.admit("alice", "memo.pdf")
    assert jobs.claim("alice", job["job_id"])
    jobs.finish("alice", job["job_id"], "uncertain")
    restarted = JobLedger(store)
    assert restarted.admit("alice", "memo.pdf")["state"] == "uncertain"
    assert not restarted.claim("alice", job["job_id"])


def test_case_identity_and_callback_scope_are_verified(store):
    add(store)
    jobs = JobLedger(store)
    job = jobs.admit("alice", "memo.pdf")
    jobs.claim("alice", job["job_id"])
    assert jobs.get("bob", job["job_id"]) is None
    with pytest.raises(AnalysisJobConflict):
        jobs.validate_callback("bob", job["job_id"], "memo.pdf")
    with pytest.raises(AnalysisJobConflict):
        jobs.validate_callback("alice", job["job_id"], "other.pdf")
    assert (
        jobs.validate_callback("alice", job["job_id"], "memo.pdf")["job_id"]
        == job["job_id"]
    )


def test_safe_pre_dispatch_failure_has_bounded_explicit_retries(store):
    add(store)
    jobs = JobLedger(store)
    for attempt in range(1, 4):
        job = jobs.admit("alice", "memo.pdf")
        assert jobs.claim("alice", job["job_id"])
        assert jobs.get("alice", job["job_id"])["attempts"] == attempt
        jobs.finish("alice", job["job_id"], "failed")
    assert jobs.admit("alice", "memo.pdf")["state"] == "failed"
    assert not jobs.claim("alice", job["job_id"])


def test_workspace_quota_and_changed_document_are_not_bypassed(store):
    jobs = JobLedger(store)
    for index in range(3):
        seed(store, f"{index}.pdf", str(index))
    first = jobs.admit("alice", "0.pdf")
    jobs.admit("alice", "1.pdf")
    with pytest.raises(AnalysisJobConflict):
        jobs.admit("alice", "2.pdf")
    jobs.claim("alice", first["job_id"])
    seed(store, "0.pdf", "replacement-generation")
    with pytest.raises(AnalysisJobConflict):
        jobs.validate_callback("alice", first["job_id"], "0.pdf")


def test_job_rls_and_expired_callback_fail_closed(store):
    add(store)
    jobs = JobLedger(store)
    job = jobs.admit("alice", "memo.pdf")
    jobs.claim("alice", job["job_id"])
    with psycopg.connect(os.environ["DMC_TEST_VECTOR_URL"]) as conn:
        assert conn.execute("SELECT count(*) FROM dmc.analysis_jobs").fetchone()[0] == 0
    with psycopg.connect(os.environ["DMC_TEST_VECTOR_ADMIN_URL"]) as conn:
        conn.execute("UPDATE dmc.analysis_jobs SET deadline=now()-interval '1 second'")
    with pytest.raises(AnalysisJobConflict):
        jobs.validate_callback("alice", job["job_id"], "memo.pdf")


def test_document_erasure_removes_only_its_jobs_and_rejects_late_callbacks(store):
    add(store)
    add(store, "bob")
    jobs = JobLedger(store)
    alice = jobs.admit("alice", "memo.pdf")
    jobs.claim("alice", alice["job_id"])
    bob = jobs.admit("bob", "memo.pdf")
    store.forget_analysis_jobs("alice", "memo.pdf")
    assert jobs.get("alice", alice["job_id"]) is None
    assert jobs.get("bob", bob["job_id"]) is not None
    with pytest.raises(AnalysisJobConflict):
        jobs.validate_callback("alice", alice["job_id"], "memo.pdf")


@pytest.fixture
def bridge(store, tmp_path, monkeypatch):
    from services import (
        analysis_jobs,
        case_store,
        n8n_orchestrator,
        analysis_dispatcher,
        pdf_storage,
        security,
    )

    monkeypatch.setattr(case_store, "CASE_DB_PATH", str(tmp_path / "cases.sqlite"))
    monkeypatch.setattr(pdf_storage, "PDF_STORAGE_DIR", str(tmp_path / "pdfs"))
    monkeypatch.setattr(analysis_jobs, "ledger", lambda: JobLedger(store))
    monkeypatch.setattr(
        n8n_orchestrator, "N8N_ORCHESTRATOR_URL", "http://fixture.invalid/webhook"
    )
    monkeypatch.setattr(security, "N8N_WEBHOOK_API_KEY", "synthetic-not-a-secret")
    monkeypatch.setattr(n8n_orchestrator, "N8N_ORCHESTRATOR_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(
        n8n_orchestrator, "N8N_ORCHESTRATOR_POLL_INTERVAL_SECONDS", 0.005
    )
    monkeypatch.setattr(n8n_orchestrator, "N8N_COMPLETION_GRACE_SECONDS", 0.01)
    add(store)
    dispatcher=analysis_dispatcher.AnalysisDispatcher(
        analysis_dispatcher.DispatchClient(os.environ['DMC_TEST_DISPATCH_URL']),JobLedger(store),interval=0.01)
    def require():
        if not dispatcher.threads:dispatcher.start()
        return dispatcher
    monkeypatch.setattr(analysis_dispatcher,'require_dispatcher',require)
    try:
        yield n8n_orchestrator, case_store, JobLedger(store)
    finally:
        dispatcher.stop()


def test_lost_response_after_final_commit_recovers_without_second_dispatch(
    bridge, monkeypatch
):
    service, cases, jobs = bridge
    dispatched = []

    def remote(filename, workspace, job_id,**_options):
        dispatched.append(job_id)
        jobs.validate_callback(workspace, job_id, filename)
        cases.create_case(
            {
                "case_id": job_id,
                "workspace_id": workspace,
                "document": {"filename": filename},
                "status": "ready_for_human_review",
                "stage": "finalized",
            }
        )
        raise service.N8nOrchestratorError(
            "Synthetic lost acknowledgement", uncertain=True
        )

    monkeypatch.setattr(service, "trigger_case_workflow", remote)
    first=list(service.stream_durable_case("memo.pdf", "alice"))
    assert first[-1][0]=='finalized'
    # A fresh observer sees the persisted artifact, not a second webhook.
    result = list(service.stream_durable_case("memo.pdf", "alice"))
    assert result[-1][0] == "finalized"
    assert len(dispatched) == 1
    assert jobs.get("alice", dispatched[0])["state"] == "complete"


def test_restart_after_claim_does_not_replay_unknown_delivery(bridge, monkeypatch):
    service, _cases, jobs = bridge
    admitted = jobs.admit("alice", "memo.pdf", seconds=0.1)
    assert jobs.claim("alice", admitted["job_id"])

    def forbidden(*_args):
        pytest.fail("A durable dispatch claim was replayed")

    monkeypatch.setattr(service, "trigger_case_workflow", forbidden)
    with pytest.raises(service.N8nOrchestratorError) as error:
        list(service.stream_durable_case("memo.pdf", "alice"))
    assert error.value.uncertain
    assert jobs.get("alice", admitted["job_id"])["state"] == "uncertain"
    assert jobs.get("alice", admitted["job_id"])["attempts"] == 1


def test_acknowledged_workflow_without_artifact_is_uncertain(bridge, monkeypatch):
    service, _cases, jobs = bridge
    monkeypatch.setattr(service, "trigger_case_workflow", lambda *_args,**_options: None)
    with pytest.raises(service.N8nOrchestratorError) as error:
        list(service.stream_durable_case("memo.pdf", "alice"))
    assert error.value.uncertain
    assert jobs.admit("alice", "memo.pdf")["state"] == "uncertain"
