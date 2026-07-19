"""
Ingestion pipeline: PDF -> page text -> chunks -> embeddings -> ChromaDB.

Step 3 of the implementation plan covers digital PDFs only (PyMuPDF).
OCR for scanned PDFs is added later in services/ocr.py (step 11); the
`extract_pages` function below already returns a per-page char count so
the scanned/digital decision can be wired in without changing callers.
"""
import os
import uuid
from datetime import datetime, timezone
from typing import Literal

import fitz  # PyMuPDF
from langchain_text_splitters import RecursiveCharacterTextSplitter

from db.chroma_client import get_collection
from services.embeddings import embed_texts
from services.session_scope import DEFAULT_SESSION_ID

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", 500))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", 50))
SCANNED_PDF_CHAR_THRESHOLD = 50  # chars/page below this -> treat as scanned


def extract_pages(pdf_path: str) -> list[dict]:
    """
    Returns one dict per page: {"page_number": int, "text": str, "char_count": int}.
    page_number is 1-indexed to match how citations should be shown to users.
    """
    pages = []
    doc = fitz.open(pdf_path)
    try:
        for i, page in enumerate(doc):
            text = page.get_text().strip()
            pages.append({
                "page_number": i + 1,
                "text": text,
                "char_count": len(text),
            })
    finally:
        doc.close()
    return pages


def is_scanned(pages: list[dict]) -> bool:
    """A PDF is treated as scanned if average chars/page is below threshold."""
    if not pages:
        return True
    avg_chars = sum(p["char_count"] for p in pages) / len(pages)
    return avg_chars < SCANNED_PDF_CHAR_THRESHOLD


def chunk_pages(pages: list[dict]) -> list[dict]:
    """
    Splits each page's text independently so every chunk stays attributable
    to a single page_number (chunks never span pages).
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    chunks = []
    chunk_index = 0
    for page in pages:
        if not page["text"]:
            continue
        for piece in splitter.split_text(page["text"]):
            chunks.append({
                "text": piece,
                "page_number": page["page_number"],
                "chunk_index": chunk_index,
            })
            chunk_index += 1
    return chunks


def embed_chunks(chunks: list[dict]) -> list[list[float]]:
    """Batch-embeds chunk texts with the local sentence-transformers model."""
    if not chunks:
        return []
    return embed_texts([c["text"] for c in chunks])


def ingest_pdf(pdf_path: str, filename: str, session_id: str = DEFAULT_SESSION_ID) -> dict:
    """
    Full pipeline for one PDF: extract -> chunk -> embed -> store.
    `session_id` stamps every chunk so it's only ever visible to the
    visitor who uploaded it (see services/session_scope.py) — defaults to
    the shared bucket used before per-visitor isolation existed, so
    callers that don't pass one (tests, direct API usage) are unaffected.
    Returns {"filename", "chunk_count", "method"}.
    """
    pages = extract_pages(pdf_path)
    method: Literal["pymupdf", "ocr"] = "ocr" if is_scanned(pages) else "pymupdf"

    if method == "ocr":
        from services.ocr import ocr_pages  # lazy import - keeps torch off the
                                             # hot path for the (common) digital-PDF case
        pages = ocr_pages(pdf_path)

    chunks = chunk_pages(pages)
    embeddings = embed_chunks(chunks)

    upload_date = datetime.now(timezone.utc).isoformat()

    collection = get_collection()
    if chunks:
        collection.add(
            ids=[f"{filename}::{c['chunk_index']}::{uuid.uuid4().hex[:8]}" for c in chunks],
            embeddings=embeddings,
            documents=[c["text"] for c in chunks],
            metadatas=[{
                "filename": filename,
                "page_number": c["page_number"],
                "chunk_index": c["chunk_index"],
                "method": method,
                "upload_date": upload_date,
                "session_id": session_id,
            } for c in chunks],
        )

    return {"filename": filename, "chunk_count": len(chunks), "method": method}
