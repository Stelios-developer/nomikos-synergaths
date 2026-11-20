from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from db.vector_store import get_collection
from services.auditor import audit_answer
from services.security import limiter, RATE_LIMIT_AUDIT
from services.session_scope import get_session_id

router = APIRouter()


class AuditCitation(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    page: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=2000)


class AuditRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=20_000)
    citations: list[AuditCitation] = Field(max_length=12)


class SentenceVerdict(BaseModel):
    text: str
    supported: bool
    reason: str
    verification_unavailable: bool = False


class AuditResponse(BaseModel):
    sentences: list[SentenceVerdict]


@router.post("/audit/run", response_model=AuditResponse)
@limiter.limit(RATE_LIMIT_AUDIT)
async def run_audit(request: Request, req: AuditRequest, session_id: str = Depends(get_session_id)):
    """
    Non-streaming JSON endpoint for the Hallucination Auditor
    (services/auditor.py): grades every sentence of an already-generated
    answer against indexed citations in a single LLM call. Positive model
    verdicts require human source review. Runs on-demand from the UI after an answer already
    exists — not automatically on every query, unlike the numeric
    faithfulness score in services/evaluator.py.
    """
    # A browser-provided citation is untrusted. Require the exact page/text
    # pair to exist in the requesting workspace's current index before asking
    # the auditor to treat it as evidence.
    collection = get_collection()
    indexed: dict[str, set[tuple[int, str]]] = {}
    for citation in req.citations:
        if citation.filename not in indexed:
            rows = collection.get(
                workspace_id=session_id, filename=citation.filename,
                include=["documents", "metadatas"],
            )
            indexed[citation.filename] = {
                (int(metadata.get("page_number", 0)), text)
                for text, metadata in zip(rows.get("documents") or [], rows.get("metadatas") or [])
                if metadata and text
            }
        if (citation.page, citation.text) not in indexed[citation.filename]:
            raise HTTPException(status_code=400, detail="A citation is not part of this workspace's indexed evidence.")

    chunks = [{"filename": c.filename, "page_number": c.page, "text": c.text} for c in req.citations]
    sentences = audit_answer(req.answer, chunks)
    return {"sentences": sentences}
