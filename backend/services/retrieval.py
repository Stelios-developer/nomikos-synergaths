"""
Hybrid retrieval: vector similarity (ChromaDB) + keyword search (BM25),
merged with Reciprocal Rank Fusion.

Step 5 shipped vector_search only. Step 9 adds keyword_search and
hybrid_search on top without changing vector_search's behavior, so
callers written against step 5 (query.py) keep working — they're
switched over to hybrid_search explicitly.

BM25 has no persistent index: the corpus is pulled fresh from ChromaDB
and re-tokenized on every call. Fine at the scale a portfolio project's
document collection will realistically hit; a real production system
would cache/rebuild the BM25 index on ingestion instead.
"""
import os
import re

from rank_bm25 import BM25Okapi

from db.chroma_client import get_collection
from services.ingestion import _get_openai_client, EMBEDDING_MODEL

DEFAULT_N_RESULTS = int(os.getenv("MAX_CHUNKS_PER_QUERY", 5))
RRF_K = 60


def embed_query(question: str) -> list[float]:
    client = _get_openai_client()
    resp = client.embeddings.create(model=EMBEDDING_MODEL, input=[question])
    return resp.data[0].embedding


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def vector_search(question: str, n_results: int = 10, document_filter: str | None = None) -> list[dict]:
    """
    Returns chunks ranked by vector similarity:
    [{"text", "filename", "page_number", "chunk_index", "distance"}]
    """
    collection = get_collection()
    query_embedding = embed_query(question)

    where = {"filename": document_filter} if document_filter else None
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        where=where,
    )

    chunks = []
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    dists = results["distances"][0]
    for doc, meta, dist in zip(docs, metas, dists):
        chunks.append({
            "text": doc,
            "filename": meta["filename"],
            "page_number": meta["page_number"],
            "chunk_index": meta["chunk_index"],
            "distance": dist,
        })
    return chunks


def keyword_search(question: str, n_results: int = 10, document_filter: str | None = None) -> list[dict]:
    """
    Returns chunks ranked by BM25 score:
    [{"text", "filename", "page_number", "chunk_index", "score"}]
    """
    collection = get_collection()
    where = {"filename": document_filter} if document_filter else None
    corpus = collection.get(where=where, include=["documents", "metadatas"])

    docs = corpus["documents"]
    metas = corpus["metadatas"]
    if not docs:
        return []

    tokenized_corpus = [_tokenize(d) for d in docs]
    bm25 = BM25Okapi(tokenized_corpus)
    scores = bm25.get_scores(_tokenize(question))

    ranked = sorted(zip(docs, metas, scores), key=lambda x: x[2], reverse=True)[:n_results]

    return [{
        "text": doc,
        "filename": meta["filename"],
        "page_number": meta["page_number"],
        "chunk_index": meta["chunk_index"],
        "score": float(score),
    } for doc, meta, score in ranked]


def _chunk_key(chunk: dict) -> tuple:
    return (chunk["filename"], chunk["chunk_index"])


def reciprocal_rank_fusion(
    vector_results: list[dict],
    keyword_results: list[dict],
    k: int = RRF_K,
    n_final: int = DEFAULT_N_RESULTS,
) -> list[dict]:
    """
    score(doc) = sum(1 / (k + rank)) across every ranked list the doc
    appears in (rank is 0-indexed here, matching the common RRF formula
    where the top result contributes 1/(k+1)).
    """
    rrf_scores: dict[tuple, float] = {}
    chunk_by_key: dict[tuple, dict] = {}

    for results in (vector_results, keyword_results):
        for rank, chunk in enumerate(results):
            key = _chunk_key(chunk)
            rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            chunk_by_key.setdefault(key, chunk)

    ranked_keys = sorted(rrf_scores, key=lambda key: rrf_scores[key], reverse=True)
    return [
        {**chunk_by_key[key], "rrf_score": rrf_scores[key]}
        for key in ranked_keys[:n_final]
    ]


def hybrid_search(question: str, document_filter: str | None = None, n_final: int = DEFAULT_N_RESULTS) -> list[dict]:
    vector_results = vector_search(question, n_results=10, document_filter=document_filter)
    keyword_results = keyword_search(question, n_results=10, document_filter=document_filter)
    return reciprocal_rank_fusion(vector_results, keyword_results, n_final=n_final)
