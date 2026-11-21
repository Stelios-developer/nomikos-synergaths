"""Synthetic local checks inside the disposable worker pod; no data is persisted."""
import os
import sys
import urllib.error
import urllib.request

import fitz
from app import UnsafePdf, scan_with_clamav


def fetch(path, body=None, token=None):
    headers = {'Content-Type': 'application/pdf'} if body is not None else {}
    if token is not None:
        headers['X-PDF-Security-Token'] = token
    try:
        with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8080' + path, data=body, headers=headers), timeout=90) as response:
            return response.status, response.read(20 * 1024 * 1024)
    except urllib.error.HTTPError as exc:
        return exc.code, b''


token = os.environ['PDF_SECURITY_TOKEN']
with fitz.open() as document:
    page = document.new_page(); page.insert_text((60, 100), 'SYNTHETIC DOCUMENT', fontsize=20)
    payload = document.tobytes()

if sys.argv[1] == 'ready':
    assert fetch('/health')[0] == 200
    assert fetch('/v1/pdf/sanitize', payload, 'invalid')[0] == 401
    assert fetch('/v1/pdf/sanitize', b'%PDF-invalid', token)[0] == 422
    status, rebuilt = fetch('/v1/pdf/sanitize', payload, token)
    assert status == 200
    with fitz.open(stream=rebuilt, filetype='pdf') as clean:
        assert clean.page_count == 1 and not clean[0].get_text().strip()
    sample = b'X5O!P%@AP[4' + bytes([92]) + b'PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*'
    try:
        scan_with_clamav(sample)
    except UnsafePdf as exc:
        assert str(exc) == 'Malware was detected in the PDF.'
    else:
        raise AssertionError('EICAR not detected')
elif sys.argv[1] == 'scanner_down':
    assert fetch('/health')[0] == 503
    assert fetch('/v1/pdf/sanitize', payload, token)[0] == 422
else:
    raise ValueError('Unknown synthetic test phase')
print('Synthetic PDF worker assertions passed.')
