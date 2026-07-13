"""
OCR fallback for scanned PDFs, using EasyOCR.

Rendering strategy: PyMuPDF rasterizes each page to an image (no
external Poppler/pdftoppm dependency needed — fitz does this natively),
then EasyOCR reads text off each page image. Runs once per PDF at
upload time, page by page, same as the digital-PDF path in ingestion.py.

Note: EasyOCR's first call downloads its detection + recognition model
weights (~100MB) and lazily loads a PyTorch backend. Both the model
download and the per-page inference are meaningfully slower than the
PyMuPDF digital-text path, so uploads that fall into the OCR branch will
take noticeably longer than digital ones - the frontend's "Uploading &
processing…" state (UploadZone.tsx) accounts for this, but a production
deployment would want to move this to a background task/queue instead
of blocking the request.
"""
import fitz  # PyMuPDF

_reader = None

# Matches the languages most likely to show up given the brief targets a
# Greek-speaking user; add more EasyOCR language codes as needed.
OCR_LANGUAGES = ["en", "el"]

# Higher = sharper OCR input, slower rendering. 2.0 (~144 DPI equivalent)
# is a reasonable trade-off for scanned office/legal documents.
RENDER_ZOOM = 2.0


def _get_reader():
    global _reader
    if _reader is None:
        import easyocr  # imported lazily so the rest of the app doesn't
                         # pay EasyOCR's heavy torch import cost on startup
        _reader = easyocr.Reader(OCR_LANGUAGES, gpu=False)
    return _reader


def _render_page_to_png_bytes(page: fitz.Page) -> bytes:
    matrix = fitz.Matrix(RENDER_ZOOM, RENDER_ZOOM)
    pix = page.get_pixmap(matrix=matrix)
    return pix.tobytes("png")


def ocr_pages(pdf_path: str) -> list[dict]:
    """
    Same return shape as ingestion.extract_pages: one dict per page,
    {"page_number": int, "text": str, "char_count": int}, so ingest_pdf
    can treat OCR'd and digitally-extracted pages identically once this
    function returns.
    """
    reader = _get_reader()
    pages = []
    doc = fitz.open(pdf_path)
    try:
        for i, page in enumerate(doc):
            png_bytes = _render_page_to_png_bytes(page)
            results = reader.readtext(png_bytes, detail=0)  # detail=0 -> just the strings
            text = " ".join(results).strip()
            pages.append({
                "page_number": i + 1,
                "text": text,
                "char_count": len(text),
            })
    finally:
        doc.close()
    return pages
