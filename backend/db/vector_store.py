"""Provider-independent, explicitly workspace-scoped document vector storage.

PostgreSQL/pgvector is the only runtime implementation. No dynamic embedding
function, collection configuration or arbitrary filter language is accepted.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import threading

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool


class VectorStoreUnavailable(RuntimeError):
    pass


def workspace(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or "\x00" in value:
        raise ValueError("A verified workspace ID is required")
    return value


def vector(values, dimensions):
    if not isinstance(values, (list, tuple)) or len(values) != dimensions:
        raise ValueError("Embedding dimension does not match the configured model")
    if any(
        isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v)
        for v in values
    ):
        raise ValueError("Embeddings must contain finite numbers")
    try:
        result = list(
            struct.unpack(f"<{dimensions}f", struct.pack(f"<{dimensions}f", *values))
        )
    except (OverflowError, struct.error) as exc:
        raise ValueError("Embedding exceeds float32 range") from exc
    if not all(math.isfinite(v) for v in result) or not any(result):
        raise ValueError("A finite nonzero embedding is required for cosine search")
    return result


def row_digest(chunk_id, document, metadata, embedding):
    payload = json.dumps(
        [chunk_id, document, metadata, embedding],
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def validate_batch(workspace_id, ids, documents, metadatas, embeddings, dimensions):
    workspace(workspace_id)
    if not ids or len(ids) > 100_000 or len(set(ids)) != len(ids):
        raise ValueError("A nonempty batch of unique chunk IDs is required")
    if not len(ids) == len(documents) == len(metadatas) == len(embeddings):
        raise ValueError("Chunk batch lengths differ")
    rows = []
    for chunk_id, document, metadata, embedding in zip(
        ids, documents, metadatas, embeddings
    ):
        if (
            not isinstance(chunk_id, str)
            or not 1 <= len(chunk_id) <= 512
            or "\x00" in chunk_id
        ):
            raise ValueError("Invalid chunk ID")
        if not isinstance(document, str) or not document or "\x00" in document:
            raise ValueError("Invalid chunk text")
        if not isinstance(metadata, dict) or metadata.get("session_id") != workspace_id:
            raise ValueError("Chunk metadata must belong to the verified workspace")
        filename = metadata.get("filename")
        if (
            not isinstance(filename, str)
            or not 1 <= len(filename) <= 255
            or "\x00" in filename
        ):
            raise ValueError("Invalid document filename")
        clean_vector = vector(embedding, dimensions)
        digest = row_digest(chunk_id, document, metadata, clean_vector)
        rows.append(
            (
                workspace_id,
                chunk_id,
                filename,
                document,
                Jsonb(metadata),
                json.dumps(clean_vector),
                digest,
            )
        )
    return rows


@dataclass(frozen=True)
class VectorSettings:
    dsn: str = field(repr=False)
    dimensions: int = 384
    model: str = "all-MiniLM-L6-v2"
    pool_size: int = 4

    @classmethod
    def environment(cls):
        dsn = os.getenv("VECTOR_DATABASE_URL", "")
        if not dsn:
            raise VectorStoreUnavailable("The document database is not configured.")
        return cls(
            dsn,
            int(os.getenv("EMBEDDING_DIMENSIONS", "384")),
            os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
            int(os.getenv("VECTOR_DB_POOL_SIZE", "4")),
        )


class PgVectorStore:
    def __init__(self, settings):
        if not 1 <= settings.dimensions <= 16000 or not 1 <= settings.pool_size <= 16:
            raise ValueError("Invalid vector-store limits")
        self.settings = settings
        self.pool = ConnectionPool(
            settings.dsn,
            min_size=0,
            max_size=settings.pool_size,
            max_waiting=16,
            timeout=5,
            open=False,
            kwargs={"connect_timeout": 5, "application_name": "dmc-vectors"},
            configure=self._configure,
        )
        self.pool.open()

    @staticmethod
    def _configure(conn):
        privileged = conn.execute(
            "SELECT rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb FROM pg_roles WHERE rolname=current_user"
        ).fetchone()[0]
        if privileged:
            raise VectorStoreUnavailable(
                "Document access requires an unprivileged database role."
            )
        conn.execute("SET search_path TO pg_catalog, public")
        conn.execute("SET statement_timeout TO '10s'")
        conn.execute("SET idle_in_transaction_session_timeout TO '15s'")
        conn.commit()

    def close(self):
        self.pool.close()

    def verify(self):
        with self.pool.connection() as conn:
            expected = {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (Path(__file__).parent / "migrations").glob("*.sql")
            }
            applied = dict(
                conn.execute(
                    "SELECT version,sha256 FROM public.dmc_schema_migrations"
                ).fetchall()
            )
            if applied != expected:
                raise VectorStoreUnavailable(
                    "Document database migrations do not match this release."
                )
            config = conn.execute(
                "SELECT dimensions, model FROM dmc.vector_config WHERE singleton"
            ).fetchone()
            if config != (self.settings.dimensions, self.settings.model):
                raise VectorStoreUnavailable(
                    "Document embedding configuration requires a reviewed migration."
                )
            secured = conn.execute(
                "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid='dmc.document_chunks'::regclass"
            ).fetchone()
            unsafe = conn.execute(
                "SELECT has_schema_privilege(current_user,'dmc','CREATE') OR has_schema_privilege(current_user,'public','CREATE') OR has_table_privilege(current_user,'dmc.document_chunks','TRUNCATE')"
            ).fetchone()[0]
            if not secured or not secured[0] or unsafe:
                raise VectorStoreUnavailable(
                    "Document database isolation is not configured safely."
                )
            for table in ['document_chunks','analysis_jobs','analysis_stages','analysis_job_events']:
                policy=conn.execute("SELECT relrowsecurity AND relforcerowsecurity AND relowner<>(SELECT oid FROM pg_roles WHERE rolname=current_user) FROM pg_class WHERE oid=%s::regclass",('dmc.'+table,)).fetchone()
                if not policy or not policy[0]:
                    raise VectorStoreUnavailable('Document/job database isolation is not configured safely.')
            if conn.execute("SELECT has_table_privilege(current_user,'dmc.analysis_job_events','UPDATE') OR has_table_privilege(current_user,'dmc.analysis_job_events','DELETE') OR has_table_privilege(current_user,'dmc.analysis_job_events','TRUNCATE')").fetchone()[0]:
                raise VectorStoreUnavailable('Analysis event history must be append-only.')
            return True

    @contextmanager
    def transaction(self, workspace_id):
        from services.workspace_lock import workspace_access

        workspace(workspace_id)
        with workspace_access(workspace_id), self.pool.connection() as conn:
            with conn.transaction():
                conn.execute(
                    "SELECT set_config('dmc.workspace_id', %s, true)", (workspace_id,)
                )
                yield conn

    @staticmethod
    def _filter(workspace_id, filename, ids):
        workspace(workspace_id)
        clauses, args = ["workspace_id=%s"], [workspace_id]
        if filename is not None:
            if not isinstance(filename, str) or not 1 <= len(filename) <= 255:
                raise ValueError("Invalid filename")
            clauses.append("filename=%s")
            args.append(filename)
        if ids is not None:
            if (
                not isinstance(ids, list)
                or len(ids) > 100_000
                or any(not isinstance(i, str) for i in ids)
            ):
                raise ValueError("Invalid chunk IDs")
            clauses.append("chunk_id=ANY(%s)")
            args.append(ids)
        return " AND ".join(clauses), args

    def get(
        self,
        *,
        workspace_id,
        filename=None,
        ids=None,
        include=None,
        limit=None,
        offset=0,
    ):
        include = ["documents", "metadatas"] if include is None else include
        if set(include) - {"documents", "metadatas", "embeddings"}:
            raise ValueError("Unsupported result field")
        if offset < 0 or limit is not None and not 1 <= limit <= 100_000:
            raise ValueError("Invalid pagination")
        where, args = self._filter(workspace_id, filename, ids)
        selected = [
            (key, column)
            for key, column in (
                ("documents", "document"),
                ("metadatas", "metadata"),
                ("embeddings", "embedding::text"),
            )
            if key in include
        ]
        projection = ",".join(["chunk_id", *[column for _key, column in selected]])
        # Stable ID ordering is shared by exports, rollback snapshots and verification.
        with self.transaction(workspace_id) as conn:
            rows = conn.execute(
                "SELECT "
                + projection
                + " FROM dmc.document_chunks WHERE "
                + where
                + " ORDER BY chunk_id LIMIT %s OFFSET %s",
                [*args, limit, offset],
            ).fetchall()
        result = {"ids": [r[0] for r in rows]}
        result.update({"documents": None, "metadatas": None, "embeddings": None})
        for index, (key, _column) in enumerate(selected, 1):
            result[key] = [
                json.loads(r[index]) if key == "embeddings" else r[index] for r in rows
            ]
        return result

    def add(self, *, workspace_id, ids, documents, metadatas, embeddings):
        rows = validate_batch(
            workspace_id,
            ids,
            documents,
            metadatas,
            embeddings,
            self.settings.dimensions,
        )
        with self.transaction(workspace_id) as conn, conn.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO dmc.document_chunks(workspace_id,chunk_id,filename,document,metadata,embedding,content_sha256) VALUES (%s,%s,%s,%s,%s,%s::vector,%s)",
                rows,
            )

    def delete(self, *, workspace_id, filename=None, ids=None):
        if filename is None and ids is None:
            raise ValueError(
                "Document deletion requires a filename or explicit chunk IDs"
            )
        where, args = self._filter(workspace_id, filename, ids)
        with self.transaction(workspace_id) as conn:
            conn.execute("DELETE FROM dmc.document_chunks WHERE " + where, args)

    def query(self, *, workspace_id, query_embeddings, n_results=10, filename=None):
        if not 1 <= n_results <= 100 or len(query_embeddings) != 1:
            raise ValueError("One bounded vector query is required")
        value = json.dumps(vector(query_embeddings[0], self.settings.dimensions))
        where, args = self._filter(workspace_id, filename, None)
        # Exact search: do not silently sacrifice tenant-filtered recall for HNSW speed.
        with self.transaction(workspace_id) as conn:
            rows = conn.execute(
                "SELECT chunk_id,document,metadata,embedding <=> %s::vector AS distance FROM dmc.document_chunks WHERE "
                + where
                + " ORDER BY distance,chunk_id LIMIT %s",
                [value, *args, n_results],
            ).fetchall()
        return {
            "ids": [[r[0] for r in rows]],
            "documents": [[r[1] for r in rows]],
            "metadatas": [[r[2] for r in rows]],
            "distances": [[r[3] for r in rows]],
        }

    def generation(self, workspace_id, filename):
        with self.transaction(workspace_id) as conn:
            rows = conn.execute(
                "SELECT chunk_id,content_sha256 FROM dmc.document_chunks WHERE workspace_id=%s AND filename=%s ORDER BY chunk_id",
                (workspace_id, filename),
            ).fetchall()
        if not rows:
            raise ValueError("Document not found in your workspace.")
        return hashlib.sha256(
            json.dumps(rows, separators=(",", ":")).encode()
        ).hexdigest()

    def forget_analysis_jobs(self, workspace_id, filename):
        """Erase document job metadata; later callbacks must fail admission."""
        with self.transaction(workspace_id) as conn:
            conn.execute(
                "DELETE FROM dmc.analysis_jobs WHERE workspace_id=%s AND filename=%s",
                (workspace_id, filename),
            )


_collection = None
_lock = threading.RLock()


def get_collection():
    global _collection
    with _lock:
        if _collection is None:
            store = PgVectorStore(VectorSettings.environment())
            try:
                store.verify()
            except Exception:
                store.close()
                raise
            _collection = store
        return _collection


def close_vector_store():
    global _collection
    with _lock:
        if _collection is not None:
            _collection.close()
            _collection = None


def validate_production_vector_store():
    settings = VectorSettings.environment()
    from psycopg.conninfo import conninfo_to_dict

    config = conninfo_to_dict(settings.dsn)
    if config.get("sslmode") != "verify-full":
        raise RuntimeError("Production vector storage requires sslmode=verify-full.")
    if config.get("host") in {None, "localhost", "127.0.0.1"}:
        raise RuntimeError(
            "Production requires a reviewed private vector database host."
        )
    get_collection().verify()
