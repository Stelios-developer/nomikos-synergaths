"""Durable admission and single-dispatch coordination for document analysis.

Unknown delivery stays uncertain. A reconnect observes the same case instead
of replaying the webhook. Accepted, not-yet-dispatched work may be reclaimed.
"""

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import uuid
from functools import lru_cache
from contextlib import contextmanager
from datetime import timedelta

from db.vector_store import get_collection
from services.analysis_context import commit_guard
from services.workspace_lock import scoped_operation, workspace_access

JOB_COLUMNS = "job_id,filename,generation,state,attempts,deadline,pipeline_sha,worker_id,heartbeat_at,updated_at,created_at,reason,budget_seconds"


class AnalysisJobConflict(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _pipeline_sources():
    """Freeze the loaded release; disk edits take effect after process restart."""
    sources = []
    for name in (
        "document_case.py",
        "auditor.py",
        "llm.py",
        "case_stages.py",
        "analysis_context.py",
    ):
        sources.append(Path(__file__).with_name(name).read_bytes())
    return tuple(sources)


def pipeline_version():
    digest = hashlib.sha256(os.getenv("LLM_PROVIDER", "openai").encode())
    for source in _pipeline_sources():
        digest.update(source)
    return digest.hexdigest()


class JobLedger:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _row(row):
        return dict(zip(JOB_COLUMNS.split(","), row)) if row else None

    def get(self, workspace_id, job_id):
        with self.store.transaction(workspace_id) as conn:
            return self._row(
                conn.execute(
                    f"SELECT {JOB_COLUMNS} FROM dmc.analysis_jobs WHERE workspace_id=%s AND job_id=%s",
                    (workspace_id, job_id),
                ).fetchone()
            )

    def admit(self, workspace_id, filename, *, seconds=900):
        if isinstance(seconds, bool) or not 0 < seconds <= 900:
            raise ValueError("Invalid analysis budget")
        generation = self.store.generation(workspace_id, filename)
        pipeline = pipeline_version()
        fingerprint = hashlib.sha256((generation + pipeline).encode()).hexdigest()
        with self.store.transaction(workspace_id) as conn:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,7901))",
                (workspace_id,),
            )
            previous = conn.execute(
                f"SELECT {JOB_COLUMNS} FROM dmc.analysis_jobs WHERE workspace_id=%s AND fingerprint=%s AND state<>'cancelled' FOR UPDATE",
                (workspace_id, fingerprint),
            ).fetchone()
            if previous:
                job = self._row(previous)
                if (
                    job["state"] == "failed"
                    and job["attempts"] < 3
                    or job["state"] == "accepted"
                    and job["deadline"] <= datetime.now(timezone.utc)
                ):
                    busy = conn.execute(
                        "SELECT count(*) FROM dmc.analysis_jobs WHERE workspace_id=%s AND job_id<>%s AND state IN ('accepted','dispatching','uncertain','cancel_requested')",
                        (workspace_id, job["job_id"]),
                    ).fetchone()[0]
                    if busy >= 2:
                        raise AnalysisJobConflict(
                            "Two analyses already need attention in this workspace."
                        )
                    job["deadline"] = conn.execute(
                        "UPDATE dmc.analysis_jobs SET state='accepted',deadline=now()+make_interval(secs=>%s),updated_at=now() WHERE workspace_id=%s AND job_id=%s RETURNING deadline",
                        (seconds, workspace_id, job["job_id"]),
                    ).fetchone()[0]
                    job["state"] = "accepted"
                return job
            busy = conn.execute(
                "SELECT count(*) FROM dmc.analysis_jobs WHERE workspace_id=%s AND state IN ('accepted','dispatching','uncertain','cancel_requested')",
                (workspace_id,),
            ).fetchone()[0]
            if busy >= 2:
                raise AnalysisJobConflict(
                    "Two analyses already need attention in this workspace. Review them before starting another."
                )
            other = conn.execute(
                "SELECT 1 FROM dmc.analysis_jobs WHERE workspace_id=%s AND filename=%s AND state IN ('accepted','dispatching','uncertain','cancel_requested')",
                (workspace_id, filename),
            ).fetchone()
            if other:
                raise AnalysisJobConflict(
                    "An earlier analysis for this document still needs attention."
                )
            job_id = uuid.uuid4().hex
            result = conn.execute(
                f"INSERT INTO dmc.analysis_jobs(workspace_id,job_id,filename,generation,fingerprint,state,deadline,pipeline_sha,budget_seconds) VALUES (%s,%s,%s,%s,%s,'accepted',now()+make_interval(secs=>%s),%s,%s) RETURNING {JOB_COLUMNS}",
                (
                    workspace_id,
                    job_id,
                    filename,
                    generation,
                    fingerprint,
                    seconds,
                    pipeline,
                    seconds,
                ),
            ).fetchone()
            self._event(conn, workspace_id, job_id, "accepted", "user")
            return self._row(result)

    def claim(self, workspace_id, job_id):
        with self.store.transaction(workspace_id) as conn:
            result = conn.execute(
                "UPDATE dmc.analysis_jobs SET state='dispatching',attempts=attempts+1,updated_at=now() WHERE workspace_id=%s AND job_id=%s AND state='accepted' AND attempts<3 AND deadline>now() RETURNING job_id",
                (workspace_id, job_id),
            ).fetchone()
            return bool(result)

    def finish(self, workspace_id, job_id, state):
        if state not in {"complete", "failed", "uncertain"}:
            raise ValueError("Invalid terminal analysis state")
        with self.store.transaction(workspace_id) as conn:
            changed = conn.execute(
                "UPDATE dmc.analysis_jobs SET state=%s,updated_at=now() WHERE workspace_id=%s AND job_id=%s AND state IN ('dispatching','uncertain') AND state<>%s RETURNING job_id",
                (state, workspace_id, job_id, state),
            ).fetchone()
            if changed:
                self._event(conn, workspace_id, job_id, state, "dispatcher")

    def validate_callback(self, workspace_id, job_id, filename):
        job = self.get(workspace_id, job_id)
        if (
            not job
            or job["filename"] != filename
            or job["state"] not in {"dispatching", "uncertain", "complete"}
        ):
            raise AnalysisJobConflict(
                "This workflow does not match an admitted analysis."
            )
        if job["state"] != "complete" and datetime.now(timezone.utc) >= job["deadline"]:
            raise AnalysisJobConflict(
                "The analysis deadline has expired; the workflow must stop."
            )
        if job["pipeline_sha"] != pipeline_version():
            raise AnalysisJobConflict(
                "The analysis belongs to another pipeline version."
            )
        if self.store.generation(workspace_id, filename) != job["generation"]:
            raise AnalysisJobConflict(
                "The document changed after this analysis was admitted."
            )
        return job

    @staticmethod
    def _event(conn, workspace_id, job_id, event, actor):
        conn.execute(
            "INSERT INTO dmc.analysis_job_events(workspace_id,job_id,event,actor) VALUES (%s,%s,%s,%s)",
            (workspace_id, job_id, event, actor),
        )

    def list(self, workspace_id, limit=50):
        with self.store.transaction(workspace_id) as conn:
            rows = conn.execute(
                f"SELECT {JOB_COLUMNS} FROM dmc.analysis_jobs WHERE workspace_id=%s ORDER BY created_at DESC,job_id LIMIT %s",
                (workspace_id, min(max(limit, 1), 100)),
            ).fetchall()
        return [self._row(row) for row in rows]

    def events(self, workspace_id, job_id):
        with self.store.transaction(workspace_id) as conn:
            return [
                dict(zip(("event", "actor", "occurred_at"), row))
                for row in conn.execute(
                    "SELECT event,actor,occurred_at FROM dmc.analysis_job_events WHERE workspace_id=%s AND job_id=%s ORDER BY event_id DESC LIMIT 100",
                    (workspace_id, job_id),
                ).fetchall()
            ]

    def saved_result(self, workspace_id, job_id):
        from services import case_store
        from services.workspace_lock import workspace_access

        with workspace_access(workspace_id):
            job = self.get(workspace_id, job_id)
            if not job:
                return None
            saved = case_store.get_case(job_id, workspace_id)
            if (
                not saved
                or saved.get("document", {}).get("filename") != job["filename"]
            ):
                return None
            try:
                unchanged = (
                    self.store.generation(workspace_id, job["filename"])
                    == job["generation"]
                )
            except ValueError:
                return None
            return saved if unchanged else None

    @scoped_operation
    def reconcile(self, workspace_id, job_id):
        from services import case_store

        with self.store.transaction(workspace_id) as conn:
            row = conn.execute(
                f"SELECT {JOB_COLUMNS} FROM dmc.analysis_jobs WHERE workspace_id=%s AND job_id=%s FOR UPDATE",
                (workspace_id, job_id),
            ).fetchone()
            job = self._row(row)
            if not job or job["state"] in {"complete", "cancelled", "failed"}:
                return job
            saved = case_store.get_case(job_id, workspace_id)
            if saved:
                from services.case_stages import CASE_STAGES, CASE_OPERATIONS

                current_stage = saved.get("stage")
                if current_stage in CASE_STAGES:
                    completed = [
                        key
                        for key, value in CASE_OPERATIONS.items()
                        if CASE_STAGES.index(value) <= CASE_STAGES.index(current_stage)
                    ]
                    conn.execute(
                        "UPDATE dmc.analysis_stages SET state='complete',finished_at=now() WHERE workspace_id=%s AND job_id=%s AND stage=ANY(%s) AND state IN ('running','uncertain')",
                        (workspace_id, job_id, completed),
                    )
            now = datetime.now(timezone.utc)
            state, reason = job["state"], job["reason"]
            if saved and saved.get("stage") == "finalized":
                state, reason = "complete", "saved_final_case"
            elif (
                job["state"] == "accepted" and job["pipeline_sha"] != pipeline_version()
            ):
                state, reason = "failed", "pipeline_changed_before_dispatch"
            elif job["state"] == "cancel_requested" and now >= job["deadline"]:
                state, reason = "cancelled", "cancelled_after_deadline"
            elif job["state"] == "dispatching" and (
                now >= job["deadline"]
                or job["heartbeat_at"]
                and now - job["heartbeat_at"] > timedelta(seconds=30)
            ):
                state, reason = (
                    "uncertain",
                    "deadline_expired" if now >= job["deadline"] else "worker_lost",
                )
            if state != job["state"]:
                conn.execute(
                    "UPDATE dmc.analysis_jobs SET state=%s,reason=%s,updated_at=now() WHERE workspace_id=%s AND job_id=%s",
                    (state, reason, workspace_id, job_id),
                )
                self._event(conn, workspace_id, job_id, reason, "reconciler")
            job.update(state=state, reason=reason)
            return job

    @scoped_operation
    def resolve(self, workspace_id, job_id, action):
        if action not in {"cancel", "close"}:
            raise ValueError("Invalid job action")
        self.reconcile(workspace_id, job_id)
        with self.store.transaction(workspace_id) as conn:
            job = self._row(
                conn.execute(
                    f"SELECT {JOB_COLUMNS} FROM dmc.analysis_jobs WHERE workspace_id=%s AND job_id=%s FOR UPDATE",
                    (workspace_id, job_id),
                ).fetchone()
            )
            if not job:
                raise KeyError("Analysis not found in your workspace.")
            if job["state"] in {"complete", "cancelled"}:
                return job
            if action == "cancel" and job["state"] == "cancel_requested":
                return job
            now = datetime.now(timezone.utc)
            if action == "cancel":
                state = (
                    "cancelled"
                    if job["state"] in {"accepted", "failed"}
                    else "cancel_requested"
                )
            elif (
                job["state"] == "failed"
                or job["state"] in {"uncertain", "cancel_requested"}
                and now >= job["deadline"]
            ):
                state = "cancelled"
            else:
                raise AnalysisJobConflict(
                    "Check saved progress first. This analysis cannot be closed before its deadline."
                )
            conn.execute(
                "UPDATE dmc.analysis_jobs SET state=%s,reason=%s,updated_at=now() WHERE workspace_id=%s AND job_id=%s",
                (state, "user_" + action, workspace_id, job_id),
            )
            self._event(conn, workspace_id, job_id, "user_" + action, "user")
            job.update(state=state, reason="user_" + action)
            return job

    @contextmanager
    def stage_scope(self, workspace_id, job_id, filename, stage):
        self.validate_callback(workspace_id, job_id, filename)
        token = uuid.uuid4().hex
        execute = True
        with (
            workspace_access(workspace_id),
            self.store.transaction(workspace_id) as conn,
        ):
            current = conn.execute(
                "SELECT state,deadline FROM dmc.analysis_jobs WHERE workspace_id=%s AND job_id=%s FOR UPDATE",
                (workspace_id, job_id),
            ).fetchone()
            if (
                not current
                or current[0] not in {"dispatching", "uncertain", "complete"}
                or current[0] != "complete"
                and current[1] <= datetime.now(timezone.utc)
            ):
                raise AnalysisJobConflict("This analysis cannot start another stage.")
            if current[0] == "complete":
                execute = False
            else:
                row = conn.execute(
                    "INSERT INTO dmc.analysis_stages(workspace_id,job_id,stage,state,token) VALUES (%s,%s,%s,'running',%s) ON CONFLICT DO NOTHING RETURNING token",
                    (workspace_id, job_id, stage, token),
                ).fetchone()
                if not row:
                    previous = conn.execute(
                        "SELECT state FROM dmc.analysis_stages WHERE workspace_id=%s AND job_id=%s AND stage=%s",
                        (workspace_id, job_id, stage),
                    ).fetchone()
                    if previous and previous[0] == "complete":
                        execute = False
                    else:
                        raise AnalysisJobConflict(
                            "This analysis stage is already running or needs reconciliation. It will not be repeated."
                        )
        # Never hold a row transaction or filesystem lock across caller/provider work.
        if not execute:
            yield False
            return
        try:

            def validate_commit():
                from services.budget import remaining

                remaining()
                self.validate_callback(workspace_id, job_id, filename)

            with commit_guard(validate_commit):
                yield True
        except BaseException:
            with self.store.transaction(workspace_id) as conn:
                conn.execute(
                    "UPDATE dmc.analysis_stages SET state='uncertain',finished_at=now() WHERE workspace_id=%s AND job_id=%s AND stage=%s AND token=%s",
                    (workspace_id, job_id, stage, token),
                )
            self.finish(workspace_id, job_id, "uncertain")
            raise
        else:
            with self.store.transaction(workspace_id) as conn:
                conn.execute(
                    "UPDATE dmc.analysis_stages SET state='complete',finished_at=now() WHERE workspace_id=%s AND job_id=%s AND stage=%s AND token=%s",
                    (workspace_id, job_id, stage, token),
                )


def ledger():
    return JobLedger(get_collection())
