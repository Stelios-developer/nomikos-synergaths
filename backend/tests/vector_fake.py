"""Memory-only test double. Real SQL/RLS/transaction tests use PostgreSQL."""
import copy
from math import sqrt
from contextlib import contextmanager

from db.vector_store import validate_batch, workspace
from services.workspace_lock import workspace_access


class MemoryVectors:
    def forget_analysis_jobs(self, workspace_id, filename):
        # Durable-job behavior is verified against real SQL in integration_tests.
        pass
    def __init__(self):
        self.rows = {}

    def close(self):
        pass

    def verify(self):
        return True

    @contextmanager
    def transaction(self, workspace_id):
        with workspace_access(workspace(workspace_id)):
            yield

    def get(self, *, workspace_id, filename=None, ids=None, include=None, limit=None, offset=0):
        with self.transaction(workspace_id):
            rows = [(key[1], row) for key, row in sorted(self.rows.items()) if key[0] == workspace_id
                    and (filename is None or row[1]['filename'] == filename) and (ids is None or key[1] in ids)]
            rows = rows[offset:offset+limit if limit is not None else None]
            include = ['documents', 'metadatas'] if include is None else include
            return {'ids': [r[0] for r in rows],
                    **{key: [copy.deepcopy(r[1][index]) for r in rows] if key in include else None
                       for key, index in [('documents', 0), ('metadatas', 1), ('embeddings', 2)]}}

    def add(self, *, workspace_id, ids, documents, metadatas, embeddings):
        validate_batch(workspace_id, ids, documents, metadatas, embeddings, len(embeddings[0]))
        with self.transaction(workspace_id):
            if any((workspace_id, key) in self.rows for key in ids):
                raise ValueError('Duplicate chunk')
            for key, document, metadata, embedding in zip(ids, documents, metadatas, embeddings):
                self.rows[(workspace_id, key)] = copy.deepcopy((document, metadata, embedding))

    def delete(self, *, workspace_id, filename=None, ids=None):
        if filename is None and ids is None:
            raise ValueError('Explicit deletion selector required')
        with self.transaction(workspace_id):
            keys = self.get(workspace_id=workspace_id, filename=filename, ids=ids, include=[])['ids']
            for key in keys:
                del self.rows[(workspace_id, key)]

    def query(self, *, workspace_id, query_embeddings, n_results=10, filename=None):
        values = self.get(workspace_id=workspace_id, filename=filename, include=['documents','metadatas','embeddings'])
        query = query_embeddings[0]
        ranked = sorted(zip(values['ids'], values['documents'], values['metadatas'], values['embeddings']),
                        key=lambda r: 1-sum(a*b for a,b in zip(query,r[3]))/(sqrt(sum(v*v for v in query))*sqrt(sum(v*v for v in r[3]))))[:n_results]
        return {'ids': [[r[0] for r in ranked]], 'documents': [[r[1] for r in ranked]],
                'metadatas': [[r[2] for r in ranked]],
                'distances': [[1-sum(a*b for a,b in zip(query,r[3]))/(sqrt(sum(v*v for v in query))*sqrt(sum(v*v for v in r[3]))) for r in ranked]]}
