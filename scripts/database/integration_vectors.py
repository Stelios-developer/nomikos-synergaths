"""Run real PostgreSQL tests in a unique disposable database, never the live DB."""

import os
from pathlib import Path
import subprocess
import sys
import uuid

from setup_vector_database import (
    ROOT,
    grant_runtime,
    local_connections,
    ensure_dispatcher_role,
    dispatcher_connection,
)
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from db.migrate import migrate


def main():
    owner, runtime = local_connections()
    name = "dmc_it_" + uuid.uuid4().hex
    with psycopg.connect(**owner, autocommit=True) as admin:
        ensure_dispatcher_role(admin)
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            test_owner, test_runtime = (
                {**owner, "dbname": name},
                {**runtime, "dbname": name},
            )
            with psycopg.connect(**test_owner) as conn:
                migrate(conn, dimensions=3, model="synthetic-integration")
                grant_runtime(conn)
            environment = {
                **os.environ,
                "DMC_TEST_VECTOR_URL": make_conninfo(**test_runtime),
                "DMC_TEST_VECTOR_ADMIN_URL": make_conninfo(**test_owner),
                "DMC_TEST_DISPATCH_URL": make_conninfo(
                    **{**dispatcher_connection(), "dbname": name}
                ),
            }
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "integration_tests",
                    "-q",
                    "--tb=short",
                ],
                cwd=ROOT / "backend",
                env=environment,
            )
            return result.returncode
        finally:
            # Exact, freshly generated database only. Existing databases/volumes are never dropped.
            if not name.startswith("dmc_it_") or len(name) != 39:
                raise RuntimeError("Invalid test database cleanup target")
            admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )


if __name__ == "__main__":
    raise SystemExit(main())
