from fastapi import APIRouter

from db.chroma_client import get_collection

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
    return {"filename": filename, "deleted": True}
