"""Synthetic PDF and harmless EICAR check against an isolated real scanner."""
import asyncio
import os

import fitz
from fastapi import HTTPException
from starlette.requests import Request
from app import UnsafePdf, health, sanitize_pdf, scan_with_clamav


def request(data, token):
    async def receive():
        return {'type': 'http.request', 'body': data, 'more_body': False}
    return Request({'type': 'http', 'method': 'POST', 'path': '/v1/pdf/sanitize',
                    'headers': [(b'content-type', b'application/pdf'), (b'x-pdf-security-token', token.encode())]}, receive)


assert health() == {'status': 'ok'}
scan_with_clamav(b'Synthetic safe content')
sample = b'X5O!P%@AP[4' + bytes([92]) + b'PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*'
try:
    scan_with_clamav(sample)
except UnsafePdf as exc:
    assert str(exc) == 'Malware was detected in the PDF.'
else:
    raise AssertionError('Harmless EICAR fixture was not detected')

with fitz.open() as document:
    page = document.new_page()
    page.insert_text((60, 100), 'SYNTHETIC DOCUMENT', fontsize=20)
    page.insert_link({'kind': fitz.LINK_URI, 'from': fitz.Rect(60, 80, 400, 110), 'uri': 'https://example.test/fixture'})
    payload = document.tobytes()


async def check():
    token = os.environ['PDF_SECURITY_TOKEN']
    result = await sanitize_pdf(request(payload, token))
    assert result.status_code == 200 and result.headers['x-pdf-cdr-mode'] == 'visual'
    with fitz.open(stream=result.body, filetype='pdf') as clean:
        assert clean.page_count == 1 and not clean[0].get_links() and not clean[0].get_text().strip()
    try:
        await sanitize_pdf(request(b'%PDF-invalid', token))
    except HTTPException as exc:
        assert exc.status_code == 422
    else:
        raise AssertionError('Malformed synthetic PDF was accepted')


asyncio.run(check())
print('Real isolated scanner: clean content, EICAR, CDR and malformed rejection passed.')
