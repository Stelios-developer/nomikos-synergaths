from unittest.mock import patch

from services import ingestion


def test_extract_pages_reads_real_text(sample_pdf_factory):
    pdf_path = sample_pdf_factory(num_pages=3)
    pages = ingestion.extract_pages(pdf_path)
    assert len(pages) == 3
    assert all(p["char_count"] > 50 for p in pages)
    assert [p["page_number"] for p in pages] == [1, 2, 3]


def test_is_scanned_true_for_blank_pdf(scanned_pdf_factory):
    pages = ingestion.extract_pages(scanned_pdf_factory(num_pages=1))
    assert ingestion.is_scanned(pages) is True


def test_is_scanned_false_for_digital_pdf(sample_pdf_factory):
    pages = ingestion.extract_pages(sample_pdf_factory(num_pages=1))
    assert ingestion.is_scanned(pages) is False


def test_chunk_pages_never_spans_pages(sample_pdf_factory):
    pages = ingestion.extract_pages(sample_pdf_factory(num_pages=3))
    chunks = ingestion.chunk_pages(pages)
    assert len(chunks) > 0
    assert set(c["page_number"] for c in chunks) == {1, 2, 3}
    # chunk_index is a single monotonic counter across the whole document
    assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))


def test_ingest_pdf_digital_end_to_end(sample_pdf_factory, fake_embeddings):
    result = ingestion.ingest_pdf(sample_pdf_factory(num_pages=2), "test.pdf")
    assert result["filename"] == "test.pdf"
    assert result["method"] == "pymupdf"
    assert result["chunk_count"] > 0

    from db.chroma_client import get_collection
    stored = get_collection().get(where={"filename": "test.pdf"})
    assert len(stored["documents"]) == result["chunk_count"]
    assert all(m["method"] == "pymupdf" for m in stored["metadatas"])


def test_ingest_pdf_scanned_routes_to_ocr(scanned_pdf_factory, fake_embeddings):
    fake_ocr_pages = [{"page_number": 1, "text": "OCR'd content about tax law.", "char_count": 28}]
    with patch("services.ocr.ocr_pages", return_value=fake_ocr_pages):
        result = ingestion.ingest_pdf(scanned_pdf_factory(num_pages=1), "scanned.pdf")

    assert result["method"] == "ocr"
    assert result["chunk_count"] == 1
