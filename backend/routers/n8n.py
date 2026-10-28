"""Server-to-server endpoints used by n8n document workflows.

n8n supplies one stable workspace ID per customer/team in X-Workspace-ID.
That value is used as the RAG session scope, so documents and answers from
one workflow cannot mix with another workspace's evidence.
"""
from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field
from uuid import UUID

from services import analysis_jobs, case_store, document_case
from services.advisory_panel import run_panel_stream
from services.agent import run_agent
from services.document_publication import process_upload
from services.multihop import run_research_stream
from services.security import MAX_UPLOAD_SIZE_MB, require_n8n_webhook_api_key
from services.supervisor import run_supervisor_stream
from services.budget import operation_budget

router = APIRouter(prefix="/integrations/n8n", tags=["n8n"])

MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024


def get_workspace_id(x_workspace_id: str | None = Header(default=None)) -> str:
    """Returns the n8n-controlled tenant boundary for an integration call."""
    if not x_workspace_id or not x_workspace_id.strip():
        raise HTTPException(status_code=400, detail="X-Workspace-ID header is required.")
    return x_workspace_id.strip()


class AnalysisRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4_000)
    document_filter: str | None = None


class CaseStartRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    analysis_job_id: UUID | None = None


class CaseRequest(BaseModel):
    case_id: str = Field(min_length=1, max_length=128)


def _case_envelope(case: dict, artifact: str | None = None) -> dict:
    """Small, workflow-friendly stage result; the full file stays server-side."""
    result = {
        "case_id": case["case_id"],
        "workspace_id": case["workspace_id"],
        "filename": case["document"]["filename"],
        "status": case["status"],
        "stage": case["stage"],
        "warnings": case.get("warnings", []),
    }
    if artifact:
        result[artifact] = case.get(artifact)
    return result


def _raise_case_http_error(exc: Exception) -> None:
    if isinstance(exc, analysis_jobs.AnalysisJobConflict):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, document_case.CaseStageError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, (ValueError, KeyError)):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    raise exc


def _execute_stage(case_id, workspace_id, operation):
    case = case_store.get_case(case_id, workspace_id)
    job = None
    if case and case.get('analysis_job_id'):
        job = analysis_jobs.ledger().validate_callback(workspace_id,case['analysis_job_id'],case['document']['filename'])
    with operation_budget(180, expires_at=job['deadline'] if job else None):
        if job:
            with analysis_jobs.ledger().stage_scope(workspace_id,case['analysis_job_id'],case['document']['filename'],operation.__name__) as execute:
                return operation(case_id,workspace_id) if execute else case_store.get_case(case_id,workspace_id)
        return operation(case_id, workspace_id)


@router.post("/documents")
async def ingest_document(
    file: UploadFile = File(...),
    workspace_id: str = Depends(get_workspace_id),
    _: None = Depends(require_n8n_webhook_api_key),
):
    """Ingests a PDF delivered by an n8n source workflow."""
    result = await process_upload(file, workspace_id, MAX_UPLOAD_SIZE_BYTES)
    return {"workspace_id": workspace_id, **result}


@router.post("/analyze")
def analyze_documents(
    req: AnalysisRequest,
    workspace_id: str = Depends(get_workspace_id),
    _: None = Depends(require_n8n_webhook_api_key),
):
    """Returns a workflow-ready, source-grounded answer as regular JSON."""
    state = run_agent(
        req.question,
        document_filter=req.document_filter,
        session_id=workspace_id,
    )
    citations = [
        {"filename": chunk["filename"], "page": chunk["page_number"], "text": chunk["text"]}
        for chunk in state["chunks"]
    ]
    return {
        "workspace_id": workspace_id,
        "question": req.question,
        "answer": state["answer"],
        "citations": citations,
        "retrieval_query": state["question"],
        "rephrase_attempts": state["iteration"],
    }


@router.post("/agents/supervisor")
def run_supervisor_agent(
    req: AnalysisRequest,
    workspace_id: str = Depends(get_workspace_id),
    _: None = Depends(require_n8n_webhook_api_key),
):
    """Run the real document supervisor and return its completed trace as JSON.

    The browser endpoint streams these same events over SSE. n8n needs a
    regular JSON response, so this adapter consumes the stream without
    changing the underlying routing or RAG behavior.
    """
    route_trace: list[dict] = []
    answer_parts: list[str] = []
    citations: list[dict] = []
    summary = ""

    for kind, payload in run_supervisor_stream(
        req.question,
        req.document_filter,
        None,
        workspace_id,
    ):
        if kind == "route":
            route_trace.append(payload)
        elif kind == "rag_token":
            answer_parts.append(payload)
        elif kind == "rag_done":
            citations = payload.get("citations", [])
        elif kind == "done":
            summary = payload.get("summary", "")

    answer = "".join(answer_parts)
    return {
        "workspace_id": workspace_id,
        "agent": "supervisor",
        "question": req.question,
        "route_trace": route_trace,
        "answer": answer,
        "summary": summary or answer,
        "citations": citations,
    }


@router.post("/agents/research")
def run_research_agent(
    req: AnalysisRequest,
    workspace_id: str = Depends(get_workspace_id),
    _: None = Depends(require_n8n_webhook_api_key),
):
    """Run the real multi-hop researcher and return its evidence trace as JSON."""
    subquestions: list[str] = []
    retrieval_trace: list[dict] = []
    answer_parts: list[str] = []
    citations: list[dict] = []

    for kind, payload in run_research_stream(
        req.question,
        req.document_filter,
        None,
        workspace_id,
    ):
        if kind == "subquestions":
            subquestions = payload
        elif kind == "subretrieval":
            retrieval_trace.append(payload)
        elif kind == "token":
            answer_parts.append(payload)
        elif kind == "done":
            citations = payload.get("citations", [])

    return {
        "workspace_id": workspace_id,
        "agent": "research",
        "question": req.question,
        "subquestions": subquestions,
        "retrieval_trace": retrieval_trace,
        "answer": "".join(answer_parts),
        "citations": citations,
    }


@router.post("/agents/expert-review")
def run_expert_review_agent(
    req: AnalysisRequest,
    workspace_id: str = Depends(get_workspace_id),
    _: None = Depends(require_n8n_webhook_api_key),
):
    """Run the real three-advisor Expert Review and moderator as JSON."""
    citations: list[dict] = []
    advisor_opinions: list[dict] = []
    moderator_summary = ""

    for kind, payload in run_panel_stream(req.question, req.document_filter, workspace_id):
        if kind == "citations":
            citations = payload
        elif kind == "advisor":
            advisor_opinions.append(payload)
        elif kind == "done":
            moderator_summary = payload.get("moderator_summary", "")

    return {
        "workspace_id": workspace_id,
        "agent": "expert_review",
        "question": req.question,
        "citations": citations,
        "advisor_opinions": advisor_opinions,
        "moderator_summary": moderator_summary,
    }


@router.post("/cases/start")
def start_document_case(
    req: CaseStartRequest,
    workspace_id: str = Depends(get_workspace_id),
    _: None = Depends(require_n8n_webhook_api_key),
):
    """Creates a workspace-scoped case file from exactly one indexed PDF."""
    try:
        job_id = req.analysis_job_id.hex if req.analysis_job_id else None
        if job_id:
            jobs=analysis_jobs.ledger()
            with jobs.stage_scope(workspace_id,job_id,req.filename.strip(),'start') as execute:
                case=(document_case.start_case(req.filename.strip(),workspace_id,case_id=job_id)
                      if execute else case_store.get_case(job_id,workspace_id))
        else:
            case=document_case.start_case(req.filename.strip(), workspace_id)
    except Exception as exc:
        _raise_case_http_error(exc)
    return _case_envelope(case, "document") | {"citations": case["citations"]}


@router.post("/cases/document-dna")
def document_dna(
    req: CaseRequest,
    workspace_id: str = Depends(get_workspace_id),
    _: None = Depends(require_n8n_webhook_api_key),
):
    try:
        case = _execute_stage(req.case_id, workspace_id, document_case.run_document_dna)
    except Exception as exc:
        _raise_case_http_error(exc)
    return _case_envelope(case, "document_profile")


@router.post("/cases/facts")
def facts_obligations_and_deadlines(
    req: CaseRequest,
    workspace_id: str = Depends(get_workspace_id),
    _: None = Depends(require_n8n_webhook_api_key),
):
    try:
        case = _execute_stage(req.case_id, workspace_id, document_case.run_facts_obligations)
    except Exception as exc:
        _raise_case_http_error(exc)
    response = _case_envelope(case)
    response.update({
        "facts": case["facts"],
        "obligations": case["obligations"],
        "deadlines": case["deadlines"],
        "open_questions": case["open_questions"],
    })
    return response


@router.post("/cases/risks")
def risk_prioritisation(
    req: CaseRequest,
    workspace_id: str = Depends(get_workspace_id),
    _: None = Depends(require_n8n_webhook_api_key),
):
    try:
        case = _execute_stage(req.case_id, workspace_id, document_case.run_risk_prioritisation)
    except Exception as exc:
        _raise_case_http_error(exc)
    response = _case_envelope(case)
    response.update({"overall_risk": case.get("overall_risk", "low"), "risks": case["risks"]})
    return response


@router.post("/cases/draft-action-pack")
def draft_decision_brief_and_action_pack(
    req: CaseRequest,
    workspace_id: str = Depends(get_workspace_id),
    _: None = Depends(require_n8n_webhook_api_key),
):
    try:
        case = _execute_stage(req.case_id, workspace_id, document_case.run_draft_action_pack)
    except Exception as exc:
        _raise_case_http_error(exc)
    return _case_envelope(case, "draft_action_pack")


@router.post("/cases/audit")
def mandatory_hallucination_audit(
    req: CaseRequest,
    workspace_id: str = Depends(get_workspace_id),
    _: None = Depends(require_n8n_webhook_api_key),
):
    try:
        case = _execute_stage(req.case_id, workspace_id, document_case.run_mandatory_audit)
    except Exception as exc:
        _raise_case_http_error(exc)
    return _case_envelope(case, "audit")


@router.post("/cases/finalize")
def finalize_action_pack(
    req: CaseRequest,
    workspace_id: str = Depends(get_workspace_id),
    _: None = Depends(require_n8n_webhook_api_key),
):
    try:
        case = _execute_stage(req.case_id, workspace_id, document_case.finalize_case)
    except Exception as exc:
        _raise_case_http_error(exc)
    return _case_envelope(case, "final_action_pack")


@router.get("/cases/{case_id}")
def get_document_case(
    case_id: str,
    workspace_id: str = Depends(get_workspace_id),
    _: None = Depends(require_n8n_webhook_api_key),
):
    try:
        case = document_case.get_case(case_id, workspace_id)
    except Exception as exc:
        _raise_case_http_error(exc)
    return document_case.public_case(case)
