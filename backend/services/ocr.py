"""Page OCR through the isolated PDF safety worker.

The upload route passes the reconstructed image-only PDF, never the original
untrusted document. Tesseract is configured for Greek and English in the
worker; the old EasyOCR configuration used an unsupported Greek code.
"""

from services.pdf_security_client import ocr_pdf


def ocr_pages(pdf_path: str) -> list[dict]:
    return ocr_pdf(pdf_path)
