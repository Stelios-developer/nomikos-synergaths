from fastapi import APIRouter, Request
from pydantic import BaseModel

from services.auditor import audit_answer
from services.security import limiter, RATE_LIMIT_AUDIT

router = APIRouter()


class AuditCitation(BaseModel):
    filename: str
    page: int
    text: str


class AuditRequest(BaseModel):
    answer: str
    citations: list[AuditCitation]


class SentenceVerdict(BaseModel):
    text: str
    supported: bool
    reason: str


class AuditResponse(BaseModel):
    sentences: list[SentenceVerdict]


@router.post("/audit/run", response_model=AuditResponse)
@limiter.limit(RATE_LIMIT_AUDIT)
async def run_audit(request: Request, req: AuditRequest):
    """
    Non-streaming JSON endpoint for the Hallucination Auditor
    (services/auditor.py): grades every sentence of an already-generated
    answer as SUPPORTED or UNSUPPORTED by the given citations, in a
    single LLM call. Runs on-demand from the UI after an answer already
    exists — not automatically on every query, unlike the numeric
    faithfulness score in services/evaluator.py.
    """
    chunks = [{"filename": c.filename, "page_number": c.page, "text": c.text} for c in req.citations]
    sentences = audit_answer(req.answer, chunks)
    return {"sentences": sentences}
