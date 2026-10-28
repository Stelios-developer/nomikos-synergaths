"""Authenticated job controls and exact, generation-checked saved results."""

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from services.analysis_jobs import ledger, AnalysisJobConflict
from services.session_scope import get_session_id
from services.document_case import public_case

router = APIRouter()


class JobAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["cancel", "close"]


def public_job(job, session_id):
    result = {
        key: job[key]
        for key in (
            "job_id",
            "filename",
            "state",
            "attempts",
            "deadline",
            "updated_at",
            "created_at",
            "reason",
        )
    }
    expired = datetime.now(timezone.utc) >= job["deadline"]
    result["can_cancel"] = job["state"] in {
        "accepted",
        "dispatching",
        "uncertain",
        "failed",
    }
    result["can_close"] = (
        job["state"] == "failed"
        or job["state"] in {"uncertain", "cancel_requested"}
        and expired
    )
    result["result_available"] = (
        ledger().saved_result(session_id, job["job_id"]) is not None
    )
    return result


@router.get("/analysis/jobs")
def list_jobs(session_id: str = Depends(get_session_id)):
    jobs = ledger()
    result = []
    for job in jobs.list(session_id):
        current = jobs.reconcile(session_id, job["job_id"])
        if current:
            result.append(public_job(current, session_id))
    return result


@router.get("/analysis/jobs/{job_id}")
def get_job(job_id: UUID, session_id: str = Depends(get_session_id)):
    jobs = ledger()
    job = jobs.reconcile(session_id, job_id.hex)
    if not job:
        raise HTTPException(404, "Analysis not found in your workspace.")
    return {
        **public_job(job, session_id),
        "events": jobs.events(session_id, job_id.hex),
    }


@router.get("/analysis/jobs/{job_id}/result")
def get_result(job_id: UUID, session_id: str = Depends(get_session_id)):
    saved = ledger().saved_result(session_id, job_id.hex)
    if not saved:
        raise HTTPException(404, "No saved result is available for this analysis.")
    return public_case(saved)


@router.post("/analysis/jobs/{job_id}/resolve")
def resolve_job(
    job_id: UUID, action: JobAction, session_id: str = Depends(get_session_id)
):
    try:
        return public_job(
            ledger().resolve(session_id, job_id.hex, action.action), session_id
        )
    except KeyError as exc:
        raise HTTPException(404, "Analysis not found in your workspace.") from exc
    except AnalysisJobConflict as exc:
        raise HTTPException(409, str(exc)) from exc
