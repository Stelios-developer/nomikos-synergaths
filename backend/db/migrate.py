"""Checksum-verified SQL migrations. No DDL is executed by API startup."""

import hashlib
from pathlib import Path


def migrate(conn, dimensions=384, model="all-MiniLM-L6-v2"):
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(728405617)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS public.dmc_schema_migrations (version text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        for path in sorted((Path(__file__).parent / "migrations").glob("*.sql")):
            source = path.read_bytes()
            digest = hashlib.sha256(source).hexdigest()
            previous = conn.execute(
                "SELECT sha256 FROM public.dmc_schema_migrations WHERE version=%s",
                (path.name,),
            ).fetchone()
            if previous:
                if previous[0] != digest:
                    raise RuntimeError("An applied database migration was modified")
                continue
            conn.execute(source.decode("utf-8"))
            conn.execute(
                "INSERT INTO public.dmc_schema_migrations(version,sha256) VALUES (%s,%s)",
                (path.name, digest),
            )
        conn.execute(
            "INSERT INTO dmc.vector_config(singleton,dimensions,model) VALUES (true,%s,%s) ON CONFLICT DO NOTHING",
            (dimensions, model),
        )
        if conn.execute(
            "SELECT dimensions,model FROM dmc.vector_config WHERE singleton"
        ).fetchone() != (dimensions, model):
            raise RuntimeError(
                "Embedding model changes require an explicit data migration"
            )
