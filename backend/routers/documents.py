import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from db.vector_store import get_collection
from services import analysis_jobs, case_store, document_case, n8n_orchestrator
from services.pdf_storage import delete_pdf, pdf_path
from services.page_render import render_page_png
from services.security import RATE_LIMIT_INTELLIGENCE, limiter
from services.session_scope import get_session_id
from services.workspace_lock import scoped_operation

router = APIRouter()


def _case_error(exc: Exception) -> None:
    if isinstance(exc, analysis_jobs.AnalysisJobConflict):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, document_case.CaseStageError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, (ValueError, KeyError)):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    raise exc


def _sse(event_type: str, payload: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **payload})}\n\n"


def _run_case_stages(filename: str, session_id: str):
    """Yield the real persisted case after every workflow stage."""
    case = document_case.start_case(filename, session_id)
    yield "started", case

    case = document_case.run_document_dna(case["case_id"], session_id)
    yield "dna_complete", case

    case = document_case.run_facts_obligations(case["case_id"], session_id)
    yield "facts_complete", case

    case = document_case.run_risk_prioritisation(case["case_id"], session_id)
    yield "risks_complete", case

    case = document_case.run_draft_action_pack(case["case_id"], session_id)
    yield "brief_complete", case

    case = document_case.run_mandatory_audit(case["case_id"], session_id)
    yield "audit_complete", case

    case = document_case.finalize_case(case["case_id"], session_id)
    yield "finalized", case


def _stream_case_stages(filename: str, session_id: str):
    """Expose n8n-run, persisted case progress for the guided frontend flow."""
    try:
        for stage, case in n8n_orchestrator.stream_durable_case(filename, session_id):
            if stage=='heartbeat':
                yield ': keepalive\n\n'
            elif stage == "finalized":
                yield _sse("done", {"case": document_case.public_case(case)})
            else:
                yield _sse("stage", {"stage": stage})
    except Exception as exc:
        if isinstance(exc, (analysis_jobs.AnalysisJobConflict, document_case.CaseStageError, ValueError, KeyError, n8n_orchestrator.N8nOrchestratorError)):
            message = str(exc)
        else:
            message = "The document intelligence workflow could not complete."
        uncertain = bool(getattr(exc,'uncertain',False))
        if uncertain:
            message = 'The analysis may still be running. Check saved progress before starting again.'
        yield _sse("error", {"message": message, 'code':'ANALYSIS_UNCERTAIN' if uncertain else 'ANALYSIS_FAILED', 'uncertain':uncertain})


@router.get("/documents")
def list_documents(session_id: str = Depends(get_session_id)):
    """
    Derives the document list from chunk metadata already in PostgreSQL
    (no separate documents table) — groups by filename, reporting
    chunk_count, the extraction method, and first-seen upload date.
    Scoped to the requesting session_id (services/session_scope.py) so
    one visitor never sees another visitor's uploads.
    """
    collection = get_collection()
    all_rows = collection.get(workspace_id=session_id, include=["metadatas"])
    metadatas = all_rows["metadatas"]

    by_filename: dict[str, dict] = {}
    for m in metadatas:
        fname = m["filename"]
        if fname not in by_filename:
            by_filename[fname] = {
                "filename": fname,
                "chunk_count": 0,
                "method": m.get("method"),
                "upload_date": m.get("upload_date"),
            }
        by_filename[fname]["chunk_count"] += 1

    return list(by_filename.values())


@router.delete("/documents/{filename}")
@scoped_operation
def delete_document(filename: str, session_id: str = Depends(get_session_id)):
    """
    Only deletes chunks that belong to BOTH this filename AND the
    requesting session — a visitor can never delete another visitor's
    document. Returns 404 (same as "never existed") rather than 403 for
    a filename that exists under a different session, so this endpoint
    doesn't leak whether a given filename exists at all elsewhere.
    """
    collection = get_collection()
    owned = collection.get(workspace_id=session_id, filename=filename, include=[])
    stored_case = case_store.get_latest_case(filename, session_id)
    source_path = pdf_path(filename, session_id=session_id)
    if not owned["ids"] and stored_case is None and source_path is None:
        raise HTTPException(status_code=404, detail="Document not found in your session.")

    # Each step is scoped to this workspace. If one fails, return an error
    # rather than claiming deletion; a retry can clean up any remaining data.
    try:
        delete_pdf(filename, session_id=session_id)
        if owned["ids"]:
            collection.delete(workspace_id=session_id, filename=filename)
        case_store.delete_cases_for_document(filename, session_id)
        collection.forget_analysis_jobs(session_id, filename)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Document deletion did not complete. Please retry.") from exc
    return {"filename": filename, "deleted": True}


@router.get("/documents/{filename}/page")
@scoped_operation
def get_page_image(
    filename: str,
    page: int = Query(..., ge=1),
    snippet: str = Query(""),
    session_id: str = Depends(get_session_id),
):
    """
    Renders one page of the original PDF as a PNG, with `snippet` (the
    cited chunk's text) highlighted if it can be located on the page —
    lets the UI show a citation's exact source location instead of just
    the extracted text. Falls back to an unhighlighted page image if the
    snippet can't be matched (e.g. odd whitespace/hyphenation), and to a
    404 if the PDF itself was never stored, has since been deleted, or
    doesn't belong to the requesting session.
    """
    collection = get_collection()
    owned = collection.get(workspace_id=session_id, filename=filename, include=[])
    if not owned["ids"]:
        raise HTTPException(
            status_code=404,
            detail="Original PDF not found in storage (uploaded before this feature was added, deleted, or not in your session).",
        )

    path = pdf_path(filename, session_id=session_id)
    if path is None:
        raise HTTPException(
            status_code=404,
            detail="Original PDF not found in storage (uploaded before this feature was added, or deleted).",
        )

    try:
        png_bytes = render_page_png(path, page, snippet)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return Response(content=png_bytes, media_type="image/png")


@router.get("/documents/{filename}/intelligence")
@scoped_operation
def get_document_intelligence(filename: str, session_id: str = Depends(get_session_id)):
    """Returns the latest stored intelligence case for this document and visitor."""
    owned = get_collection().get(workspace_id=session_id, filename=filename, include=[])
    if not owned["ids"]:
        raise HTTPException(status_code=404, detail="Document not found in your workspace.")
    case = case_store.get_latest_case(filename, session_id)
    if case is None:
        raise HTTPException(status_code=404, detail="No intelligence case exists for this document yet.")
    return document_case.public_case(case)


@router.post("/documents/{filename}/intelligence/run")
@limiter.limit(RATE_LIMIT_INTELLIGENCE)
def run_document_intelligence(
    request: Request,
    filename: str,
    session_id: str = Depends(get_session_id),
):
    """Runs the evidence-first analysis and its mandatory quality gate."""
    try:
        case = None
        for _stage, current_case in n8n_orchestrator.stream_durable_case(filename, session_id):
            if _stage!='heartbeat':case = current_case
    except Exception as exc:
        _case_error(exc)
    if case is None:
        raise HTTPException(status_code=500, detail="The document intelligence workflow did not produce a case.")
    return document_case.public_case(case)


@router.post("/documents/{filename}/intelligence/stream")
@limiter.limit(RATE_LIMIT_INTELLIGENCE)
async def stream_document_intelligence(
    request: Request,
    filename: str,
    session_id: str = Depends(get_session_id),
):
    """Starts the visible n8n Agent Orchestrator and streams its real stages."""
    return StreamingResponse(
        _stream_case_stages(filename, session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
