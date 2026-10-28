"""Call the private PDF safety service before any untrusted PDF reaches PyMuPDF.

The service is a separate, resource-limited container. A failure is never a
clean verdict. In development the service is optional; production requires it.
"""
import asyncio
import json
import os
from urllib import error, request
from services.runtime import is_production


class PdfSecurityError(ValueError):
    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


def _sanitize(contents: bytes, max_bytes: int) -> tuple[bytes, int]:
    url = os.getenv("PDF_SECURITY_URL", "").strip()
    if not url:
        raise PdfSecurityError("The PDF safety service is not configured.")
    token = os.getenv("PDF_SECURITY_TOKEN", "")
    req = request.Request(
        url.rstrip("/") + "/v1/pdf/sanitize",
        data=contents,
        headers={"Content-Type": "application/pdf", "X-PDF-Security-Token": token},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=90) as response:
            if response.status != 200:
                raise PdfSecurityError("The PDF safety service rejected the file.")
            mode = response.headers.get("X-PDF-CDR-Mode", "")
            if is_production() and mode != "visual":
                raise PdfSecurityError("Production requires visual PDF reconstruction.")
            try:
                page_count = int(response.headers.get("X-PDF-Pages", ""))
            except ValueError as exc:
                raise PdfSecurityError("The PDF safety service returned invalid metadata.") from exc
            # A reconstructed PDF can be larger than its source, but must be bounded.
            sanitized = response.read(max_bytes * 2 + 1)
            if len(sanitized) > max_bytes * 2 or not sanitized.startswith(b"%PDF-"):
                raise PdfSecurityError("The PDF safety service returned an invalid or oversized PDF.")
            return sanitized, page_count
    except error.HTTPError as exc:
        if exc.code in {400, 413, 415, 422}:
            status_code = 413 if exc.code == 413 else 400
            raise PdfSecurityError("The PDF safety service rejected the file.", status_code) from exc
        raise PdfSecurityError("The PDF safety service is unavailable.") from exc
    except (error.URLError, TimeoutError, OSError) as exc:
        raise PdfSecurityError("The PDF safety service is unavailable.") from exc


async def sanitize_pdf(contents: bytes, max_bytes: int) -> tuple[bytes, int]:
    return await asyncio.to_thread(_sanitize, contents, max_bytes)


def ocr_pdf(pdf_path: str) -> list[dict]:
    """Extract Greek/English text from a reconstructed PDF in the worker."""
    url = os.getenv("PDF_SECURITY_URL", "").strip()
    if not url:
        raise PdfSecurityError("The PDF OCR service is not configured.")
    with open(pdf_path, "rb") as source:
        # The CDR output is capped at 2x the 20 MiB upload limit.
        data = source.read(40 * 1024 * 1024 + 1)
    if len(data) > 40 * 1024 * 1024:
        raise PdfSecurityError("The PDF is too large for OCR.")
    req = request.Request(
        url.rstrip("/") + "/v1/pdf/ocr",
        data=data,
        headers={
            "Content-Type": "application/pdf",
            "X-PDF-Security-Token": os.getenv("PDF_SECURITY_TOKEN", ""),
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=600) as response:
            payload = response.read(40 * 1024 * 1024 + 1)
            if len(payload) > 40 * 1024 * 1024:
                raise PdfSecurityError("The OCR response is too large.")
        pages = json.loads(payload)["pages"]
        if not isinstance(pages, list) or not 1 <= len(pages) <= 250:
            raise ValueError("Invalid OCR page count")
        for index, page in enumerate(pages, 1):
            if not isinstance(page, dict) or page.get("page_number") != index or not isinstance(page.get("text"), str):
                raise ValueError("Invalid OCR page data")
            if len(page["text"]) > 100_000 or page.get("char_count") != len(page["text"]):
                raise ValueError("Invalid OCR text length")
        return pages
    except (error.URLError, TimeoutError, OSError, KeyError, ValueError, TypeError) as exc:
        raise PdfSecurityError("The PDF OCR service failed.") from exc
