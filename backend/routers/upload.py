from fastapi import APIRouter, Depends, Request, UploadFile, File

from services.document_publication import process_upload
from services.security import (
    MAX_UPLOAD_SIZE_MB,
    RATE_LIMIT_UPLOAD,
    limiter,
)
from services.session_scope import get_session_id

router = APIRouter()

MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024


@router.post("/upload")
@limiter.limit(RATE_LIMIT_UPLOAD)
async def upload_pdf(
    request: Request,
    file: UploadFile = File(...),
    session_id: str = Depends(get_session_id),
):
    return await process_upload(file, session_id, MAX_UPLOAD_SIZE_BYTES)
