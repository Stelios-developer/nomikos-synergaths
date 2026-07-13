import tempfile
import os

from fastapi import APIRouter, Request, UploadFile, File, HTTPException

from services.ingestion import ingest_pdf
from services.security import limiter, RATE_LIMIT_UPLOAD

router = APIRouter()


@router.post("/upload")
@limiter.limit(RATE_LIMIT_UPLOAD)
async def upload_pdf(request: Request, file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only .pdf files are accepted.")

    tmp_path = None
    try:
        contents = await file.read()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(contents)
            tmp_path = tmp.name

        result = ingest_pdf(tmp_path, file.filename)
        return result

    except NotImplementedError as e:
        # Scanned PDF, OCR not wired in yet (step 11 of the build).
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # Covers corrupted / unreadable PDFs (fitz raising on open/parse).
        raise HTTPException(status_code=400, detail=f"Could not process PDF: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
