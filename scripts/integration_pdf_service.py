"""Synthetic checks against DMC's local CDR/OCR gateway and ClamAV only.

No documents are saved or uploaded to the application or an AI provider.
"""

import json
from pathlib import Path
import subprocess
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from dotenv import dotenv_values
import fitz

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:5186"


def request(path, data=None, token=None):
    headers = {"Content-Type": "application/pdf"} if data is not None else {}
    if token:
        headers["X-PDF-Security-Token"] = token
    try:
        with urlopen(
            Request(BASE + path, data=data, headers=headers), timeout=120
        ) as response:
            return response.status, response.read(2 * 1024 * 1024)
    except HTTPError as exc:
        return exc.code, exc.read(4096)


def main():
    token = dotenv_values(ROOT / "security/pdf_worker/.env").get("PDF_SECURITY_TOKEN")
    if not token or len(token) < 32:
        raise RuntimeError("Configure the local PDF service first")
    assert request("/health")[0] == 200, "ClamAV-backed gateway is not ready"
    assert request("/v1/pdf/sanitize", b"%PDF-fixture")[0] == 401
    assert request("/v1/pdf/sanitize", b"%PDF-invalid", token)[0] == 422
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((60, 120), "SYNTHETIC LOCAL DEADLINE", fontsize=24)
        page.insert_link(
            {
                "kind": fitz.LINK_URI,
                "from": fitz.Rect(60, 100, 500, 130),
                "uri": "https://example.test/fixture",
            }
        )
        source = document.tobytes()
    code, sanitized = request("/v1/pdf/sanitize", source, token)
    assert code == 200, "Clean synthetic PDF was rejected"
    with fitz.open(stream=sanitized, filetype="pdf") as document:
        assert document.page_count == 1 and not document[0].get_links()
        assert not document[0].get_text().strip() and document.embfile_count() == 0
    code, content = request("/v1/pdf/ocr", sanitized, token)
    assert (
        code == 200 and "SYNTHETIC" in json.loads(content)["pages"][0]["text"].upper()
    )
    # The harmless EICAR string is held in memory, sent only to the local scanner.
    program = r"""
from app import scan_with_clamav,UnsafePdf
sample=b'X5O!P%@AP[4'+bytes([92])+b'PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*'
try: scan_with_clamav(sample)
except UnsafePdf as exc: assert str(exc)=='Malware was detected in the PDF.'
else: raise AssertionError('EICAR was not detected')
print('EICAR detection PASSED')
"""
    checked = subprocess.run(
        ["docker", "exec", "-i", "pdf_worker-pdf-worker-1", "python", "-c", program],
        capture_output=True,
        timeout=60,
    )
    if checked.returncode:
        raise RuntimeError("Local EICAR scanner check failed")
    image = subprocess.check_output(
        ["docker", "inspect", "--format", "{{.Image}}", "pdf_worker-pdf-worker-1"],
        text=True,
    ).strip()
    report = {
        "gate": "PASSED",
        "image": image,
        "gateway_health": True,
        "unauthorized_denied": True,
        "malformed_denied": True,
        "cdr": True,
        "ocr": True,
        "eicar_detected": True,
        "scope": "Local synthetic PDF and in-memory harmless EICAR; no AI call or customer data.",
    }
    target = ROOT / "output/engineering-audit/pdf-service.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    print("Local PDF gateway, CDR/OCR, rejection and ClamAV EICAR checks PASSED.")


if __name__ == "__main__":
    main()
