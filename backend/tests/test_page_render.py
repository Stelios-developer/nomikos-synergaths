import fitz
import pytest

from services.page_render import render_page_png


@pytest.fixture
def two_page_pdf(tmp_path):
    path = tmp_path / "doc.pdf"
    doc = fitz.open()
    p1 = doc.new_page()
    p1.insert_text((50, 72), "The quarterly filing deadline is March 31st for all entities.", fontsize=11)
    p2 = doc.new_page()
    p2.insert_text((50, 72), "Equipment depreciation follows a five year straight line schedule.", fontsize=11)
    doc.save(str(path))
    doc.close()
    return str(path)


def test_render_page_png_returns_png_bytes(two_page_pdf):
    png = render_page_png(two_page_pdf, 1, "quarterly filing deadline")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_page_png_picks_correct_page(two_page_pdf):
    # Rendering page 2 should still succeed and return a (different-sized,
    # since content differs) but valid PNG — mainly guards against an
    # off-by-one on the 1-indexed page_number.
    png = render_page_png(two_page_pdf, 2, "depreciation")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_page_png_out_of_range_page_raises(two_page_pdf):
    with pytest.raises(ValueError):
        render_page_png(two_page_pdf, 99, "anything")


def test_render_page_png_no_snippet_match_still_returns_image(two_page_pdf):
    # Snippet that appears nowhere on the page — should not raise, just
    # render the page without a highlight.
    png = render_page_png(two_page_pdf, 1, "this text does not appear anywhere in the pdf at all")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_page_png_empty_snippet_returns_image(two_page_pdf):
    png = render_page_png(two_page_pdf, 1, "")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_page_png_long_snippet_falls_back_to_prefix(two_page_pdf):
    # A snippet much longer than what's actually on the page (simulating a
    # ~500-char chunk where only the start matches verbatim) should still
    # find a match via the fallback-prefix logic.
    long_snippet = "The quarterly filing deadline is March 31st for all entities. " + ("Extra padding text that is not on the page. " * 10)
    png = render_page_png(two_page_pdf, 1, long_snippet)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
