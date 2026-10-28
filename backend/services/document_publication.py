"""Publish a prepared PDF/index/case generation with rollback and fail-closed recovery.

These stores do not support a shared ACID transaction. Workspace locks hide
intermediate states; a durable marker quarantines interrupted/failed rollbacks.
"""
import asyncio
import json
import os
import shutil
import tempfile

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from db.vector_store import get_collection
from services import case_store, pdf_storage
from services.ingestion import ingest_pdf, prepare_pdf
from services.pdf_upload import PdfUploadError, enforce_workspace_capacity, read_validated_pdf
from services.workspace_lock import WorkspaceUnavailable, publication_scope, workspace_access

_upload_slots = asyncio.Semaphore(2)


def _sync_directory(path):
    # POSIX requires a directory fsync for durable rename/create metadata.
    # Windows lacks a portable equivalent; this is not power-loss proof.
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def publish_pdf(filename, contents, workspace_id):
    staged = pdf_storage.stage_pdf(filename, contents, workspace_id)
    backup = None
    keep_backup = False
    marker = None
    try:
        prepared = prepare_pdf(staged)
        with workspace_access(workspace_id):
            enforce_workspace_capacity(filename, len(contents), workspace_id)
            collection = get_collection()
            previous = collection.get(workspace_id=workspace_id, filename=filename, include=["documents", "metadatas", "embeddings"])
            cases = case_store.snapshot_document_cases(filename, workspace_id)
            destination = pdf_storage._safe_path(filename, workspace_id)
            if os.path.exists(destination):
                fd, backup = tempfile.mkstemp(prefix=".previous-", suffix=".tmp", dir=os.path.dirname(destination))
                os.close(fd)
                shutil.copyfile(destination, backup)
                with open(backup, "r+b") as source:
                    os.fsync(source.fileno())
            with publication_scope(workspace_id) as marker:
                # Never clear an existing interrupted-publication marker here.
                with open(marker, "x", encoding="ascii") as pending:
                    json.dump({"version": 1, "destination": os.path.basename(destination),
                               "previous_source": os.path.basename(backup) if backup else None,
                               "staged_source": os.path.basename(staged)}, pending)
                    pending.flush()
                    os.fsync(pending.fileno())
                _sync_directory(os.path.dirname(marker))
                try:
                    result = ingest_pdf(staged, filename, session_id=workspace_id, prepared=prepared)
                    pdf_storage.commit_staged_pdf(filename, staged, workspace_id)
                    case_store.delete_cases_for_document(filename, workspace_id)
                    _sync_directory(os.path.dirname(marker))
                    os.unlink(marker)
                except Exception as original:
                    try:
                        collection.delete(workspace_id=workspace_id, filename=filename)
                        if previous["ids"]:
                            collection.add(workspace_id=workspace_id, ids=previous["ids"], documents=previous["documents"],
                                           metadatas=previous["metadatas"], embeddings=previous["embeddings"])
                        if backup:
                            os.replace(backup, destination)
                            backup = None
                        else:
                            pdf_storage.delete_pdf(filename, workspace_id)
                        case_store.restore_document_cases(filename, workspace_id, cases)
                        _sync_directory(os.path.dirname(marker))
                        os.unlink(marker)
                    except Exception as rollback:
                        keep_backup = True
                        raise WorkspaceUnavailable("Document recovery is required before this workspace can be used.") from rollback
                    raise original
                # After the logical commit, cleanup must not report a false
                # "failed replacement" or try to roll back without a backup.
                if backup:
                    try:
                        pdf_storage.discard_staged_pdf(backup)
                        backup = None
                    except OSError as cleanup:
                        keep_backup = True
                        with open(marker, "x", encoding="ascii") as pending:
                            json.dump({"version": 1, "destination": os.path.basename(destination),
                                       "previous_source": os.path.basename(backup), "cleanup_required": True}, pending)
                            pending.flush()
                            os.fsync(pending.fileno())
                        _sync_directory(os.path.dirname(marker))
                        raise WorkspaceUnavailable("Document recovery is required before this workspace can be used.") from cleanup
                return result
    finally:
        pending = marker is not None and os.path.exists(marker)
        if not pending:
            pdf_storage.discard_staged_pdf(staged)
        if backup and not keep_backup and not pending:
            pdf_storage.discard_staged_pdf(backup)


async def process_upload(file, workspace_id, max_bytes):
    if _upload_slots.locked():
        raise HTTPException(429, "PDF processing is busy. Retry shortly.")
    async with _upload_slots:
        try:
            filename, contents, _ = await read_validated_pdf(file, max_bytes)
            # Shielded threadpool execution finishes cleanup even if the client
            # disconnects. OCR, embeddings and filesystem I/O never block ASGI.
            return await run_in_threadpool(publish_pdf, filename, contents, workspace_id)
        except PdfUploadError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
        except WorkspaceUnavailable:
            raise
        except Exception as exc:
            raise HTTPException(400, "Could not process PDF.") from exc
