"""Bridge browser document-intelligence requests to the real n8n workflow.

The browser uploads and indexes the PDF through the API first.  This module
then starts the active n8n Agent Orchestrator workflow and observes the
workspace-scoped case file it produces.  It deliberately does not reproduce
any agent logic: the HTTP nodes in n8n call the integration endpoints and
persist every stage in ``case_store``.
"""
from __future__ import annotations

import json
import os
import threading
import time
import subprocess
import sys
from pathlib import Path
from collections.abc import Generator
from dataclasses import dataclass
from datetime import datetime, timezone

from services import analysis_jobs, case_store, security
from services.resilience import DependencyGuard, DependencyRejected


N8N_ORCHESTRATOR_URL = os.getenv("N8N_ORCHESTRATOR_URL", "").strip()
N8N_ORCHESTRATOR_POLL_INTERVAL_SECONDS = 0.25
N8N_ORCHESTRATOR_TIMEOUT_SECONDS = 900.0
N8N_COMPLETION_GRACE_SECONDS = 3.0
N8N_RESPONSE_LIMIT_BYTES = 1024 * 1024


# The browser UI intentionally has a simpler vocabulary than the persisted
# case file.  These are aliases for real, completed server-side stages.
FRONTEND_STAGE_BY_CASE_STAGE = {
    "started": "started",
    "dna_complete": "dna_complete",
    "facts_complete": "facts_complete",
    "risks_complete": "risks_complete",
    "draft_complete": "brief_complete",
    "audited": "audit_complete",
}


class N8nOrchestratorError(RuntimeError):
    """Raised when the real n8n workflow cannot safely complete."""
    def __init__(self, message: str, *, retryable=False, uncertain=False):
        super().__init__(message)
        self.retryable = retryable
        self.uncertain = uncertain


_workflow_guard = DependencyGuard(count_failure=lambda exc: isinstance(exc, N8nOrchestratorError) and exc.retryable)


@dataclass
class _WebhookRun:
    done: threading.Event
    error: Exception | None = None


def _require_configuration() -> tuple[str, str]:
    url = N8N_ORCHESTRATOR_URL.strip()
    api_key = security.N8N_WEBHOOK_API_KEY
    if not url:
        raise N8nOrchestratorError(
            "The n8n orchestrator is not configured. Set N8N_ORCHESTRATOR_URL before running document intelligence."
        )
    if not api_key:
        raise N8nOrchestratorError(
            "The n8n orchestrator credential is not configured. Set N8N_WEBHOOK_API_KEY before running document intelligence."
        )
    return url, api_key


def trigger_case_workflow(filename: str, workspace_id: str, job_id=None, *, cancel_event=None, timeout_seconds=None) -> None:
    _require_configuration()
    try:
        with _workflow_guard.call():
            _post_case_workflow(filename, workspace_id, job_id,cancel_event=cancel_event,timeout_seconds=timeout_seconds)
    except DependencyRejected as exc:
        raise N8nOrchestratorError(str(exc), retryable=True) from exc


def _post_case_workflow(filename: str, workspace_id: str, job_id=None, *,cancel_event=None,timeout_seconds=None) -> None:
    """POST a pre-indexed browser document to n8n's production webhook.

    The API key stays server-side.  n8n receives it only as an HTTP header so
    its visible validation node can reject forged calls before an agent runs.
    """
    url, api_key = _require_configuration()
    payload = {"filename": filename, "workspace_id": workspace_id}
    if job_id:
        payload['analysis_job_id'] = job_id
    timeout=N8N_ORCHESTRATOR_TIMEOUT_SECONDS if timeout_seconds is None else min(timeout_seconds,N8N_ORCHESTRATOR_TIMEOUT_SECONDS)
    packet = {'url':url, 'body':payload, 'timeout':timeout,
              'limit':N8N_RESPONSE_LIMIT_BYTES, 'headers':{
                  'Content-Type':'application/json','Accept':'application/json',
                  'X-N8N-API-Key':api_key,'X-Workspace-ID':workspace_id}}
    try:
        command=[sys.executable,str(Path(__file__).with_name('webhook_task.py'))]
        if cancel_event is None:
            completed = subprocess.run(command,
                input=json.dumps(packet).encode(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=timeout, check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        else:
            if cancel_event.is_set():raise N8nOrchestratorError('The analysis dispatcher is stopping.',retryable=True)
            process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                                     creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            try:
                deadline=time.monotonic()+timeout
                body=json.dumps(packet).encode()
                sent=False
                while True:
                    if cancel_event.is_set() or time.monotonic()>=deadline:
                        process.kill();process.communicate()
                        raise N8nOrchestratorError('The local analysis transport stopped; remote progress must be checked.',retryable=True,uncertain=sent)
                    try:
                        sent=True
                        stdout,_=process.communicate(input=body,timeout=min(0.2,max(0.01,deadline-time.monotonic())))
                        completed=subprocess.CompletedProcess(command,process.returncode,stdout=stdout)
                        break
                    except subprocess.TimeoutExpired:
                        body=None
            finally:
                if process.poll() is None:process.kill();process.communicate()
    except subprocess.TimeoutExpired as exc:
        raise N8nOrchestratorError('The n8n orchestrator timed out before the document workflow completed.',retryable=True,uncertain=True) from exc
    except OSError as exc:
        raise N8nOrchestratorError('The webhook transport could not start.',retryable=True) from exc
    try:
        if completed.returncode!=0 or len(completed.stdout)>4096:
            raise ValueError('invalid transport result')
        result=json.loads(completed.stdout)
        kind=result['kind']
    except Exception as exc:
        raise N8nOrchestratorError('The webhook transport did not confirm its outcome.',retryable=True,uncertain=True) from exc
    if kind=='http' and 200<=int(result['status'])<300:
        return
    if kind=='http':
        status=int(result['status'])
        raise N8nOrchestratorError(f'n8n returned HTTP {status} while running the document workflow.',
                                  retryable=status>=500 or status==429,uncertain=status not in {401,403,404})
    if kind=='oversize':
        raise N8nOrchestratorError('The n8n response exceeded the safe size limit.',retryable=True,uncertain=True)
    raise N8nOrchestratorError('The n8n orchestrator could not be reached or confirm its outcome.',retryable=True,uncertain=True)


def _run_webhook(run: _WebhookRun, filename: str, workspace_id: str, job_id=None) -> None:
    try:
        if job_id:
            trigger_case_workflow(filename, workspace_id, job_id)
        else:
            trigger_case_workflow(filename, workspace_id)
        if job_id:
            current = case_store.get_case(job_id,workspace_id)
            if current and current.get('stage')=='finalized':
                analysis_jobs.ledger().finish(workspace_id,job_id,'complete')
    except Exception as exc:  # surfaced safely from the SSE generator
        run.error = exc
        if job_id:
            try:
                state = 'uncertain' if not isinstance(exc,N8nOrchestratorError) or exc.uncertain else 'failed'
                analysis_jobs.ledger().finish(workspace_id,job_id,state)
            except Exception:
                pass  # the durable dispatch claim remains; it must never be replayed blindly
    finally:
        run.done.set()


def _new_case_for_request(case: dict | None, previous_case_id: str | None) -> bool:
    return bool(case and case.get("case_id") and case.get("case_id") != previous_case_id)


def _workflow_error(run: _WebhookRun) -> N8nOrchestratorError:
    if isinstance(run.error, N8nOrchestratorError):
        return run.error
    return N8nOrchestratorError("The n8n document workflow could not complete.")


def stream_case_via_n8n(filename: str, workspace_id: str, *, job=None, dispatch=True) -> Generator[tuple[str, dict], None, None]:
    """Yield only persisted stages from a new n8n-created document case.

    A prior case for the same filename is deliberately ignored.  This avoids
    showing stale results as progress for a newly requested analysis.
    """
    # Validate before spawning a thread, so configuration mistakes are
    # reported immediately and no half-configured browser request is started.
    _require_configuration()
    previous = case_store.get_latest_case(filename, workspace_id)
    previous_case_id = previous.get("case_id") if previous else None

    run = _WebhookRun(done=threading.Event())
    thread = threading.Thread(
        target=_run_webhook,
        args=(run, filename, workspace_id, job['job_id']) if job else (run,filename,workspace_id),
        name="n8n-document-orchestrator",
        daemon=True,
    )
    if dispatch:
        thread.start()

    deadline = time.monotonic() + N8N_ORCHESTRATOR_TIMEOUT_SECONDS
    if job:
        deadline = min(deadline,time.monotonic()+max(0,(job['deadline']-datetime.now(timezone.utc)).total_seconds()))
    completion_deadline: float | None = None
    observed_case_id: str | None = job['job_id'] if job else None
    observed_stage: str | None = None

    while True:
        current = case_store.get_case(job['job_id'],workspace_id) if job else case_store.get_latest_case(filename, workspace_id)
        if current and (job or _new_case_for_request(current, previous_case_id)):
            current_case_id = str(current["case_id"])
            if observed_case_id is None:
                observed_case_id = current_case_id
            # A second, unrelated case must never be blended into this stream.
            if current_case_id == observed_case_id:
                case_stage = str(current.get("stage", ""))
                if case_stage != observed_stage:
                    observed_stage = case_stage
                    frontend_stage = FRONTEND_STAGE_BY_CASE_STAGE.get(case_stage)
                    if frontend_stage:
                        yield frontend_stage, current

                if case_stage == "finalized" and (run.done.is_set() or not dispatch):
                    if run.error:
                        raise _workflow_error(run)
                    if job:
                        analysis_jobs.ledger().finish(workspace_id,job['job_id'],'complete')
                    yield "finalized", current
                    return

        if run.done.is_set():
            if run.error:
                raise _workflow_error(run)
            # A webhook configured with a last-node response should have made
            # the final case visible by now.  Keep a short grace period for
            # SQLite visibility, then fail closed instead of inventing stages.
            if completion_deadline is None:
                completion_deadline = time.monotonic() + N8N_COMPLETION_GRACE_SECONDS
            elif time.monotonic() >= completion_deadline:
                if job:
                    analysis_jobs.ledger().finish(workspace_id,job['job_id'],'uncertain')
                raise N8nOrchestratorError(
                    "n8n finished without finalising a new document case. Check the Agent Orchestrator execution.",
                    uncertain=True,
                )

        if time.monotonic() >= deadline:
            if job:
                analysis_jobs.ledger().finish(workspace_id,job['job_id'],'uncertain')
            raise N8nOrchestratorError("The n8n document workflow timed out before finalising the case.", uncertain=True)
        time.sleep(N8N_ORCHESTRATOR_POLL_INTERVAL_SECONDS)


def stream_durable_case(filename, workspace_id):
    _require_configuration()
    from services.analysis_dispatcher import require_dispatcher
    dispatcher = require_dispatcher()
    jobs = analysis_jobs.ledger()
    job = jobs.admit(workspace_id,filename,seconds=N8N_ORCHESTRATOR_TIMEOUT_SECONDS)
    saved = case_store.get_case(job['job_id'],workspace_id)
    if saved and saved.get('stage')=='finalized':
        jobs.finish(workspace_id,job['job_id'],'complete')
        yield 'finalized',saved
        return
    if job['state'] in {'uncertain','complete'}:
        raise N8nOrchestratorError('The previous analysis outcome needs review. It will not be automatically repeated.',uncertain=True)
    if job['state'] in {'cancelled','cancel_requested'}:
        raise N8nOrchestratorError('This analysis was cancelled or cancellation is pending. Review background activity.',uncertain=job['state']=='cancel_requested')
    if job['state']=='failed':
        raise N8nOrchestratorError('The analysis could not start after three attempts. Check service configuration before retrying.')
    dispatcher.wake()
    observed=None
    heartbeat=time.monotonic()+1
    deadline=time.monotonic()+N8N_ORCHESTRATOR_TIMEOUT_SECONDS
    while True:
        job=jobs.reconcile(workspace_id,job['job_id'])
        if not job:raise N8nOrchestratorError('This document analysis is no longer available.')
        current=case_store.get_case(job['job_id'],workspace_id)
        if job['state']=='complete' and current and current.get('stage')=='finalized':
            yield 'finalized',current;return
        if current and current.get('stage')!=observed:
            observed=current.get('stage')
            mapped=FRONTEND_STAGE_BY_CASE_STAGE.get(observed)
            if mapped:yield mapped,current
        if job['state'] in {'failed','cancelled','cancel_requested'}:
            raise N8nOrchestratorError('The analysis stopped. Review its background activity.',uncertain=job['state']=='cancel_requested')
        if job['state']=='uncertain':
            raise N8nOrchestratorError('Check saved progress and background activity. This analysis will not be resent.',uncertain=True)
        if time.monotonic()>=deadline:
            # Leaving an observer never cancels accepted/dispatching durable work.
            raise N8nOrchestratorError('The analysis continues in background activity. Check its saved progress.',uncertain=True)
        if time.monotonic()>=heartbeat:
            heartbeat=time.monotonic()+1
            yield 'heartbeat',{}
        time.sleep(N8N_ORCHESTRATOR_POLL_INTERVAL_SECONDS)
