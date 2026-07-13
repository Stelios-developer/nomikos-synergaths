"""
ChromaDB singleton connection.

Everything lives in one persistent local client and one collection
("documents"). Individual PDFs are distinguished purely via the
`filename` field in each chunk's metadata, not via separate collections.
"""
import os
import chromadb

_client = None
_collection = None

CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./chroma_db")
COLLECTION_NAME = "documents"


def get_chroma_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    return _client


def get_collection():
    """Returns the singleton 'documents' collection, creating it if needed."""
    global _collection
    if _collection is None:
        client = get_chroma_client()
        _collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection
