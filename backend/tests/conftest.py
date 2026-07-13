import random

import fitz
import pytest

import db.chroma_client as chroma_client
import services.evaluator as evaluator_module


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """
    Every test gets its own ChromaDB dir + evaluation SQLite file, and the
    module-level singletons (db.chroma_client's client/collection) are
    reset so state never leaks between tests.
    """
    monkeypatch.setattr(chroma_client, "CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    monkeypatch.setattr(chroma_client, "_client", None)
    monkeypatch.setattr(chroma_client, "_collection", None)
    monkeypatch.setattr(evaluator_module, "DB_PATH", str(tmp_path / "evaluation.db"))
    yield


@pytest.fixture
def sample_pdf_factory(tmp_path):
    """Builds a small digital PDF with real extractable text per page."""
    def _make(num_pages=2, sentence="This is sample text about tax technology consulting. "):
        path = tmp_path / "sample.pdf"
        doc = fitz.open()
        for i in range(num_pages):
            page = doc.new_page()
            page.insert_text((50, 72), f"Page {i + 1}. " + sentence * 15, fontsize=10)
        doc.save(str(path))
        doc.close()
        return str(path)
    return _make


@pytest.fixture
def scanned_pdf_factory(tmp_path):
    """Builds a PDF with blank pages (no extractable text) — triggers the
    OCR branch of ingest_pdf."""
    def _make(num_pages=1):
        path = tmp_path / "scanned.pdf"
        doc = fitz.open()
        for _ in range(num_pages):
            doc.new_page()
        doc.save(str(path))
        doc.close()
        return str(path)
    return _make


@pytest.fixture
def fake_openai_embeddings(monkeypatch):
    """Patches ingestion._get_openai_client so embed_chunks/embed_query
    never touch the network."""
    import services.ingestion as ingestion_module

    class FakeEmbeddingItem:
        def __init__(self, v):
            self.embedding = v

    class FakeResp:
        def __init__(self, n):
            self.data = [FakeEmbeddingItem([random.random() for _ in range(8)]) for _ in range(n)]

    class FakeEmbeddings:
        def create(self, model, input):
            return FakeResp(len(input))

    class FakeClient:
        embeddings = FakeEmbeddings()

    monkeypatch.setattr(ingestion_module, "_get_openai_client", lambda: FakeClient())
    return FakeClient()


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """slowapi's limiter keeps in-memory per-IP counters across the whole
    test session (the FastAPI app is imported once); reset before each
    test so rate-limit tests don't get polluted by earlier ones."""
    try:
        import main
        main.app.state.limiter.reset()
    except Exception:
        pass
    yield
