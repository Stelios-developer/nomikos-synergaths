import math
import pytest

from db import vector_store as store


def test_vector_settings_do_not_expose_database_credentials():
    assert 'private-password' not in repr(store.VectorSettings('postgresql://user:private-password@db/dmc'))


def test_missing_database_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv('VECTOR_DATABASE_URL', raising=False)
    with pytest.raises(store.VectorStoreUnavailable):
        store.VectorSettings.environment()


@pytest.mark.parametrize('values', [[0,0,0], [1,math.nan,0], [1,math.inf,0], [True,0,0], [1], [1e100,0,0]])
def test_invalid_embeddings_are_rejected(values):
    with pytest.raises(ValueError):
        store.vector(values,3)


def test_metadata_cannot_select_a_different_workspace():
    with pytest.raises(ValueError, match='verified workspace'):
        store.validate_batch('alice', ['1'], ['source'], [{'filename':'a.pdf','session_id':'bob'}], [[1,0,0]],3)


def test_both_read_and_write_contracts_require_explicit_workspace():
    instance=object.__new__(store.PgVectorStore)
    for method in (instance.get, instance.query, instance.add, instance.delete):
        with pytest.raises(TypeError):
            method()


def test_production_refuses_unverified_database_tls(monkeypatch):
    monkeypatch.setenv('VECTOR_DATABASE_URL','postgresql://local:synthetic@localhost/test')
    with pytest.raises(RuntimeError, match='verify-full'):
        store.validate_production_vector_store()
