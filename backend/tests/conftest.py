import os
import random
import sys

import fitz
import pytest

import db.vector_store as vector_store
from tests.vector_fake import MemoryVectors
import services.case_store as case_store_module
import services.evaluator as evaluator_module
import services.observability as observability_module
import services.pdf_storage as pdf_storage_module


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Give every test its own documents, vector store, and metrics database."""
    # Unit tests must not inherit a running Docker service from local .env.
    # Worker-specific tests explicitly configure/mimic that boundary.
    monkeypatch.delenv("PDF_SECURITY_URL", raising=False)
    monkeypatch.delenv("PDF_SECURITY_TOKEN", raising=False)
    monkeypatch.setenv('ANALYSIS_DISPATCH_ENABLED','false')
    monkeypatch.delenv('ANALYSIS_DISPATCH_DATABASE_URL',raising=False)
    monkeypatch.setattr(vector_store, "_collection", MemoryVectors())
    monkeypatch.setattr(evaluator_module, "DB_PATH", str(tmp_path / "evaluation.db"))
    monkeypatch.setattr(case_store_module, "CASE_DB_PATH", str(tmp_path / "document_cases.db"))
    monkeypatch.setattr(observability_module, "OBS_DB_PATH", str(tmp_path / "observability.db"))
    pdf_dir = tmp_path / "pdfs"
    os.makedirs(pdf_dir, exist_ok=True)
    monkeypatch.setattr(pdf_storage_module, "PDF_STORAGE_DIR", str(pdf_dir))
    yield


@pytest.fixture
def sample_pdf_factory(tmp_path):
    def _make(num_pages=2, sentence="This is sample text about tax technology consulting. "):
        path = tmp_path / "sample.pdf"
        document = fitz.open()
        for index in range(num_pages):
            page = document.new_page()
            page.insert_text((50, 72), f"Page {index + 1}. " + sentence * 15, fontsize=10)
        document.save(str(path))
        document.close()
        return str(path)
    return _make


@pytest.fixture
def scanned_pdf_factory(tmp_path):
    def _make(num_pages=1):
        path = tmp_path / "scanned.pdf"
        document = fitz.open()
        for _ in range(num_pages):
            document.new_page()
        document.save(str(path))
        document.close()
        return str(path)
    return _make


@pytest.fixture
def fake_embeddings(monkeypatch):
    import services.ingestion as ingestion_module

    def _fake_embed_texts(texts):
        return [[random.random() for _ in range(8)] for _ in texts]

    monkeypatch.setattr(ingestion_module, "embed_texts", _fake_embed_texts)
    return _fake_embed_texts


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    # Pure service tests need not import the entire API/embedding stack.
    main = sys.modules.get("main")
    if main is not None:
        main.app.state.limiter.reset()
    yield


@pytest.fixture(autouse=True)
def isolate_llm_provider(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    yield


@pytest.fixture(autouse=True)
def isolate_dependency_guard(monkeypatch):
    bridge = sys.modules.get("services.n8n_orchestrator")
    if bridge is not None:
        from services.resilience import DependencyGuard
        monkeypatch.setattr(bridge, "_workflow_guard", DependencyGuard(
            count_failure=lambda exc: isinstance(exc, bridge.N8nOrchestratorError) and exc.retryable,
        ))
