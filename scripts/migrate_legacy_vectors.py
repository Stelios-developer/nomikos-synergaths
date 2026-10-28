"""Offline, backed-up Chroma -> pgvector transfer for this project only.

Chroma is imported only by this one-time operator command. The API never
loads it. No automatic source deletion, account reassignment or overwrite.
"""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
import tarfile
import uuid

from setup_vector_database import ROOT, local_connections
from dotenv import dotenv_values, set_key
from psycopg.conninfo import make_conninfo

settings = dotenv_values(ROOT / "backend/.env")
for name, value in settings.items():
    if value is not None:
        os.environ.setdefault(name, value)

from db.vector_store import PgVectorStore, VectorSettings, row_digest, vector
from services import pdf_storage
from services.backup_crypto import file_sha256, restore_bytes, seal
from services.workspace_lock import storage_maintenance


def project_path(value):
    path = Path(value)
    path = (
        (ROOT / "backend" / path).resolve()
        if not path.is_absolute()
        else path.resolve()
    )
    if not path.is_relative_to(ROOT / "backend") or path.is_symlink():
        raise ValueError("Only this project backend data can be migrated")
    return path


def require_offline():
    with socket.socket() as probe:
        probe.settimeout(1)
        if probe.connect_ex(("127.0.0.1", 8000)) == 0:
            raise RuntimeError(
                "Stop the DMC API on port 8000 before this offline operation"
            )


def read_legacy(source):
    import chromadb
    from chromadb.config import Settings

    client = chromadb.PersistentClient(
        path=str(source),
        settings=Settings(
            chroma_api_impl="chromadb.api.rust.RustBindingsAPI",
            anonymized_telemetry=False,
        ),
    )
    collection = client.get_collection("documents", embedding_function=None)
    rows = collection.get(include=["documents", "metadatas", "embeddings"])
    exported = []
    for key, text, metadata, embedding in zip(
        rows["ids"], rows["documents"], rows["metadatas"], rows["embeddings"]
    ):
        exported.append(
            {
                "id": key,
                "text": text,
                "metadata": metadata,
                "embedding": list(map(float, embedding)),
            }
        )
    client._system.stop()  # one-time pinned legacy reader, not an API dependency
    return sorted(
        exported, key=lambda item: (item["metadata"].get("session_id", ""), item["id"])
    )


def add_bytes(archive, name, value):
    entry = tarfile.TarInfo(name)
    entry.size, entry.mode = len(value), 0o600
    archive.addfile(entry, io.BytesIO(value))


def make_backup(path, rows, source):
    inventory = {}
    data_roots = [source, project_path(pdf_storage.PDF_STORAGE_DIR)]
    sqlite_paths = [
        project_path(settings.get(key) or default)
        for key, default in (
            ("DOCUMENT_CASE_DB_PATH", "document_cases.db"),
            ("EVAL_DB_PATH", "evaluation.db"),
            ("OBSERVABILITY_DB_PATH", "observability.db"),
        )
    ]

    def produce(output):
        with tarfile.open(fileobj=output, mode="w|") as archive:
            export = json.dumps(rows, ensure_ascii=False, allow_nan=False).encode()
            add_bytes(archive, "legacy-vectors.json", export)
            inventory["legacy-vectors.json"] = hashlib.sha256(export).hexdigest()
            for root in data_roots:
                for file in sorted(root.rglob("*")):
                    if file.is_symlink():
                        raise ValueError("Backup refuses symlinks")
                    if (
                        not file.is_file()
                        or file.name.endswith(".lock")
                        or file.name == ".storage-maintenance"
                    ):
                        continue
                    relative = file.relative_to(ROOT).as_posix()
                    inventory[relative] = file_sha256(file)
                    archive.add(file, arcname=relative, recursive=False)
                    if file_sha256(file) != inventory[relative]:
                        raise RuntimeError("Source changed during offline backup")
            for database in sqlite_paths:
                if not database.is_file():
                    continue
                with (
                    sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as origin,
                    sqlite3.connect(":memory:") as snapshot,
                ):
                    origin.backup(snapshot)
                    if snapshot.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise RuntimeError("SQLite snapshot integrity failed")
                    value = snapshot.serialize()
                relative = database.relative_to(ROOT).as_posix()
                add_bytes(archive, relative, value)
                inventory[relative] = hashlib.sha256(value).hexdigest()
            add_bytes(
                archive, "manifest.json", json.dumps(inventory, sort_keys=True).encode()
            )

    encryption = seal(path, produce)
    # Fully decrypt, validate every member checksum and reparse the export before activation.
    with tarfile.open(fileobj=io.BytesIO(restore_bytes(path)), mode="r:") as archive:
        actual = {}
        for entry in archive.getmembers():
            if (
                not entry.isfile()
                or entry.name.startswith("/")
                or ".." in Path(entry.name).parts
            ):
                raise ValueError("Unexpected backup member")
            if entry.name != "manifest.json":
                actual[entry.name] = hashlib.sha256(
                    archive.extractfile(entry).read()
                ).hexdigest()
        saved = json.load(archive.extractfile("manifest.json"))
        if (
            saved != actual
            or json.load(archive.extractfile("legacy-vectors.json")) != rows
        ):
            raise RuntimeError("Backup restore verification mismatch")
    return {
        **encryption,
        "members_verified": len(inventory),
        "key_protection": "Windows current-user DPAPI",
    }


def digest_rows(rows, dimensions):
    digests = [
        row_digest(
            row["id"],
            row["text"],
            row["metadata"],
            vector(row["embedding"], dimensions),
        )
        for row in rows
    ]
    return hashlib.sha256("".join(sorted(digests)).encode()).hexdigest()


def migrate():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--quarantine-unowned", action="store_true")
    args = parser.parse_args()
    source = project_path(settings.get("CHROMA_PERSIST_DIR") or "chroma_db")
    if not (source / "chroma.sqlite3").is_file():
        raise RuntimeError("Legacy source was not found; nothing was changed")
    if args.apply:
        from importlib.util import find_spec

        if find_spec("chromadb") is None:
            raise RuntimeError(
                "The one-time legacy reader has been removed. Use the verified encrypted backup and restore drill; do not reinstall it in the API environment."
            )
    require_offline()
    _, runtime = local_connections()
    dimensions = int(settings.get("EMBEDDING_DIMENSIONS") or 384)
    store = PgVectorStore(
        VectorSettings(
            make_conninfo(**runtime),
            dimensions,
            settings.get("EMBEDDING_MODEL") or "all-MiniLM-L6-v2",
        )
    )
    try:
        store.verify()
        if not args.apply:
            print(
                "Plan: encrypted verified backup, exact workspace transfer, row/hash verification, then local configuration activation. Source retained."
            )
            return
        run_id = uuid.uuid4().hex
        destination = (
            ROOT / "output/security-backups" / ("storage-" + run_id + ".tar.aesgcm")
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        with storage_maintenance(resume=args.resume):
            require_offline()
            rows = read_legacy(source)
            grouped = defaultdict(list)
            quarantined = []
            for row in rows:
                owner = row["metadata"].get("session_id")
                if not owner:
                    if not args.quarantine_unowned:
                        raise RuntimeError(
                            "Legacy data has no verified owner; explicit operator mapping or encrypted quarantine is required"
                        )
                    quarantined.append(row)
                    continue
                grouped[owner].append(row)
            backup = make_backup(destination, rows, source)
            for owner, chunks in grouped.items():
                if store.get(workspace_id=owner, include=[])["ids"]:
                    raise RuntimeError(
                        "Destination workspace is nonempty; refusing to overwrite it"
                    )
                store.add(
                    workspace_id=owner,
                    ids=[r["id"] for r in chunks],
                    documents=[r["text"] for r in chunks],
                    metadatas=[r["metadata"] for r in chunks],
                    embeddings=[r["embedding"] for r in chunks],
                )
                result = store.get(
                    workspace_id=owner, include=["documents", "metadatas", "embeddings"]
                )
                restored = [
                    {
                        "id": key,
                        "text": text,
                        "metadata": metadata,
                        "embedding": embedding,
                    }
                    for key, text, metadata, embedding in zip(
                        result["ids"],
                        result["documents"],
                        result["metadatas"],
                        result["embeddings"],
                    )
                ]
                if len(restored) != len(chunks) or digest_rows(
                    restored, dimensions
                ) != digest_rows(chunks, dimensions):
                    raise RuntimeError(
                        "Target verification failed; maintenance remains active"
                    )
            # Update only server-side local configuration after all recovery/data checks passed.
            set_key(
                str(ROOT / "backend/.env"),
                "VECTOR_DATABASE_URL",
                make_conninfo(**runtime),
            )
            set_key(str(ROOT / "backend/.env"), "EMBEDDING_DIMENSIONS", str(dimensions))
            report = {
                "schema_version": 1,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "gate": "PASSED",
                "source_retained": True,
                "workspaces": len(grouped),
                "source_chunks": len(rows),
                "chunks": len(rows) - len(quarantined),
                "quarantined_chunks": len(quarantined),
                "source_content_sha256": digest_rows(rows, dimensions),
                "migrated_content_sha256": digest_rows(
                    [r for r in rows if r["metadata"].get("session_id")], dimensions
                ),
                "backup": backup,
                "encrypted_backup": destination.relative_to(ROOT).as_posix(),
            }
            report_path = ROOT / "output/engineering-audit/vector-migration.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )
            print(
                f"Verified migration: {len(rows) - len(quarantined)} chunks in {len(grouped)} workspaces; {len(quarantined)} unowned chunks retained only in recovery data; encrypted backup restored and verified; source retained."
            )
    finally:
        store.close()


if __name__ == "__main__":
    migrate()
