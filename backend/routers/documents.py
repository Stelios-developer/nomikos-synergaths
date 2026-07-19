from fastapi import APIRouter, HTTPException, Query, Response

from db.chroma_client import get_collection
from services.pdf_storage import delete_pdf, pdf_path
from services.page_render import render_page_png

router = APIRouter()


@router.get("/documents")
async def list_documents():
    """
    Derives the document list from chunk metadata already in ChromaDB
    (no separate documents table) — groups by filename, reporting
    chunk_count, the extraction method, and first-seen upload date.
    """
    collection = get_collection()
    all_rows = collection.get(include=["metadatas"])
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
async def delete_document(filename: str):
    collection = get_collection()
    collection.delete(where={"filename": filename})
    delete_pdf(filename)
    return {"filename": filename, "deleted": True}


@router.get("/documents/{filename}/page")
async def get_page_image(filename: str, page: int = Query(..., ge=1), snippet: str = Query("")):
    """
    Renders one page of the original PDF as a PNG, with `snippet` (the
    cited chunk's text) highlighted if it can be located on the page —
    lets the UI show a citation's exact source location instead of just
    the extracted text. Falls back to an unhighlighted page image if the
    snippet can't be matched (e.g. odd whitespace/hyphenation), and to a
    404 if the PDF itself was never stored or has since been deleted.
    """
    path = pdf_path(filename)
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
