import asyncio
import importlib.util
import io
import json
from pathlib import Path
from urllib.error import HTTPError

import fitz
import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient

from services.pdf_security_client import PdfSecurityError, _sanitize, ocr_pdf
from services.pdf_upload import PdfUploadError, read_validated_pdf


def _worker_module():
    path = Path(__file__).resolve().parents[2] / "security" / "pdf_worker" / "app.py"
    spec = importlib.util.spec_from_file_location("pdf_safety_worker", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pdf(text="A deadline is 30 June."):
    document = fitz.open()
    page = document.new_page()
    page.insert_text((50, 70), text)
    data = document.tobytes()
    document.close()
    return data


def test_visual_cdr_preserves_page_image_but_removes_pdf_text_objects():
    worker = _worker_module()
    with fitz.open(stream=_pdf(), filetype="pdf") as original:
        action = original.get_new_xref()
        original.update_object(action, "<< /S /JavaScript /JS (app.alert\\(test\\)) >>")
        original.xref_set_key(original.pdf_catalog(), "OpenAction", f"{action} 0 R")
        source = original.tobytes()
    assert b"/JavaScript" in source
    rebuilt, page_count = worker.reconstruct_pdf(source)
    assert page_count == 1
    with fitz.open(stream=rebuilt, filetype="pdf") as result:
        assert result.page_count == 1
        assert result[0].get_text().strip() == ""
        assert result[0].get_images()
        assert "/JavaScript" not in result.xref_object(result.pdf_catalog())
        assert "/OpenAction" not in result.xref_object(result.pdf_catalog())


def test_worker_fails_closed_when_scanner_unavailable(monkeypatch):
    worker = _worker_module()
    monkeypatch.setenv("PDF_SECURITY_TOKEN", "s" * 40)

    def unavailable(_contents):
        raise worker.UnsafePdf("Malware scanning is unavailable.")

    monkeypatch.setattr(worker, "scan_with_clamav", unavailable)
    response = TestClient(worker.app).post(
        "/v1/pdf/sanitize",
        content=_pdf(),
        headers={"Content-Type": "application/pdf", "X-PDF-Security-Token": "s" * 40},
    )
    assert response.status_code == 422
    assert "unavailable" in response.json()["detail"]


def test_worker_rejects_missing_token_and_embedded_file(monkeypatch):
    worker = _worker_module()
    monkeypatch.setenv("PDF_SECURITY_TOKEN", "s" * 40)
    monkeypatch.setattr(worker, "scan_with_clamav", lambda _contents: None)
    client = TestClient(worker.app)
    assert client.post("/v1/pdf/sanitize", content=_pdf(), headers={"Content-Type": "application/pdf"}).status_code == 401
    document = fitz.open()
    document.new_page()
    document.embfile_add("danger.txt", b"payload")
    attached = document.tobytes()
    document.close()
    response = client.post(
        "/v1/pdf/sanitize",
        content=attached,
        headers={"Content-Type": "application/pdf", "X-PDF-Security-Token": "s" * 40},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("reply,allowed", [
    (b"stream: OK\0", True),
    (b"stream: Eicar-Test-Signature FOUND\0", False),
    (b"INSTREAM size limit exceeded\0", False),
    (b"", False),
])
def test_clamav_only_accepts_an_explicit_clean_verdict(monkeypatch, reply, allowed):
    worker = _worker_module()

    class FakeSocket:
        def __init__(self):
            self.sent = bytearray()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def settimeout(self, _seconds):
            return None

        def sendall(self, payload):
            self.sent.extend(payload)

        def recv(self, _size):
            result = self.reply
            self.reply = b""
            return result

    connection = FakeSocket()
    connection.reply = reply
    monkeypatch.setattr(worker.socket, "create_connection", lambda *_args, **_kwargs: connection)
    if allowed:
        worker.scan_with_clamav(b"sample")
    else:
        with pytest.raises(worker.UnsafePdf):
            worker.scan_with_clamav(b"sample")
    assert connection.sent.startswith(b"zINSTREAM\0")


def test_production_pdf_ingress_requires_worker(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("PDF_SECURITY_URL", raising=False)
    file = UploadFile(filename="paper.pdf", file=io.BytesIO(_pdf()))
    with pytest.raises(PdfUploadError, match="required"):
        asyncio.run(read_validated_pdf(file))


def test_private_worker_output_is_used_before_ingestion(monkeypatch):
    monkeypatch.setenv("PDF_SECURITY_URL", "http://127.0.0.1:5186")
    safe = _pdf("Only the worker output may be indexed.")

    async def fake_sanitize(_contents, _max_bytes):
        return safe, 1

    monkeypatch.setattr("services.pdf_upload.sanitize_pdf", fake_sanitize)
    file = UploadFile(filename="paper.pdf", file=io.BytesIO(_pdf("Untrusted original")))
    filename, returned, count = asyncio.run(read_validated_pdf(file))
    assert filename == "paper.pdf"
    assert returned == safe
    assert count == 1


def test_worker_ocr_requires_token_and_returns_page_text(monkeypatch):
    worker = _worker_module()
    monkeypatch.setenv("PDF_SECURITY_TOKEN", "s" * 40)
    monkeypatch.setattr(worker, "scan_with_clamav", lambda _contents: None)

    pages = [{"page_number": 1, "text": "Προθεσμία 30 Ιουνίου", "char_count": len("Προθεσμία 30 Ιουνίου")}]
    monkeypatch.setattr(worker, "run_private_job", lambda *_args: json.dumps({"pages": pages}).encode())
    client = TestClient(worker.app)
    assert client.post("/v1/pdf/ocr", content=_pdf(), headers={"Content-Type": "application/pdf"}).status_code == 401
    response = client.post(
        "/v1/pdf/ocr",
        content=_pdf(),
        headers={"Content-Type": "application/pdf", "X-PDF-Security-Token": "s" * 40},
    )
    assert response.status_code == 200
    assert response.json()["pages"] == [{"page_number": 1, "text": "Προθεσμία 30 Ιουνίου", "char_count": len("Προθεσμία 30 Ιουνίου")}]


def test_backend_rejects_invalid_ocr_response(monkeypatch, tmp_path):
    source = tmp_path / "safe.pdf"
    source.write_bytes(_pdf())
    monkeypatch.setenv("PDF_SECURITY_URL", "http://worker.internal")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return b'{"pages":[{"page_number":1,"text":"ok","char_count":99}]}'

    monkeypatch.setattr("services.pdf_security_client.request.urlopen", lambda *_args, **_kwargs: FakeResponse())
    with pytest.raises(PdfSecurityError, match="OCR service failed"):
        ocr_pdf(str(source))


def test_worker_rejection_is_distinct_from_service_outage(monkeypatch):
    monkeypatch.setenv("PDF_SECURITY_URL", "http://worker.internal")

    def rejected(*_args, **_kwargs):
        raise HTTPError("http://worker.internal", 422, "rejected", {}, None)

    monkeypatch.setattr("services.pdf_security_client.request.urlopen", rejected)
    with pytest.raises(PdfSecurityError) as caught:
        _sanitize(_pdf(), 20 * 1024 * 1024)
    assert caught.value.status_code == 400


def test_parser_job_timeout_fails_closed(monkeypatch):
    worker = _worker_module()

    def stalled(*_args, **_kwargs):
        raise worker.subprocess.TimeoutExpired("pdf_task", 90)

    monkeypatch.setattr(worker.subprocess, "run", stalled)
    with pytest.raises(worker.UnsafePdf, match="limits"):
        worker.run_private_job("sanitize", _pdf())
