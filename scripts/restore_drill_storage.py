"""Verify encrypted storage recovery into a disposable PostgreSQL database.

No extraction into live PDF paths and no replacement of the current database.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile
import uuid

from setup_vector_database import ROOT, grant_runtime, local_connections
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from db.migrate import migrate
from db.vector_store import PgVectorStore, VectorSettings, row_digest, vector
from services.backup_crypto import restore_bytes


def verified_archive(path):
    if not path.resolve().is_relative_to(ROOT / "output/security-backups"):
        raise ValueError("Use an exact DMC backup inside the ignored backup directory")
    archive = tarfile.open(fileobj=io.BytesIO(restore_bytes(path)), mode="r:")
    manifest = json.load(archive.extractfile("manifest.json"))
    actual = {}
    for entry in archive.getmembers():
        if (
            not entry.isfile()
            or entry.name.startswith("/")
            or ".." in Path(entry.name).parts
        ):
            raise ValueError("Unexpected recovery archive member")
        if entry.name != "manifest.json":
            actual[entry.name] = hashlib.sha256(
                archive.extractfile(entry).read()
            ).hexdigest()
    if manifest != actual:
        raise RuntimeError("Backup checksum mismatch")
    return archive


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("backup", type=Path)
    args = parser.parse_args()
    with verified_archive(args.backup) as archive:
        rows = json.load(archive.extractfile("legacy-vectors.json"))
        manifest_count = len(json.load(archive.extractfile("manifest.json")))
        # SQLite pages are validated in memory; raw legacy Chroma is not opened.
        import sqlite3

        sqlite_verified = 0
        for entry in archive.getmembers():
            if entry.name.endswith(".db"):
                with sqlite3.connect(":memory:") as conn:
                    conn.deserialize(archive.extractfile(entry).read())
                    if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise RuntimeError(
                            "Recovered SQLite data failed integrity checking"
                        )
                    sqlite_verified += 1
    grouped = {}
    for row in rows:
        if row["metadata"].get("session_id"):
            grouped.setdefault(row["metadata"]["session_id"], []).append(row)
    owner, runtime = local_connections()
    name = "dmc_restore_" + uuid.uuid4().hex
    store = None
    with psycopg.connect(**owner, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            with psycopg.connect(**{**owner, "dbname": name}) as conn:
                migrate(conn)
                grant_runtime(conn)
            store = PgVectorStore(
                VectorSettings(make_conninfo(**{**runtime, "dbname": name}))
            )
            store.verify()
            restored = 0
            for workspace_id, chunks in grouped.items():
                store.add(
                    workspace_id=workspace_id,
                    ids=[r["id"] for r in chunks],
                    documents=[r["text"] for r in chunks],
                    metadatas=[r["metadata"] for r in chunks],
                    embeddings=[r["embedding"] for r in chunks],
                )
                values = store.get(
                    workspace_id=workspace_id,
                    include=["documents", "metadatas", "embeddings"],
                )
                expected = sorted(
                    row_digest(
                        r["id"], r["text"], r["metadata"], vector(r["embedding"], 384)
                    )
                    for r in chunks
                )
                actual = sorted(
                    row_digest(key, text, metadata, vector(embedding, 384))
                    for key, text, metadata, embedding in zip(
                        values["ids"],
                        values["documents"],
                        values["metadatas"],
                        values["embeddings"],
                    )
                )
                if expected != actual:
                    raise RuntimeError(
                        "Recovered vector content differs from the backup"
                    )
                restored += len(chunks)
            report = {
                "gate": "PASSED",
                "chunks_restored": restored,
                "quarantined_chunks": len(rows) - restored,
                "members_verified": manifest_count,
                "sqlite_integrity_checks": sqlite_verified,
                "live_database_changed": False,
                "live_pdf_paths_written": False,
            }
        finally:
            if store:
                store.close()
            if not re.fullmatch(r"dmc_restore_[0-9a-f]{32}", name):
                raise RuntimeError("Unsafe test database cleanup target")
            admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )
    target = ROOT / "output/engineering-audit/storage-restore.json"
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
