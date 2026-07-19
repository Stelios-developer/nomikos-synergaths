from fastapi import APIRouter, Request, UploadFile, File, HTTPException

from services.ingestion import ingest_pdf
from services.security import limiter, RATE_LIMIT_UPLOAD
from services.pdf_storage import save_pdf, delete_pdf

router = APIRouter()


@router.post("/upload")
@limiter.limit(RATE_LIMIT_UPLOAD)
async def upload_pdf(request: Request, file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only .pdf files are accepted.")

    contents = await file.read()

    # Persisted (not a temp file) so citations can later be traced back to
    # the original page — see services/page_render.py and
    # GET /documents/{filename}/page.
    pdf_path = save_pdf(file.filename, contents)

    try:
        result = ingest_pdf(pdf_path, file.filename)
        return result
    except NotImplementedError as e:
        # Scanned PDF, OCR not wired in yet (step 11 of the build).
        delete_pdf(file.filename)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # Covers corrupted / unreadable PDFs (fitz raising on open/parse).
        delete_pdf(file.filename)
        raise HTTPException(status_code=400, detail=f"Could not process PDF: {e}")
