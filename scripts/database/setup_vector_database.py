"""Initialize only DMC's dedicated local vector database. No legacy data writes."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import dotenv_values
from dotenv import set_key
import secrets
import psycopg
from psycopg import sql
from db.migrate import migrate


def local_connections():
    values = dotenv_values(ROOT / "infra/vector/.env")
    port = int(values.get("DMC_VECTOR_PORT", "5441"))
    if not values.get("POSTGRES_PASSWORD") or not values.get("DMC_DB_PASSWORD"):
        raise RuntimeError("Create the dedicated vector environment first")
    owner = {
        "host": "127.0.0.1",
        "port": port,
        "dbname": "dmc",
        "user": "dmc_owner",
        "password": values["POSTGRES_PASSWORD"],
    }
    runtime = {**owner, "user": "dmc_runtime", "password": values["DMC_DB_PASSWORD"]}
    return owner, runtime


def grant_runtime(conn):
    conn.execute("GRANT USAGE ON SCHEMA dmc TO dmc_runtime")
    conn.execute(
        "GRANT SELECT ON dmc.vector_config, public.dmc_schema_migrations TO dmc_runtime"
    )
    conn.execute(
        "GRANT SELECT,INSERT,UPDATE,DELETE ON dmc.document_chunks TO dmc_runtime"
    )
    conn.execute(
        "GRANT SELECT,INSERT,UPDATE,DELETE ON dmc.analysis_jobs TO dmc_runtime"
    )
    conn.execute(
        "GRANT SELECT,INSERT,UPDATE,DELETE ON dmc.analysis_stages TO dmc_runtime"
    )
    conn.execute("GRANT SELECT,INSERT ON dmc.analysis_job_events TO dmc_runtime")
    conn.execute(
        "GRANT USAGE ON SEQUENCE dmc.analysis_job_events_event_id_seq TO dmc_runtime"
    )
    conn.execute("GRANT USAGE ON SCHEMA dmc TO dmc_dispatcher")
    conn.execute(
        "GRANT EXECUTE ON FUNCTION dmc.dispatch_claim(text,text),dmc.dispatch_heartbeat(text,text,text),dmc.dispatch_observe() TO dmc_dispatcher"
    )


def dispatcher_connection():
    values = dotenv_values(ROOT / "infra/vector/.env")
    if not values.get("DMC_DISPATCH_PASSWORD"):
        raise RuntimeError("Initialize the dedicated dispatcher role first.")
    owner, _ = local_connections()
    return {
        **owner,
        "user": "dmc_dispatcher",
        "password": values["DMC_DISPATCH_PASSWORD"],
    }


def ensure_dispatcher_role(conn):
    path = ROOT / "infra/vector/.env"
    values = dotenv_values(path)
    password = values.get("DMC_DISPATCH_PASSWORD")
    if not password:
        password = secrets.token_urlsafe(48)
        set_key(path, "DMC_DISPATCH_PASSWORD", password)
    existing = conn.execute(
        "SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname='dmc_dispatcher'"
    ).fetchone()
    if existing:
        if any(existing):
            raise RuntimeError("The dispatcher role has excessive privileges.")
    else:
        conn.execute(
            sql.SQL(
                "CREATE ROLE dmc_dispatcher LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD {}"
            ).format(sql.Literal(password))
        )
    conn.execute("ALTER ROLE dmc_dispatcher CONNECTION LIMIT 8")


if __name__ == "__main__":
    owner, _ = local_connections()
    with psycopg.connect(**owner) as conn:
        ensure_dispatcher_role(conn)
        migrate(conn)
        grant_runtime(conn)
    print(
        "Dedicated DMC document schema initialized; runtime role is not an owner or administrator."
    )
