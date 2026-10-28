"""Real queue/RLS/commit-fence tests, with synthetic transports (never AI)."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

import psycopg
import pytest

from integration_tests.test_pgvector import store, add
from services.analysis_jobs import JobLedger, AnalysisJobConflict
from services.analysis_dispatcher import DispatchClient, AnalysisDispatcher
from services import case_store, pdf_storage


@pytest.fixture
def system(store, tmp_path, monkeypatch):
    monkeypatch.setattr(case_store, "CASE_DB_PATH", str(tmp_path / "cases.db"))
    monkeypatch.setattr(pdf_storage, "PDF_STORAGE_DIR", str(tmp_path / "pdfs"))
    return JobLedger(store), DispatchClient(os.environ["DMC_TEST_DISPATCH_URL"])


def wait_for(check, seconds=4):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        result = check()
        if result:
            return result
        time.sleep(0.01)
    raise AssertionError("Background condition did not complete within its test budget")


def final_case(job_id, workspace, filename):
    return case_store.create_case(
        {
            "case_id": job_id,
            "workspace_id": workspace,
            "document": {"filename": filename},
            "stage": "finalized",
            "status": "ready_for_human_review",
        }
    )


def test_dispatcher_role_has_only_narrow_functions_and_no_customer_table_access(system):
    jobs, client = system
    client.verify()
    for table in [
        "document_chunks",
        "analysis_jobs",
        "analysis_stages",
        "analysis_job_events",
    ]:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            client.call("SELECT * FROM dmc." + table)
    with jobs.store.transaction("alice") as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM dmc.dispatch_observe()")


def test_parallel_claims_obey_global_capacity_and_cannot_dispatch_twice(system):
    jobs, client = system
    for owner in ["alice", "bob", "carol", "dave"]:
        add(jobs.store, owner)
        jobs.admit(owner, "memo.pdf")
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(lambda _: client.claim(uuid.uuid4().hex), range(12)))
    claims = [row for row in claims if row]
    assert len(claims) == 2
    assert len({row["job_id"] for row in claims}) == 2
    assert client.claim(uuid.uuid4().hex) is None


def test_accepted_work_runs_after_restart_without_any_browser_observer(system):
    jobs, client = system
    add(jobs.store)
    job = jobs.admit("alice", "memo.pdf")
    calls = []

    def transport(filename, workspace, job_id, **_options):
        calls.append(job_id)
        final_case(job_id, workspace, filename)

    runner = AnalysisDispatcher(client, jobs, transport=transport, interval=0.01)
    runner.start()
    try:
        wait_for(lambda: jobs.get("alice", job["job_id"])["state"] == "complete")
        assert calls == [job["job_id"]]
    finally:
        runner.stop()


def test_cancel_queued_creates_new_identity_and_denies_late_old_callbacks(system):
    jobs, client = system
    add(jobs.store)
    old = jobs.admit("alice", "memo.pdf")
    assert jobs.resolve("alice", old["job_id"], "cancel")["state"] == "cancelled"
    assert client.claim(uuid.uuid4().hex) is None
    new = jobs.admit("alice", "memo.pdf")
    assert new["job_id"] != old["job_id"]
    with pytest.raises(AnalysisJobConflict):
        jobs.validate_callback("alice", old["job_id"], "memo.pdf")
    assert [event["event"] for event in jobs.events("alice", old["job_id"])] == [
        "user_cancel",
        "accepted",
    ]


def test_uncertain_is_never_replayed_and_late_valid_completion_is_reconciled(system):
    jobs, client = system
    add(jobs.store)
    job = jobs.admit("alice", "memo.pdf")
    original = uuid.uuid4().hex
    client.claim(original)
    with psycopg.connect(os.environ["DMC_TEST_VECTOR_ADMIN_URL"]) as conn:
        conn.execute(
            "UPDATE dmc.analysis_jobs SET heartbeat_at=now()-interval '60 seconds'"
        )
    assert jobs.reconcile("alice", job["job_id"])["state"] == "uncertain"
    assert client.claim(uuid.uuid4().hex) is None
    jobs.validate_callback("alice", job["job_id"], "memo.pdf")
    final_case(job["job_id"], "alice", "memo.pdf")
    assert jobs.reconcile("alice", job["job_id"])["state"] == "complete"
    assert jobs.get("alice", job["job_id"])["attempts"] == 1


def test_unsafe_close_is_refused_until_deadline_and_old_attempt_never_resumes(system):
    jobs, client = system
    add(jobs.store)
    old = jobs.admit("alice", "memo.pdf")
    client.claim(uuid.uuid4().hex)
    jobs.finish("alice", old["job_id"], "uncertain")
    with pytest.raises(AnalysisJobConflict):
        jobs.resolve("alice", old["job_id"], "close")
    with psycopg.connect(os.environ["DMC_TEST_VECTOR_ADMIN_URL"]) as conn:
        conn.execute("UPDATE dmc.analysis_jobs SET deadline=now()-interval '1 second'")
    assert jobs.resolve("alice", old["job_id"], "close")["state"] == "cancelled"
    new = jobs.admit("alice", "memo.pdf")
    assert new["job_id"] != old["job_id"]
    with pytest.raises(AnalysisJobConflict):
        jobs.validate_callback("alice", old["job_id"], "memo.pdf")


def test_duplicate_stage_is_not_reentered_and_completed_stage_is_read_only(system):
    jobs, client = system
    add(jobs.store)
    job = jobs.admit("alice", "memo.pdf")
    client.claim(uuid.uuid4().hex)
    with jobs.stage_scope("alice", job["job_id"], "memo.pdf", "facts") as execute:
        assert execute
        with pytest.raises(AnalysisJobConflict):
            with jobs.stage_scope("alice", job["job_id"], "memo.pdf", "facts"):
                pytest.fail("A duplicate stage entered provider work")
    with jobs.stage_scope("alice", job["job_id"], "memo.pdf", "facts") as execute:
        assert not execute
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert (
                pool.submit(jobs.resolve, "alice", job["job_id"], "cancel").result(
                    timeout=2
                )["state"]
                == "cancel_requested"
            )


def test_cancel_fences_inflight_case_commit_without_overwriting_previous_result(system):
    jobs, client = system
    add(jobs.store)
    job = jobs.admit("alice", "memo.pdf")
    client.claim(uuid.uuid4().hex)
    previous = case_store.create_case(
        {
            "case_id": job["job_id"],
            "workspace_id": "alice",
            "document": {"filename": "memo.pdf"},
            "stage": "started",
            "status": "in_progress",
        }
    )
    entered, release = threading.Event(), threading.Event()

    def stage():
        with pytest.raises(AnalysisJobConflict):
            with jobs.stage_scope("alice", job["job_id"], "memo.pdf", "facts"):
                entered.set()
                assert release.wait(3)
                case_store.save_case({**previous, "stage": "facts_complete"})

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(stage)
        assert entered.wait(2)
        assert (
            jobs.resolve("alice", job["job_id"], "cancel")["state"]
            == "cancel_requested"
        )
        release.set()
        future.result(timeout=3)
    assert case_store.get_case(job["job_id"], "alice")["stage"] == "started"


def test_browser_close_does_not_cancel_background_work(system, monkeypatch):
    from services import analysis_dispatcher, analysis_jobs, n8n_orchestrator, security

    jobs, client = system
    add(jobs.store)
    released = threading.Event()
    calls = []

    def transport(filename, workspace, job_id, **_options):
        calls.append(job_id)
        case = case_store.create_case(
            {
                "case_id": job_id,
                "workspace_id": workspace,
                "document": {"filename": filename},
                "stage": "started",
                "status": "in_progress",
            }
        )
        assert released.wait(3)
        case_store.save_case({**case, "stage": "finalized"})

    runner = AnalysisDispatcher(client, jobs, transport=transport, interval=0.01)
    monkeypatch.setattr(analysis_dispatcher, "require_dispatcher", lambda: runner)
    monkeypatch.setattr(analysis_jobs, "ledger", lambda: jobs)
    monkeypatch.setattr(
        n8n_orchestrator, "N8N_ORCHESTRATOR_URL", "http://fixture.invalid"
    )
    monkeypatch.setattr(security, "N8N_WEBHOOK_API_KEY", "synthetic")
    runner.start()
    try:
        observer = n8n_orchestrator.stream_durable_case("memo.pdf", "alice")
        assert next(observer)[0] == "started"
        observer.close()
        released.set()
        wait_for(lambda: jobs.get("alice", calls[0])["state"] == "complete")
        assert len(calls) == 1
    finally:
        released.set()
        runner.stop()


def test_events_are_tenant_scoped_and_cannot_be_rewritten(system):
    jobs, _client = system
    add(jobs.store)
    job = jobs.admit("alice", "memo.pdf")
    assert jobs.events("bob", job["job_id"]) == []
    assert jobs.list("bob") == []
    with pytest.raises(KeyError):
        jobs.resolve("bob", job["job_id"], "cancel")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with jobs.store.transaction("alice") as conn:
            conn.execute("UPDATE dmc.analysis_job_events SET actor='forged'")


def test_acceptance_and_event_write_roll_back_together(system, monkeypatch):
    jobs, _client = system
    add(jobs.store)

    def fail(*_args):
        raise RuntimeError("Synthetic event-store failure")

    monkeypatch.setattr(jobs, "_event", fail)
    with pytest.raises(RuntimeError):
        jobs.admit("alice", "memo.pdf")
    assert jobs.list("alice") == []


def test_job_http_controls_are_tenant_scoped_csrf_guarded_and_metadata_only(
    system, tmp_path, monkeypatch
):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    monkeypatch.setenv("OTEL_CONSOLE_EXPORT", "false")
    monkeypatch.setenv("ANALYSIS_DISPATCH_ENABLED", "false")
    import main
    from fastapi.testclient import TestClient
    from services import analysis_jobs, observability
    from services.authentication import require_authenticated_user
    from services.session_scope import get_session_id

    jobs, _client = system
    add(jobs.store)
    import db.vector_store as vectors
    import routers.analysis as analysis_routes

    monkeypatch.setattr(vectors, "_collection", jobs.store)
    monkeypatch.setattr(analysis_routes, "ledger", lambda: jobs)
    job = jobs.admit("alice", "memo.pdf")
    monkeypatch.setattr(analysis_jobs, "ledger", lambda: jobs)
    monkeypatch.setattr(observability, "OBS_DB_PATH", str(tmp_path / "metrics.db"))
    actor = ["alice"]
    previous = main.app.dependency_overrides.copy()
    main.app.dependency_overrides[require_authenticated_user] = lambda: {"id": actor[0]}
    main.app.dependency_overrides[get_session_id] = lambda: actor[0]
    try:
        client = TestClient(main.app)
        response = client.get("/analysis/jobs")
        assert response.status_code == 200
        assert response.json()[0]["job_id"] == job["job_id"]
        assert not any(
            key in response.json()[0]
            for key in [
                "worker_id",
                "pipeline_sha",
                "generation",
                "fingerprint",
                "password",
            ]
        )
        actor[0] = "bob"
        assert client.get("/analysis/jobs").json() == []
        assert client.get("/analysis/jobs/" + job["job_id"]).status_code == 404
        assert (
            client.get("/analysis/jobs/" + job["job_id"] + "/result").status_code == 404
        )
        headers = {"Origin": "http://localhost:5173", "X-CSRF-Protection": "nexus-v1"}
        assert (
            client.post(
                "/analysis/jobs/" + job["job_id"] + "/resolve",
                headers=headers,
                json={"action": "cancel"},
            ).status_code
            == 404
        )
        actor[0] = "alice"
        assert (
            client.post(
                "/analysis/jobs/" + job["job_id"] + "/resolve",
                headers={**headers, "Origin": "https://evil.test"},
                json={"action": "cancel"},
            ).status_code
            == 403
        )
        assert jobs.get("alice", job["job_id"])["state"] == "accepted"
        assert (
            client.post(
                "/analysis/jobs/" + job["job_id"] + "/resolve",
                headers=headers,
                json={"action": "retry"},
            ).status_code
            == 422
        )
        response = client.post(
            "/analysis/jobs/" + job["job_id"] + "/resolve",
            headers=headers,
            json={"action": "cancel"},
        )
        assert response.status_code == 200 and response.json()["state"] == "cancelled"
    finally:
        main.app.dependency_overrides.clear()
        main.app.dependency_overrides.update(previous)


def test_expired_stage_budget_fences_save_even_before_job_deadline(system):
    from services.budget import operation_budget, BudgetExpired

    jobs, client = system
    add(jobs.store)
    job = jobs.admit("alice", "memo.pdf")
    client.claim(uuid.uuid4().hex)
    saved = case_store.create_case(
        {
            "case_id": job["job_id"],
            "workspace_id": "alice",
            "document": {"filename": "memo.pdf"},
            "stage": "started",
            "status": "in_progress",
        }
    )
    with pytest.raises(BudgetExpired):
        with operation_budget(0.001):
            with jobs.stage_scope(
                "alice", job["job_id"], "memo.pdf", "deadline-fixture"
            ):
                time.sleep(0.01)
                case_store.save_case({**saved, "stage": "finalized"})
    assert case_store.get_case(job["job_id"], "alice")["stage"] == "started"


def test_actual_process_loss_and_restart_never_replays_delivered_work(system, tmp_path):
    jobs, _client = system
    add(jobs.store)
    old = jobs.admit("alice", "memo.pdf")
    program = r"""
import os,time
from pathlib import Path
from db.vector_store import PgVectorStore,VectorSettings
from services.analysis_dispatcher import AnalysisDispatcher,DispatchClient
from services.analysis_jobs import JobLedger
from services import case_store
store=PgVectorStore(VectorSettings(os.environ['DMC_TEST_VECTOR_URL'],3,'synthetic-integration'))
jobs=JobLedger(store)
def transport(filename,workspace,job_id,**options):
    if os.environ['DMC_TEST_CRASH']=='true':
        # Simulates process death after delivery, without graceful worker cleanup.
        os._exit(0)
    assert workspace=='bob','Delivered work was replayed after process restart'
    case_store.create_case({'case_id':job_id,'workspace_id':workspace,
        'document':{'filename':filename},'stage':'finalized','status':'ready_for_human_review'})
runner=AnalysisDispatcher(DispatchClient(os.environ['DMC_TEST_DISPATCH_URL']),jobs,transport=transport,interval=.02)
runner.start()
try:
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        target=os.environ.get('DMC_TEST_TARGET')
        if target and jobs.get('bob',target)['state']=='complete':break
        time.sleep(.02)
    else:raise AssertionError('Process recovery test timed out')
finally:
    runner.stop();store.close()
"""
    environment = {
        **os.environ,
        "DMC_TEST_CRASH": "true",
        "DOCUMENT_CASE_DB_PATH": case_store.CASE_DB_PATH,
        "PDF_STORAGE_DIR": pdf_storage.PDF_STORAGE_DIR,
    }
    first = subprocess.run(
        [sys.executable, "-c", program],
        env=environment,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        timeout=20,
    )
    assert first.returncode == 0, first.stderr.decode(errors="replace")[-1000:]
    assert jobs.get("alice", old["job_id"])["state"] == "dispatching"
    with psycopg.connect(os.environ["DMC_TEST_VECTOR_ADMIN_URL"]) as conn:
        conn.execute(
            "UPDATE dmc.analysis_jobs SET heartbeat_at=now()-interval '60 seconds'"
        )
    assert jobs.reconcile("alice", old["job_id"])["state"] == "uncertain"
    add(jobs.store, "bob")
    new = jobs.admit("bob", "memo.pdf")
    second = subprocess.run(
        [sys.executable, "-c", program],
        env={
            **environment,
            "DMC_TEST_CRASH": "false",
            "DMC_TEST_TARGET": new["job_id"],
        },
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        timeout=20,
    )
    assert second.returncode == 0, second.stderr.decode(errors="replace")[-1000:]
    assert jobs.get("alice", old["job_id"])["attempts"] == 1
    assert jobs.get("alice", old["job_id"])["state"] == "uncertain"
    assert jobs.get("bob", new["job_id"])["state"] == "complete"


def test_committed_stage_with_lost_ledger_ack_is_reconciled_without_provider_replay(
    system,
):
    jobs, client = system
    add(jobs.store)
    job = jobs.admit("alice", "memo.pdf")
    client.claim(uuid.uuid4().hex)
    case_store.create_case(
        {
            "case_id": job["job_id"],
            "workspace_id": "alice",
            "document": {"filename": "memo.pdf"},
            "stage": "facts_complete",
            "status": "in_progress",
        }
    )
    with jobs.store.transaction("alice") as conn:
        conn.execute(
            "INSERT INTO dmc.analysis_stages(workspace_id,job_id,stage,state,token) VALUES ('alice',%s,'run_facts_obligations','running',%s)",
            (job["job_id"], uuid.uuid4().hex),
        )
    jobs.reconcile("alice", job["job_id"])
    with jobs.stage_scope(
        "alice", job["job_id"], "memo.pdf", "run_facts_obligations"
    ) as execute:
        assert execute is False


def test_saved_result_is_exact_to_attempt_and_current_source_generation(system):
    jobs, client = system
    add(jobs.store)
    old = jobs.admit("alice", "memo.pdf")
    client.claim(uuid.uuid4().hex)
    case_store.create_case(
        {
            "case_id": old["job_id"],
            "workspace_id": "alice",
            "document": {"filename": "memo.pdf"},
            "stage": "facts_complete",
            "status": "in_progress",
        }
    )
    jobs.finish("alice", old["job_id"], "failed")
    jobs.resolve("alice", old["job_id"], "close")
    new = jobs.admit("alice", "memo.pdf")
    assert new["job_id"] != old["job_id"]
    final_case(new["job_id"], "alice", "memo.pdf")
    assert jobs.saved_result("alice", old["job_id"])["case_id"] == old["job_id"]
    assert jobs.saved_result("alice", new["job_id"])["case_id"] == new["job_id"]
    assert jobs.saved_result("bob", old["job_id"]) is None
    add(jobs.store, ids=["new-fragment"])
    assert jobs.saved_result("alice", old["job_id"]) is None
    assert jobs.saved_result("alice", new["job_id"]) is None


def test_cancellation_ack_is_serialized_with_case_commit(system):
    from services.workspace_lock import workspace_access

    jobs, client = system
    add(jobs.store)
    job = jobs.admit("alice", "memo.pdf")
    client.claim(uuid.uuid4().hex)
    started = threading.Event()

    def cancel():
        started.set()
        return jobs.resolve("alice", job["job_id"], "cancel")

    with ThreadPoolExecutor(max_workers=1) as pool:
        with workspace_access("alice"):
            future = pool.submit(cancel)
            assert started.wait(1)
            with pytest.raises(TimeoutError):
                future.result(timeout=0.1)
            saved = case_store.create_case(
                {
                    "case_id": job["job_id"],
                    "workspace_id": "alice",
                    "document": {"filename": "memo.pdf"},
                    "stage": "started",
                    "status": "in_progress",
                }
            )
        assert future.result(timeout=2)["state"] == "cancel_requested"
    with pytest.raises(AnalysisJobConflict):
        with jobs.stage_scope("alice", job["job_id"], "memo.pdf", "facts"):
            case_store.save_case({**saved, "stage": "facts_complete"})
    assert case_store.get_case(job["job_id"], "alice")["stage"] == "started"
