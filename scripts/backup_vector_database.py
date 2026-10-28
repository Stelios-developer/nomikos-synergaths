"""Encrypt a consistent dedicated DMC pg_dump, then restore to a disposable DB.

Never restores over the active DB, writes a plaintext dump or exports credentials.
"""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import uuid

from setup_vector_database import ROOT, local_connections
from services.backup_crypto import seal, restore_bytes
import psycopg
from psycopg import sql

CONTAINER = "dmc-vector-postgres-1"


def fingerprint(conn):
    rows = conn.execute(
        "SELECT workspace_id,chunk_id,filename,document,metadata,embedding::text,content_sha256 FROM dmc.document_chunks ORDER BY workspace_id,chunk_id"
    ).fetchall()
    return len(rows), hashlib.sha256(
        json.dumps(
            rows, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def main():
    label = subprocess.check_output(
        [
            "docker",
            "inspect",
            "--format",
            '{{index .Config.Labels "com.docker.compose.project"}}',
            CONTAINER,
        ],
        text=True,
    ).strip()
    if label != "dmc-vector":
        raise RuntimeError(
            "Refusing a container outside the dedicated DMC vector project"
        )
    owner, _ = local_connections()
    with psycopg.connect(**owner) as conn:
        if conn.execute(
            "SELECT count(*) FROM dmc.analysis_jobs WHERE state IN ('accepted','dispatching','uncertain','cancel_requested')"
        ).fetchone()[0]:
            raise RuntimeError(
                "Review outstanding analyses before this coordinated maintenance backup"
            )
        before = fingerprint(conn)
    target = (
        ROOT
        / "output/security-backups"
        / ("vector-pre-dispatch-" + uuid.uuid4().hex + ".dump.aesgcm")
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        [
            "docker",
            "exec",
            CONTAINER,
            "pg_dump",
            "-U",
            "dmc_owner",
            "-d",
            "dmc",
            "--format=custom",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    def write(output):
        try:
            shutil.copyfileobj(process.stdout, output, 1024 * 1024)
            if process.wait(timeout=60) != 0:
                raise RuntimeError(
                    "Consistent database dump failed; diagnostics withheld"
                )
        finally:
            process.stdout.close()
            if process.poll() is None:
                process.kill()
                process.wait()

    seal(target, write)
    restored = restore_bytes(target)
    listing = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "pg_restore", "--list"],
        input=restored,
        capture_output=True,
        timeout=30,
    )
    if listing.returncode or b"document_chunks" not in listing.stdout:
        raise RuntimeError("Encrypted database archive failed verification")
    database = "dmc_queue_restore_" + uuid.uuid4().hex
    with psycopg.connect(**owner, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        try:
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    "-i",
                    CONTAINER,
                    "pg_restore",
                    "-U",
                    "dmc_owner",
                    "-d",
                    database,
                    "--exit-on-error",
                    "--no-owner",
                ],
                input=restored,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=90,
            )
            if result.returncode:
                raise RuntimeError(
                    "Isolated database restore failed; diagnostics withheld"
                )
            with psycopg.connect(**{**owner, "dbname": database}) as restored_db:
                after = fingerprint(restored_db)
            if before != after:
                raise RuntimeError("Restored vector content does not match its source")
        finally:
            if not database.startswith("dmc_queue_restore_") or len(database) != 50:
                raise RuntimeError("Invalid restore cleanup target")
            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    sql.Identifier(database)
                )
            )
    report = {
        "gate": "PASSED",
        "encrypted_backup": target.relative_to(ROOT).as_posix(),
        "chunks": before[0],
        "content_sha256": before[1],
        "isolated_restore": True,
        "live_database_overwritten": False,
        "plaintext_dump_written": False,
    }
    output = ROOT / "output/engineering-audit/vector-pre-dispatch-backup.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    print(
        "Consistent encrypted PostgreSQL backup and disposable-database restore PASSED; live DB untouched."
    )


if __name__ == "__main__":
    main()
