"""
Renders a single PDF page as a PNG with the cited chunk's text highlighted —
powers the "view source page" citation feature (click a citation, see the
exact excerpt highlighted on the real page, not just the extracted text).

Matching strategy: PyMuPDF's page.search_for() does its own text extraction
internally and handles line-wrapped text reasonably well, but a full ~500
char chunk (our CHUNK_SIZE) is often too long to match verbatim against the
page (whitespace/hyphenation can differ slightly from our extracted text).
So matching degrades gracefully: try the full snippet first, then shorter
and shorter prefixes, down to a handful of words. If nothing matches at
all, we still return the page image unhighlighted rather than erroring —
seeing the right page is still useful even without the highlight.
"""
import fitz  # PyMuPDF

RENDER_ZOOM = 2.0  # 2x zoom for a crisper image than the PDF's native size
FALLBACK_LENGTHS = [500, 200, 100, 60]  # chars, tried in order after the full snippet
MIN_FALLBACK_WORDS = 5


def _find_rects(page: "fitz.Page", snippet: str) -> list["fitz.Rect"]:
    snippet = snippet.strip()
    if not snippet:
        return []

    rects = page.search_for(snippet)
    if rects:
        return rects

    for length in FALLBACK_LENGTHS:
        candidate = snippet[:length].strip()
        if len(candidate) < 10:
            continue
        rects = page.search_for(candidate)
        if rects:
            return rects

    words = snippet.split()
    if len(words) >= MIN_FALLBACK_WORDS:
        candidate = " ".join(words[:MIN_FALLBACK_WORDS])
        rects = page.search_for(candidate)
        if rects:
            return rects

    return []


def render_page_png(pdf_path: str, page_number: int, snippet: str = "") -> bytes:
    """
    Renders `page_number` (1-indexed, matching the citations shown to
    users) from the PDF at pdf_path as a PNG, highlighting `snippet` if it
    can be located on the page. Raises ValueError for an out-of-range page.
    """
    doc = fitz.open(pdf_path)
    try:
        if page_number < 1 or page_number > len(doc):
            raise ValueError(f"Page {page_number} out of range (document has {len(doc)} pages).")

        page = doc[page_number - 1]
        rects = _find_rects(page, snippet)
        for rect in rects:
            annot = page.add_highlight_annot(rect)
            annot.set_colors(stroke=(0.98, 0.78, 0.30))  # matches the UI's gold accent
            annot.update()

        pix = page.get_pixmap(matrix=fitz.Matrix(RENDER_ZOOM, RENDER_ZOOM))
        return pix.tobytes("png")
    finally:
        doc.close()
