"""Apply the reviewed queue schema/config only after verified local recovery."""

import argparse
import json
import os
import socket

from setup_vector_database import (
    ROOT,
    local_connections,
    dispatcher_connection,
    ensure_dispatcher_role,
    grant_runtime,
)
from backup_vector_database import fingerprint
from dotenv import dotenv_values, load_dotenv, set_key
import psycopg
from psycopg.conninfo import make_conninfo
from db.migrate import migrate
from db.vector_store import PgVectorStore, VectorSettings
from services.analysis_dispatcher import DispatchClient


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    with socket.socket() as probe:
        probe.settimeout(0.2)
        if probe.connect_ex(("127.0.0.1", 8000)) == 0:
            raise RuntimeError(
                "Stop the local API before applying this maintenance change"
            )
    report = json.loads(
        (ROOT / "output/engineering-audit/vector-pre-dispatch-backup.json").read_text(
            encoding="utf8"
        )
    )
    if report.get("gate") != "PASSED" or not report.get("isolated_restore"):
        raise RuntimeError(
            "A verified encrypted backup and isolated restore are required"
        )
    os.chdir(ROOT / "backend")
    load_dotenv(ROOT / "backend/.env")
    from services.workspace_lock import storage_maintenance

    owner, runtime = local_connections()
    before = dotenv_values(ROOT / "backend/.env")
    with storage_maintenance(resume=args.resume):
        with psycopg.connect(**owner) as conn:
            conn.execute("LOCK TABLE dmc.analysis_jobs IN ACCESS EXCLUSIVE MODE")
            if conn.execute(
                "SELECT count(*) FROM dmc.analysis_jobs WHERE state IN ('accepted','dispatching','uncertain','cancel_requested')"
            ).fetchone()[0]:
                raise RuntimeError(
                    "Review outstanding analyses before changing dispatch configuration"
                )
            count, checksum = fingerprint(conn)
            if checksum != report["content_sha256"] or count != report["chunks"]:
                raise RuntimeError(
                    "The live database changed after the recovery drill; repeat the backup first"
                )
            ensure_dispatcher_role(conn)
            migrate(conn)
            grant_runtime(conn)
        store = PgVectorStore(VectorSettings(make_conninfo(**runtime)))
        try:
            store.verify()
        finally:
            store.close()
        dispatcher_dsn = make_conninfo(**dispatcher_connection())
        DispatchClient(dispatcher_dsn).verify()
        set_key(ROOT / "backend/.env", "ANALYSIS_DISPATCH_DATABASE_URL", dispatcher_dsn)
        set_key(ROOT / "backend/.env", "ANALYSIS_DISPATCH_ENABLED", "true")
        after = dotenv_values(ROOT / "backend/.env")
        changed = {"ANALYSIS_DISPATCH_DATABASE_URL", "ANALYSIS_DISPATCH_ENABLED"}
        if any(
            after.get(key) != value
            for key, value in before.items()
            if key not in changed
        ):
            raise RuntimeError("An unrelated application setting changed")
        with psycopg.connect(**owner) as conn:
            if fingerprint(conn) != (count, checksum):
                raise RuntimeError("Vector data changed during maintenance")
    outcome = {
        "gate": "PASSED",
        "schema": "003_background_analysis.sql",
        "chunks_preserved": count,
        "modified_configuration_keys": sorted(changed),
        "outstanding_jobs": 0,
        "provider_called": False,
        "backup_report": "output/engineering-audit/vector-pre-dispatch-backup.json",
    }
    (ROOT / "output/engineering-audit/dispatcher-activation.json").write_text(
        json.dumps(outcome, indent=2) + "\n", encoding="utf8"
    )
    print(
        "Local queue schema/role verified and enabled; existing vectors/configuration preserved; no provider call."
    )


if __name__ == "__main__":
    main()
