import asyncio
import io
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import numpy as np
from fastapi import UploadFile
from fastapi.testclient import TestClient

import main
from db.vector_store import get_collection
from services import case_store, document_publication, pdf_storage
from services.session_scope import DEFAULT_SESSION_ID
from services.workspace_lock import WorkspaceUnavailable, marker_path, workspace_access


def _seed(sample_pdf_factory):
    original = Path(sample_pdf_factory(sentence="Original source text. ")).read_bytes()
    document_publication.publish_pdf("memo.pdf", original, DEFAULT_SESSION_ID)
    case_store.create_case({"case_id": "original", "workspace_id": DEFAULT_SESSION_ID,
        "document": {"filename": "memo.pdf"}, "status": "finalized", "stage": "finalized"})
    return original, get_collection().get(workspace_id=DEFAULT_SESSION_ID, filename="memo.pdf", include=["documents", "metadatas", "embeddings"])


@pytest.mark.parametrize("failure", ["source", "case"])
def test_failed_commit_restores_complete_previous_generation(sample_pdf_factory, fake_embeddings, failure):
    original, snapshot = _seed(sample_pdf_factory)
    replacement = Path(sample_pdf_factory(sentence="Replacement source text. ")).read_bytes()
    target = "services.document_publication.pdf_storage.commit_staged_pdf" if failure == "source" else "services.document_publication.case_store.delete_cases_for_document"
    with patch(target, side_effect=OSError("simulated disk failure")) as failing_commit:
        with pytest.raises(OSError):
            document_publication.publish_pdf("memo.pdf", replacement, DEFAULT_SESSION_ID)
    failing_commit.assert_called_once()
    assert Path(pdf_storage.pdf_path("memo.pdf")).read_bytes() == original
    current = get_collection().get(workspace_id=DEFAULT_SESSION_ID, filename="memo.pdf", include=["documents", "metadatas", "embeddings"])
    assert current["ids"] == snapshot["ids"]
    assert current["documents"] == snapshot["documents"]
    assert current["metadatas"] == snapshot["metadatas"]
    # Chroma may re-normalize float32 vectors when a snapshot is reinserted.
    np.testing.assert_allclose(current["embeddings"], snapshot["embeddings"], rtol=1e-6, atol=1e-7)
    assert case_store.get_latest_case("memo.pdf", DEFAULT_SESSION_ID)["case_id"] == "original"
    assert not Path(marker_path(DEFAULT_SESSION_ID)).exists()


def test_failed_first_upload_does_not_leave_a_document(sample_pdf_factory, fake_embeddings):
    replacement = Path(sample_pdf_factory()).read_bytes()
    with patch("services.document_publication.pdf_storage.commit_staged_pdf", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            document_publication.publish_pdf("memo.pdf", replacement, DEFAULT_SESSION_ID)
    assert get_collection().get(workspace_id=DEFAULT_SESSION_ID, include=[])["ids"] == []
    assert pdf_storage.pdf_path("memo.pdf") is None


def test_successful_replacement_invalidates_cases_and_removes_temporary_sources(sample_pdf_factory, fake_embeddings):
    _seed(sample_pdf_factory)
    replacement = Path(sample_pdf_factory(sentence="Replacement source text. ")).read_bytes()
    document_publication.publish_pdf("memo.pdf", replacement, DEFAULT_SESSION_ID)
    assert Path(pdf_storage.pdf_path("memo.pdf")).read_bytes() == replacement
    assert case_store.get_latest_case("memo.pdf", DEFAULT_SESSION_ID) is None
    rows = get_collection().get(workspace_id=DEFAULT_SESSION_ID, filename="memo.pdf", include=["documents"])
    assert all("Original" not in text for text in rows["documents"])
    assert not list(Path(pdf_storage.pdf_path("memo.pdf")).parent.glob("*.tmp"))


def test_recovery_backup_cleanup_failure_quarantines_without_false_rollback(sample_pdf_factory, fake_embeddings):
    _seed(sample_pdf_factory)
    replacement = Path(sample_pdf_factory(sentence="Replacement source text. ")).read_bytes()
    original_discard = pdf_storage.discard_staged_pdf

    def fail_backup(path):
        if Path(path).name.startswith(".previous-"):
            raise PermissionError("backup is locked")
        return original_discard(path)

    with patch.object(pdf_storage, "discard_staged_pdf", fail_backup):
        with pytest.raises(WorkspaceUnavailable):
            document_publication.publish_pdf("memo.pdf", replacement, DEFAULT_SESSION_ID)
    assert Path(marker_path(DEFAULT_SESSION_ID)).exists()
    assert Path(pdf_storage.pdf_path("memo.pdf")).read_bytes() == replacement
    assert list(Path(pdf_storage.pdf_path("memo.pdf")).parent.glob(".previous-*.tmp"))


def test_rollback_failure_quarantines_workspace_and_retains_recovery_source(sample_pdf_factory, fake_embeddings):
    original, _ = _seed(sample_pdf_factory)
    replacement = Path(sample_pdf_factory(sentence="Replacement source text. ")).read_bytes()
    with patch("services.document_publication.pdf_storage.commit_staged_pdf", side_effect=OSError("disk full")), \
         patch("services.document_publication.case_store.restore_document_cases", side_effect=OSError("database unavailable")):
        with pytest.raises(WorkspaceUnavailable):
            document_publication.publish_pdf("memo.pdf", replacement, DEFAULT_SESSION_ID)
    assert Path(marker_path(DEFAULT_SESSION_ID)).exists()
    assert Path(pdf_storage.pdf_path("memo.pdf")).read_bytes() == original
    with pytest.raises(WorkspaceUnavailable):
        get_collection().get(workspace_id=DEFAULT_SESSION_ID)
    assert TestClient(main.app).get("/documents").status_code == 503
    assert get_collection().get(workspace_id="unrelated", include=[])["ids"] == []


def test_leftover_marker_blocks_reads_and_new_publications(sample_pdf_factory, fake_embeddings):
    Path(marker_path(DEFAULT_SESSION_ID)).write_text("interrupted", encoding="ascii")
    contents = Path(sample_pdf_factory()).read_bytes()
    with pytest.raises(WorkspaceUnavailable):
        document_publication.publish_pdf("memo.pdf", contents, DEFAULT_SESSION_ID)
    assert Path(marker_path(DEFAULT_SESSION_ID)).read_text() == "interrupted"


def test_same_workspace_read_waits_until_publication_finishes():
    entered = threading.Event()
    done = threading.Event()

    def reader():
        entered.set()
        with workspace_access("owner"):
            done.set()

    with workspace_access("owner"):
        thread = threading.Thread(target=reader)
        thread.start()
        assert entered.wait(1)
        assert not done.wait(0.05)
        with workspace_access("another-owner"):
            pass
    thread.join(2)
    assert done.is_set()


def test_heavy_ingestion_does_not_block_async_health_work(sample_pdf_factory):
    contents = Path(sample_pdf_factory()).read_bytes()
    started = threading.Event()

    def slow(*args):
        started.set()
        time.sleep(0.2)
        return {"filename": "memo.pdf"}

    async def exercise():
        task = asyncio.create_task(document_publication.process_upload(UploadFile(io.BytesIO(contents), filename="memo.pdf"), "owner", 1024 * 1024))
        while not started.is_set():
            await asyncio.sleep(0.001)
        before = time.perf_counter()
        await asyncio.sleep(0.01)
        elapsed = time.perf_counter() - before
        await task
        return elapsed

    with patch.object(document_publication, "publish_pdf", slow):
        assert asyncio.run(exercise()) < 0.12
