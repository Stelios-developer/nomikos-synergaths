"""Local synthetic PDF assertions; scanner-down path is real, not a real scanner."""
import asyncio
import json
import os
import subprocess
from unittest.mock import patch

import fitz
from fastapi import HTTPException
from starlette.requests import Request
from app import UnsafePdf, health, run_private_job, sanitize_pdf


def request(data, token):
    headers = [(b'content-type', b'application/pdf'), (b'x-pdf-security-token', token.encode())]
    async def receive():
        return {'type': 'http.request', 'body': data, 'more_body': False}
    return Request({'type': 'http', 'method': 'POST', 'path': '/v1/pdf/sanitize', 'headers': headers}, receive)


async def rejected(data, token, expected):
    try:
        await sanitize_pdf(request(data, token))
    except HTTPException as exc:
        assert exc.status_code == expected
    else:
        raise AssertionError('Unsafe synthetic request was accepted')


with fitz.open() as document:
    page = document.new_page()
    page.insert_text((60, 100), 'SYNTHETIC DEADLINE 15 JULY 2027', fontsize=24)
    page.insert_link({'kind': fitz.LINK_URI, 'from': fitz.Rect(60, 80, 400, 110), 'uri': 'https://example.test/synthetic'})
    source = document.tobytes()

token = os.environ['PDF_SECURITY_TOKEN']
async def check_requests():
    await rejected(source, 'incorrect', 401)
    await rejected(b'invalid', token, 400)
    await rejected(source, token, 503)


asyncio.run(check_requests())
try:
    health()
except HTTPException as exc:
    assert exc.status_code == 503
else:
    raise AssertionError('Unavailable scanner reported healthy')
result = run_private_job('sanitize', source)
assert int.from_bytes(result[:4], 'big') == 1
with fitz.open(stream=result[4:], filetype='pdf') as document:
    assert document.page_count == 1 and not document[0].get_links()
    assert not document[0].get_text().strip()
pages = json.loads(run_private_job('ocr', result[4:]))['pages']
assert len(pages) == 1 and 'SYNTHETIC' in pages[0]['text'].upper()
try:
    run_private_job('sanitize', b'%PDF-invalid')
except UnsafePdf:
    pass
else:
    raise AssertionError('Malformed synthetic PDF accepted')
with patch('app.subprocess.run', side_effect=subprocess.TimeoutExpired('synthetic', 1)):
    try:
        run_private_job('ocr', result[4:])
    except UnsafePdf:
        pass
    else:
        raise AssertionError('Synthetic timeout did not fail closed')
print('Synthetic CDR/OCR, request rejection, scanner outage and mocked timeout passed.')
