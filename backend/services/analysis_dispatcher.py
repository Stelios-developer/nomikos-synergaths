"""Bounded durable queue runner. Unknown delivery is observed, never resent."""

from datetime import datetime, timezone
import os
import queue
import threading
import time
import uuid

import psycopg
from psycopg.rows import dict_row
from services.analysis_jobs import JobLedger, pipeline_version


class DispatcherUnavailable(RuntimeError):
    pass


class DispatchClient:
    def __init__(self, dsn):
        from services.runtime import is_production

        if is_production():
            from psycopg.conninfo import conninfo_to_dict

            config = conninfo_to_dict(dsn)
            if config.get("sslmode") != "verify-full" or config.get("host") in {
                None,
                "localhost",
                "127.0.0.1",
                "::1",
            }:
                raise DispatcherUnavailable(
                    "Production queue storage requires a verified TLS connection to its reviewed database host."
                )
        self.dsn = dsn

    def call(self, query, parameters=()):
        with psycopg.connect(
            self.dsn,
            connect_timeout=3,
            options="-c statement_timeout=3000",
            row_factory=dict_row,
        ) as conn:
            return conn.execute(query, parameters).fetchall()

    def verify(self):
        row = self.call(
            "SELECT r.rolname,r.rolsuper,r.rolbypassrls,r.rolcreatedb,r.rolcreaterole,has_table_privilege(current_user,'dmc.document_chunks','SELECT') AS data_access,has_table_privilege(current_user,'dmc.analysis_jobs','SELECT') AS job_access,has_function_privilege(current_user,'dmc.dispatch_claim(text,text)','EXECUTE') AS claim_access FROM pg_roles r WHERE r.rolname=current_user"
        )[0]
        if (
            row["rolname"] != "dmc_dispatcher"
            or any(
                row[k]
                for k in (
                    "rolsuper",
                    "rolbypassrls",
                    "rolcreatedb",
                    "rolcreaterole",
                    "data_access",
                    "job_access",
                )
            )
            or not row["claim_access"]
        ):
            raise DispatcherUnavailable(
                "Dispatcher database privileges are not restricted safely."
            )
        members = self.call(
            "SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=current_user)"
        )
        if members:
            raise DispatcherUnavailable(
                "The dispatcher must not inherit or assume another database role."
            )
        for signature in [
            "dmc.dispatch_observe()",
            "dmc.dispatch_heartbeat(text,text,text)",
        ]:
            if not self.call(
                "SELECT has_function_privilege(current_user,%s,'EXECUTE') AS allowed",
                (signature,),
            )[0]["allowed"]:
                raise DispatcherUnavailable(
                    "Dispatcher function grants are incomplete."
                )

    def claim(self, worker):
        rows = self.call(
            "SELECT * FROM dmc.dispatch_claim(%s,%s)", (worker, pipeline_version())
        )
        return rows[0] if rows else None

    def heartbeat(self, job, worker):
        self.call(
            "SELECT dmc.dispatch_heartbeat(%s,%s,%s)",
            (job["workspace_id"], job["job_id"], worker),
        )

    def observe(self):
        return self.call("SELECT * FROM dmc.dispatch_observe()")


class AnalysisDispatcher:
    def __init__(self, client, jobs, *, transport=None, interval=1):
        self.client, self.jobs = client, jobs
        self.worker = uuid.uuid4().hex
        self.interval = interval
        self.transport = transport
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.pending = queue.Queue(maxsize=2)
        self.active = {}
        self.lock = threading.Lock()
        self.threads = []
        self.last_healthy = 0.0
        self.last_error_log = 0.0

    def start(self):
        self.client.verify()
        self.last_healthy = time.monotonic()
        for target, name in [
            (self._run, "analysis-dispatch-1"),
            (self._run, "analysis-dispatch-2"),
            (self._coordinate, "analysis-coordinator"),
        ]:
            thread = threading.Thread(target=target, name=name, daemon=True)
            self.threads.append(thread)
            thread.start()

    def wake(self):
        self.wake_event.set()

    @property
    def healthy(self):
        return (
            bool(self.threads)
            and not self.stop_event.is_set()
            and all(t.is_alive() for t in self.threads)
            and time.monotonic() - self.last_healthy < 15
        )

    def stop(self):
        self.stop_event.set()
        self.wake_event.set()
        for thread in self.threads:
            if thread.ident is not None:
                thread.join(timeout=3)
        while True:
            try:
                job = self.pending.get_nowait()
            except queue.Empty:
                break
            try:
                self.jobs.finish(job["workspace_id"], job["job_id"], "failed")
            finally:
                self.pending.task_done()

    def _coordinate(self):
        while not self.stop_event.is_set():
            try:
                for job in self.client.observe():
                    try:
                        self.jobs.reconcile(job["workspace_id"], job["job_id"])
                    except Exception:
                        continue
                with self.lock:
                    active = list(self.active.values())
                    available = 2 - len(active) - self.pending.qsize()
                for job in active:
                    self.client.heartbeat(job, self.worker)
                for _ in range(max(available, 0)):
                    if self.stop_event.is_set():
                        break
                    job = self.client.claim(self.worker)
                    if not job:
                        break
                    if self.stop_event.is_set():
                        self.jobs.finish(job["workspace_id"], job["job_id"], "failed")
                        break
                    self.pending.put_nowait(job)
                self.last_healthy = time.monotonic()
            except Exception as exc:
                # No document/credential exception messages leave this thread.
                if time.monotonic() - self.last_error_log >= 30:
                    from services.observability import logger

                    logger.warning(
                        "analysis_dispatch_unavailable",
                        extra={"context": {"error_type": type(exc).__name__}},
                    )
                    self.last_error_log = time.monotonic()
            self.wake_event.wait(self.interval)
            self.wake_event.clear()

    def _run(self):
        while not self.stop_event.is_set():
            try:
                job = self.pending.get(timeout=0.2)
            except queue.Empty:
                continue
            with self.lock:
                self.active[job["job_id"]] = job
            try:
                from services.n8n_orchestrator import (
                    trigger_case_workflow,
                    N8nOrchestratorError,
                )

                current = self.jobs.reconcile(job["workspace_id"], job["job_id"])
                if not current or current["state"] not in {"dispatching", "uncertain"}:
                    continue
                if self.stop_event.is_set():
                    self.jobs.finish(job["workspace_id"], job["job_id"], "failed")
                    continue
                try:
                    self.jobs.validate_callback(
                        job["workspace_id"], job["job_id"], job["filename"]
                    )
                except Exception:
                    self.jobs.finish(job["workspace_id"], job["job_id"], "failed")
                    continue
                transport = self.transport or trigger_case_workflow
                seconds = max(
                    0.01, (job["deadline"] - datetime.now(timezone.utc)).total_seconds()
                )
                transport(
                    job["filename"],
                    job["workspace_id"],
                    job["job_id"],
                    cancel_event=self.stop_event,
                    timeout_seconds=seconds,
                )
                self.jobs.reconcile(job["workspace_id"], job["job_id"])
                # A completed HTTP response without a final artifact stays unknown.
                current = self.jobs.get(job["workspace_id"], job["job_id"])
                if current and current["state"] in {"dispatching", "uncertain"}:
                    self.jobs.finish(job["workspace_id"], job["job_id"], "uncertain")
            except Exception as exc:
                try:
                    from services.n8n_orchestrator import N8nOrchestratorError

                    state = (
                        "failed"
                        if isinstance(exc, N8nOrchestratorError) and not exc.uncertain
                        else "uncertain"
                    )
                    self.jobs.finish(job["workspace_id"], job["job_id"], state)
                    self.jobs.reconcile(job["workspace_id"], job["job_id"])
                except Exception:
                    pass
            finally:
                with self.lock:
                    self.active.pop(job["job_id"], None)
                self.pending.task_done()


_dispatcher = None


def require_dispatcher():
    if _dispatcher is None or not _dispatcher.healthy:
        raise DispatcherUnavailable(
            "Background analysis is unavailable. No new analysis was dispatched."
        )
    return _dispatcher


def start_dispatcher():
    global _dispatcher
    if os.getenv("ANALYSIS_DISPATCH_ENABLED", "false").lower() != "true":
        return None
    if _dispatcher is not None:
        raise DispatcherUnavailable("The background dispatcher is already running.")
    from services.n8n_orchestrator import _require_configuration

    _require_configuration()
    from db.vector_store import get_collection

    dsn = os.getenv("ANALYSIS_DISPATCH_DATABASE_URL", "")
    if not dsn:
        raise DispatcherUnavailable("Configure the dedicated dispatcher database role.")
    candidate = AnalysisDispatcher(DispatchClient(dsn), JobLedger(get_collection()))
    try:
        candidate.start()
    except Exception:
        candidate.stop()
        raise
    _dispatcher = candidate
    return candidate


def stop_dispatcher():
    global _dispatcher
    if _dispatcher is not None:
        _dispatcher.stop()
    _dispatcher = None
