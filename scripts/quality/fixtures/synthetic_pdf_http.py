"""Exercise the real backend PDF ingress client against an isolated worker."""
import asyncio
import io
import os
import sys

import fitz
from fastapi import UploadFile
from services.pdf_upload import PdfUploadError, read_validated_pdf


def document():
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((60, 100), 'SYNTHETIC DOCUMENT')
        page.insert_link({'kind': fitz.LINK_URI, 'from': fitz.Rect(60, 80, 400, 110),
                          'uri': 'https://example.test/fixture'})
        return pdf.tobytes()


async def upload(data):
    return await read_validated_pdf(UploadFile(filename='synthetic.pdf', file=io.BytesIO(data)), 2 * 1024 * 1024)


async def main():
    data = document()
    if sys.argv[1] == 'scanner_down':
        try:
            await upload(data)
        except PdfUploadError as exc:
            assert exc.status_code == 503
        else:
            raise AssertionError('Unavailable scanner was accepted')
        return
    assert sys.argv[1] == 'ready'
    filename, sanitized, pages = await upload(data)
    assert filename == 'synthetic.pdf' and pages == 1
    with fitz.open(stream=sanitized, filetype='pdf') as pdf:
        assert pdf.page_count == 1 and not pdf[0].get_links() and not pdf[0].get_text().strip()
    for payload, expected in ((b'%PDF-invalid', 400), (b'not-a-pdf', 400)):
        try:
            await upload(payload)
        except PdfUploadError as exc:
            assert exc.status_code == expected
        else:
            raise AssertionError('Invalid synthetic input was accepted')
    original = os.environ['PDF_SECURITY_TOKEN']
    os.environ['PDF_SECURITY_TOKEN'] = 'incorrect-synthetic-token'
    try:
        try:
            await upload(data)
        except PdfUploadError as exc:
            assert exc.status_code == 503
        else:
            raise AssertionError('Invalid worker token was accepted')
    finally:
        os.environ['PDF_SECURITY_TOKEN'] = original


asyncio.run(main())
print('Synthetic backend PDF client check passed.')
