import os
import random

import fitz
import pytest

import db.chroma_client as chroma_client
import services.evaluator as evaluator_module
import services.pdf_storage as pdf_storage_module
import services.observability as observability_module


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """
    Every test gets its own ChromaDB dir + evaluation SQLite file + PDF
    storage dir + observability SQLite file, and the module-level
    singletons (db.chroma_client's client/collection) are reset so state
    never leaks between tests. observability.db in particular would
    otherwise get a row per TestClient(app) request via main.py's
    observability_middleware — every test file that exercises the app
    through TestClient, not just test_observability.py, so this has to be
    a global autouse fixture rather than something local to one test module.
    """
    monkeypatch.setattr(chroma_client, "CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    monkeypatch.setattr(chroma_client, "_client", None)
    monkeypatch.setattr(chroma_client, "_collection", None)
    monkeypatch.setattr(evaluator_module, "DB_PATH", str(tmp_path / "evaluation.db"))
    monkeypatch.setattr(observability_module, "OBS_DB_PATH", str(tmp_path / "observability.db"))
    pdf_dir = tmp_path / "pdfs"
    os.makedirs(pdf_dir, exist_ok=True)
    monkeypatch.setattr(pdf_storage_module, "PDF_STORAGE_DIR", str(pdf_dir))
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
def fake_embeddings(monkeypatch):
    """Patches ingestion.embed_texts so embed_chunks never loads the real
    (torch-based) sentence-transformers model."""
    import services.ingestion as ingestion_module

    def _fake_embed_texts(texts):
        return [[random.random() for _ in range(8)] for _ in texts]

    monkeypatch.setattr(ingestion_module, "embed_texts", _fake_embed_texts)
    return _fake_embed_texts


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


@pytest.fixture(autouse=True)
def isolate_docker_availability_cache():
    """
    services.sandbox caches whether Docker is available at module level
    (by design — probing `docker info`/`docker image inspect` on every
    single Action Agent run would be wasteful in production). That same
    caching means once one test exercises the Docker-available branch
    (mocked True), the cache leaks that True into every later test in the
    same pytest run — including unrelated ones that just want the default
    subprocess sandbox. Reset it before every test.
    """
    import services.sandbox as sandbox_module
    sandbox_module.reset_docker_availability_cache()
    yield


@pytest.fixture(autouse=True)
def isolate_llm_provider(monkeypatch):
    """
    main.py's load_dotenv() reads the real backend/.env the first time
    `main` is imported in the test process (dotenv only sets vars that
    aren't already present, so it happens exactly once and then lingers
    for every later test in the same pytest run). If that .env has
    LLM_PROVIDER=anthropic set — which it does on a normal dev setup,
    since it's the documented default — every test that assumes the
    "openai" default (i.e. every test that doesn't explicitly set
    LLM_PROVIDER itself) would silently start hitting the real Anthropic
    API instead of the mocked client, causing flaky/order-dependent
    failures (or worse, quietly making a real network call using
    whatever ANTHROPIC_API_KEY happens to be in .env). Force a clean slate
    before every test; tests that need "anthropic" already set it
    themselves via monkeypatch, which takes precedence within that test.
    """
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    yield
