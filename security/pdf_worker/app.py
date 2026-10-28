"""Private, isolated PDF malware scan and visual CDR worker.

Only the reconstructed image-only PDF leaves this service. It deliberately
does not return the original bytes or extracted active PDF objects.
"""
import asyncio
import hmac
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile

import fitz
from fastapi import FastAPI, HTTPException, Request, Response

MAX_INPUT_BYTES = int(os.getenv("MAX_UPLOAD_SIZE_MB", "20")) * 1024 * 1024
MAX_OUTPUT_BYTES = MAX_INPUT_BYTES * 2
MAX_PAGES = int(os.getenv("MAX_PDF_PAGES", "250"))
MAX_PAGE_PIXELS = 20_000_000
RENDER_ZOOM = 1.5

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
job_slot = asyncio.Semaphore(1)


class UnsafePdf(ValueError):
    pass


def run_private_job(mode: str, contents: bytes) -> bytes:
    """Kill stalled parsers; bound output in ephemeral tmpfs, not a pipe."""
    timeout = 90 if mode == "sanitize" else 540
    try:
        with tempfile.TemporaryFile() as output:
            completed = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("pdf_task.py")), mode],
                input=contents, stdout=output, stderr=subprocess.DEVNULL,
                timeout=timeout, check=False,
                env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1", "OMP_THREAD_LIMIT": "1"},
            )
            if completed.returncode != 0:
                raise UnsafePdf("The PDF processing job rejected the file.")
            output.seek(0)
            result = output.read(MAX_OUTPUT_BYTES + 5)
            if len(result) > MAX_OUTPUT_BYTES + 4:
                raise UnsafePdf("The PDF processing output is too large.")
            return result
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise UnsafePdf("The PDF processing job exceeded its limits or is unavailable.") from exc


async def _reserve_job() -> None:
    try:
        await asyncio.wait_for(job_slot.acquire(), timeout=0.1)
    except TimeoutError as exc:
        raise HTTPException(status_code=429, detail="PDF processing is busy. Retry shortly.") from exc


def scan_with_clamav(contents: bytes) -> None:
    """Use clamd INSTREAM; every timeout, error, or ambiguous reply fails closed."""
    host = os.getenv("CLAMAV_HOST", "clamav")
    port = int(os.getenv("CLAMAV_PORT", "3310"))
    try:
        with socket.create_connection((host, port), timeout=20) as connection:
            connection.settimeout(40)
            connection.sendall(b"zINSTREAM\0")
            for offset in range(0, len(contents), 1024 * 1024):
                chunk = contents[offset:offset + 1024 * 1024]
                connection.sendall(struct.pack(">I", len(chunk)) + chunk)
            connection.sendall(struct.pack(">I", 0))
            reply = bytearray()
            while len(reply) < 4096:
                part = connection.recv(4096 - len(reply))
                if not part:
                    break
                reply.extend(part)
                if b"\0" in part:
                    break
    except (OSError, TimeoutError) as exc:
        raise UnsafePdf("Malware scanning is unavailable.") from exc
    verdict = bytes(reply).split(b"\0", 1)[0]
    if verdict.endswith(b" FOUND"):
        raise UnsafePdf("Malware was detected in the PDF.")
    if verdict != b"stream: OK":
        raise UnsafePdf("Malware scanning did not return a clean verdict.")


def reconstruct_pdf(contents: bytes) -> tuple[bytes, int]:
    """Rasterize each page into a new image-only PDF, without source objects."""
    try:
        with fitz.open(stream=contents, filetype="pdf") as source:
            if source.is_encrypted or source.needs_pass:
                raise UnsafePdf("Password-protected PDFs are not supported.")
            if source.embfile_count() > 0:
                raise UnsafePdf("PDFs with embedded files are not supported.")
            if not 1 <= source.page_count <= MAX_PAGES:
                raise UnsafePdf(f"PDFs must contain between 1 and {MAX_PAGES} pages.")
            result = fitz.open()
            try:
                for original in source:
                    rect = original.rect
                    if rect.is_empty or rect.is_infinite or rect.width > 2000 or rect.height > 2000:
                        raise UnsafePdf("The PDF contains an unsupported page size.")
                    if rect.width * rect.height * RENDER_ZOOM * RENDER_ZOOM > MAX_PAGE_PIXELS:
                        raise UnsafePdf("The PDF page is too large to reconstruct safely.")
                    pixmap = original.get_pixmap(matrix=fitz.Matrix(RENDER_ZOOM, RENDER_ZOOM), alpha=False)
                    image = pixmap.tobytes("jpeg", jpg_quality=80)
                    page = result.new_page(width=rect.width, height=rect.height)
                    page.insert_image(page.rect, stream=image)
                    if result.xref_length() > MAX_PAGES * 10 + 100:
                        raise UnsafePdf("The reconstructed PDF exceeded its object budget.")
                rebuilt = result.tobytes(garbage=4, deflate=True, clean=True)
            finally:
                result.close()
            if len(rebuilt) > MAX_OUTPUT_BYTES:
                raise UnsafePdf("The reconstructed PDF is too large.")
            return rebuilt, source.page_count
    except UnsafePdf:
        raise
    except Exception as exc:
        raise UnsafePdf("The PDF could not be safely reconstructed.") from exc


def extract_ocr_pages(contents: bytes) -> list[dict]:
    """OCR only the already-reconstructed image PDF, never original objects."""
    try:
        with fitz.open(stream=contents, filetype="pdf") as document:
            if not 1 <= document.page_count <= MAX_PAGES:
                raise UnsafePdf("Invalid OCR page count.")
            pages = []
            for index, page in enumerate(document):
                if page.rect.width * page.rect.height * 1.5 * 1.5 > MAX_PAGE_PIXELS:
                    raise UnsafePdf("The PDF page is too large to OCR safely.")
                pixels = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
                completed = subprocess.run(
                    ["tesseract", "stdin", "stdout", "-l", "ell+eng"],
                    input=pixels.tobytes("png"),
                    capture_output=True,
                    check=False,
                    timeout=45,
                )
                if completed.returncode != 0:
                    raise UnsafePdf("OCR could not process the PDF page.")
                text = completed.stdout.decode("utf-8", errors="replace").strip()
                pages.append({"page_number": index + 1, "text": text, "char_count": len(text)})
            return pages
    except UnsafePdf:
        raise
    except (subprocess.TimeoutExpired, OSError, RuntimeError) as exc:
        raise UnsafePdf("OCR is unavailable.") from exc
    except Exception as exc:
        raise UnsafePdf("OCR could not read the PDF.") from exc


def _authenticate_pdf_request(request: Request) -> None:
    token = os.getenv("PDF_SECURITY_TOKEN", "")
    if len(token) < 32 or not hmac.compare_digest(request.headers.get("X-PDF-Security-Token", ""), token):
        raise HTTPException(status_code=401, detail="Unauthorized.")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/pdf":
        raise HTTPException(status_code=415, detail="Only application/pdf is accepted.")


async def _read_bounded_pdf(request: Request, max_bytes: int) -> bytes:
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > max_bytes:
            raise HTTPException(status_code=413, detail="PDF is too large.")
    if not data.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="Invalid PDF signature.")
    return bytes(data)


@app.get("/health")
def health() -> dict:
    try:
        with socket.create_connection((os.getenv("CLAMAV_HOST", "clamav"), int(os.getenv("CLAMAV_PORT", "3310"))), timeout=3) as connection:
            connection.settimeout(3)
            connection.sendall(b"zPING\0")
            if connection.recv(32).split(b"\0", 1)[0] != b"PONG":
                raise OSError("clamd is not ready")
    except OSError as exc:
        raise HTTPException(status_code=503, detail="Scanner is not ready.") from exc
    return {"status": "ok"}


@app.post("/v1/pdf/sanitize")
async def sanitize_pdf(request: Request) -> Response:
    _authenticate_pdf_request(request)
    await _reserve_job()
    try:
        data = await _read_bounded_pdf(request, MAX_INPUT_BYTES)
        await asyncio.to_thread(scan_with_clamav, data)
        result = await asyncio.to_thread(run_private_job, "sanitize", data)
        pages = int.from_bytes(result[:4], "big")
        rebuilt = result[4:]
        if not 1 <= pages <= MAX_PAGES or not rebuilt.startswith(b"%PDF-"):
            raise UnsafePdf("Invalid PDF processing output.")
        await asyncio.to_thread(scan_with_clamav, rebuilt)
    except UnsafePdf as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        job_slot.release()
    return Response(
        content=rebuilt,
        media_type="application/pdf",
        headers={"X-PDF-CDR-Mode": "visual", "X-PDF-Pages": str(pages), "Cache-Control": "no-store"},
    )


@app.post("/v1/pdf/ocr")
async def ocr_pdf(request: Request) -> Response:
    _authenticate_pdf_request(request)
    await _reserve_job()
    try:
        data = await _read_bounded_pdf(request, MAX_OUTPUT_BYTES)
        await asyncio.to_thread(scan_with_clamav, data)
        result = await asyncio.to_thread(run_private_job, "ocr", data)
        pages = json.loads(result)["pages"]
        if not isinstance(pages, list) or not 1 <= len(pages) <= MAX_PAGES:
            raise UnsafePdf("Invalid OCR processing output.")
    except UnsafePdf as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid OCR processing output.") from exc
    finally:
        job_slot.release()
    return Response(result, media_type="application/json", headers={"Cache-Control": "no-store"})
