"""Real SQL, RLS, transaction rollback, pool cleanup and migration invariants."""

import os

import psycopg
import pytest

from db.migrate import migrate
from db.vector_store import PgVectorStore, VectorSettings


@pytest.fixture
def store():
    dsn = os.getenv("DMC_TEST_VECTOR_URL")
    if not dsn:
        pytest.skip("Run scripts/database/integration_vectors.py to create an isolated database")
    instance = PgVectorStore(VectorSettings(dsn, 3, "synthetic-integration"))
    instance.verify()
    yield instance
    instance.close()
    with psycopg.connect(os.environ["DMC_TEST_VECTOR_ADMIN_URL"]) as conn:
        conn.execute("DELETE FROM dmc.analysis_jobs")
        conn.execute("DELETE FROM dmc.document_chunks")


def add(store, owner="alice", ids=None, vectors=None):
    ids = ids or ["same-id"]
    store.add(
        workspace_id=owner,
        ids=ids,
        documents=["Private " + owner] * len(ids),
        metadatas=[
            {"filename": "memo.pdf", "session_id": owner, "page_number": 1} for _ in ids
        ],
        embeddings=vectors or [[1, 0, 0]] * len(ids),
    )


def test_same_chunk_id_is_isolated_by_workspace(store):
    add(store)
    add(store, "bob")
    assert store.get(workspace_id="alice")["documents"] == ["Private alice"]
    assert store.get(workspace_id="bob")["documents"] == ["Private bob"]
    store.delete(workspace_id="alice", ids=["same-id"])
    assert store.get(workspace_id="alice")["ids"] == []
    assert store.get(workspace_id="bob")["ids"] == ["same-id"]


def test_cosine_ranking_is_exact_and_deterministic(store):
    add(store, ids=["a", "b", "c"], vectors=[[1, 0, 0], [0, 1, 0], [0.5, 0.5, 0]])
    add(store, "bob")
    result = store.query(
        workspace_id="alice", query_embeddings=[[1, 0, 0]], n_results=10
    )
    assert result["ids"] == [["a", "c", "b"]]
    assert result["distances"][0] == sorted(result["distances"][0])
    assert store.query(
        workspace_id="alice", filename="missing.pdf", query_embeddings=[[1, 0, 0]]
    )["ids"] == [[]]


def test_rls_blocks_raw_queries_without_and_with_foreign_context(store):
    add(store)
    with psycopg.connect(os.environ["DMC_TEST_VECTOR_URL"]) as conn:
        assert (
            conn.execute("SELECT count(*) FROM dmc.document_chunks").fetchone()[0] == 0
        )
        conn.execute("SELECT set_config('dmc.workspace_id','bob',true)")
        assert (
            conn.execute(
                "SELECT count(*) FROM dmc.document_chunks WHERE workspace_id=%s",
                ("alice",),
            ).fetchone()[0]
            == 0
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("TRUNCATE dmc.document_chunks")


def test_rls_rejects_foreign_write_even_below_adapter(store):
    with psycopg.connect(os.environ["DMC_TEST_VECTOR_URL"]) as conn:
        conn.execute("SELECT set_config('dmc.workspace_id','bob',true)")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "INSERT INTO dmc.document_chunks VALUES ('alice','x','a.pdf','source','{\"session_id\":\"alice\",\"filename\":\"a.pdf\"}','[1,0,0]',%s)",
                ("0" * 64,),
            )


def test_failed_batch_rolls_back_every_row(store):
    add(store)
    with pytest.raises(psycopg.errors.UniqueViolation):
        add(store, ids=["new-id", "same-id"])
    assert store.get(workspace_id="alice")["ids"] == ["same-id"]


def test_scope_does_not_leak_after_pool_return_or_exception(store):
    add(store)
    add(store, "bob")
    with pytest.raises(RuntimeError):
        with store.transaction("alice") as conn:
            assert (
                conn.execute("SELECT count(*) FROM dmc.document_chunks").fetchone()[0]
                == 1
            )
            raise RuntimeError("synthetic fault")
    with store.pool.connection() as conn:
        assert (
            conn.execute("SELECT count(*) FROM dmc.document_chunks").fetchone()[0] == 0
        )
    assert store.get(workspace_id="bob")["documents"] == ["Private bob"]


def test_concurrent_workspaces_do_not_share_connection_context(store):
    add(store)
    add(store, "bob")
    from concurrent.futures import ThreadPoolExecutor

    def read(owner):
        return store.get(workspace_id=owner)["documents"] == ["Private " + owner]

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all(pool.map(read, ["alice", "bob"] * 20))


def test_sql_values_cannot_change_query_structure(store):
    owner = "alice' OR '1'='1"
    add(store, owner)
    assert store.get(workspace_id="alice")["ids"] == []
    assert store.get(workspace_id=owner)["documents"] == ["Private " + owner]


def test_runtime_cannot_change_schema_or_embedding_configuration(store):
    for command in (
        "ALTER TABLE dmc.document_chunks DISABLE ROW LEVEL SECURITY",
        "UPDATE dmc.vector_config SET dimensions=8",
        "CREATE TABLE dmc.untrusted(x int)",
    ):
        with psycopg.connect(os.environ["DMC_TEST_VECTOR_URL"]) as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(command)


def test_migration_is_repeatable_and_rejects_model_drift(store):
    with psycopg.connect(os.environ["DMC_TEST_VECTOR_ADMIN_URL"]) as conn:
        migrate(conn, 3, "synthetic-integration")
    with psycopg.connect(os.environ["DMC_TEST_VECTOR_ADMIN_URL"]) as conn:
        with pytest.raises(RuntimeError, match="data migration"):
            migrate(conn, 4, "changed-model")


def test_database_rejects_wrong_dimensions_below_adapter(store):
    with psycopg.connect(os.environ["DMC_TEST_VECTOR_URL"]) as conn:
        conn.execute("SELECT set_config('dmc.workspace_id','alice',true)")
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute(
                "INSERT INTO dmc.document_chunks VALUES ('alice','x','a.pdf','source','{\"session_id\":\"alice\",\"filename\":\"a.pdf\"}','[1,0]',%s)",
                ("0" * 64,),
            )


def test_store_survives_new_connection_with_identical_data(store):
    add(store)
    snapshot = store.get(
        workspace_id="alice", include=["documents", "metadatas", "embeddings"]
    )
    other = PgVectorStore(store.settings)
    try:
        assert (
            other.get(
                workspace_id="alice", include=["documents", "metadatas", "embeddings"]
            )
            == snapshot
        )
    finally:
        other.close()
