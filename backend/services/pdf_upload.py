"""Shared, bounded validation for browser and n8n PDF uploads.

This rejects obvious unsafe or unsupported files. It is not malware scanning
or a substitute for an isolated parser/CDR at a production ingress.
"""
import os

import fitz
from fastapi import UploadFile
from starlette.concurrency import run_in_threadpool

from db.vector_store import get_collection
from services.pdf_security_client import PdfSecurityError, sanitize_pdf
from services.pdf_storage import pdf_path, storage_usage_bytes
from services.security import MAX_DOCUMENTS_PER_USER, MAX_PDF_PAGES, MAX_STORAGE_MB_PER_USER, MAX_UPLOAD_SIZE_MB
from services.runtime import is_production


class PdfUploadError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def validate_filename(filename: str | None) -> str:
    name = (filename or "").strip()
    if (
        not name or len(name) > 255 or not name.lower().endswith(".pdf")
        or name in {".", ".."}
        or any(char in name for char in ("/", "\\", "\x00", ":"))
        or any(ord(char) < 32 for char in name)
        or os.path.basename(name) != name
    ):
        raise PdfUploadError("Only PDF files with safe filenames are accepted.")
    return name


async def read_validated_pdf(file: UploadFile, max_bytes: int | None = None) -> tuple[str, bytes, int]:
    filename = validate_filename(file.filename)
    limit = max_bytes if max_bytes is not None else MAX_UPLOAD_SIZE_MB * 1024 * 1024
    # Never read an unbounded user-controlled body into process memory.
    contents = await file.read(limit + 1)
    if len(contents) > limit:
        raise PdfUploadError("PDF upload is too large.", status_code=413)
    if not contents.startswith(b"%PDF-"):
        raise PdfUploadError("The uploaded file is not a valid PDF.")

    if os.getenv("PDF_SECURITY_URL", "").strip():
        try:
            contents, page_count = await sanitize_pdf(contents, limit)
        except PdfSecurityError as exc:
            raise PdfUploadError(str(exc), status_code=exc.status_code) from exc
        if not 1 <= page_count <= MAX_PDF_PAGES:
            raise PdfUploadError(f"PDFs must contain between 1 and {MAX_PDF_PAGES} pages.")
        return filename, contents, page_count
    if is_production():
        raise PdfUploadError("The PDF safety service is required.", status_code=503)

    page_count = await run_in_threadpool(_validate_local_pdf, contents)
    return filename, contents, page_count


def _validate_local_pdf(contents: bytes) -> int:
    try:
        with fitz.open(stream=contents, filetype="pdf") as document:
            if document.is_encrypted or document.needs_pass:
                raise PdfUploadError("Password-protected PDFs are not supported.")
            if document.embfile_count() > 0:
                raise PdfUploadError("PDFs with embedded files are not supported.")
            page_count = document.page_count
    except PdfUploadError:
        raise
    except Exception as exc:
        raise PdfUploadError("The uploaded PDF could not be read.") from exc

    if not 1 <= page_count <= MAX_PDF_PAGES:
        raise PdfUploadError(f"PDFs must contain between 1 and {MAX_PDF_PAGES} pages.")
    return page_count


def enforce_workspace_capacity(filename: str, incoming_bytes: int, workspace_id: str) -> None:
    """Apply the same document and source-storage quotas to every ingress."""
    collection = get_collection()
    existing = collection.get(workspace_id=workspace_id, filename=filename, include=[])["ids"]
    if not existing:
        current = collection.get(workspace_id=workspace_id, include=["metadatas"])["metadatas"]
        if len({metadata["filename"] for metadata in current}) >= MAX_DOCUMENTS_PER_USER:
            raise PdfUploadError("Your workspace has reached its document limit.", status_code=413)

    previous_path = pdf_path(filename, session_id=workspace_id)
    previous_bytes = os.path.getsize(previous_path) if previous_path else 0
    if storage_usage_bytes(workspace_id) - previous_bytes + incoming_bytes > MAX_STORAGE_MB_PER_USER * 1024 * 1024:
        raise PdfUploadError("Your workspace has reached its PDF storage limit.", status_code=413)
