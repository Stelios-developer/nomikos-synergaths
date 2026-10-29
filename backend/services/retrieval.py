"""
Hybrid retrieval: vector similarity (PostgreSQL/pgvector) + keyword search (BM25),
merged with Reciprocal Rank Fusion.

Step 5 shipped vector_search only. Step 9 adds keyword_search and
hybrid_search on top without changing vector_search's behavior, so
callers written against step 5 (query.py) keep working — they're
switched over to hybrid_search explicitly.

BM25 has no persistent index: the corpus is pulled fresh from PostgreSQL/pgvector
and re-tokenized on every call. Fine at the scale a portfolio project's
document collection will realistically hit; a real production system
would cache/rebuild the BM25 index on ingestion instead.

Every search function is scoped by session_id (services/session_scope.py)
so one visitor's retrieval can never surface another visitor's uploaded
chunks — both the vector query AND the BM25 corpus pull apply the same
where-filter, since BM25 rebuilds its corpus straight from PostgreSQL/pgvector on
every call and would otherwise leak cross-session content through the
keyword-search half even if the vector half were filtered correctly.
"""
import os
import re
import unicodedata

from rank_bm25 import BM25Okapi

from db.vector_store import get_collection
from services.embeddings import embed_text
from services.session_scope import DEFAULT_SESSION_ID
from services.workspace_lock import scoped_operation

DEFAULT_N_RESULTS = int(os.getenv("MAX_CHUNKS_PER_QUERY", 5))
RRF_K = 60


def embed_query(question: str) -> list[float]:
    return embed_text(question)


def _tokenize(text: str) -> list[str]:
    # Accent-insensitive matching helps Greek queries without altering evidence.
    normalized = unicodedata.normalize("NFKD", text.casefold())
    return re.findall(r"\w+", "".join(c for c in normalized if not unicodedata.combining(c)))


# Narrow query-only bridges. This is not machine translation and must never
# change source text or be treated as a comprehensive domain vocabulary.
_CROSS_LANGUAGE_TERMS = (
    (("κινδυν", "risk", "risks", "hazard"), ("risk", "risks", "penalty", "exposure", "mitigation")),
    (("ενεργει", "μετρ", "action", "actions", "mitigation"), ("action", "actions", "mitigation", "review", "escalation")),
    (("προθεσμ", "ημερομην", "deadline", "deadlines"), ("deadline", "deadlines", "due", "filing", "date")),
    (("υπευθυν", "αρμοδι", "responsible", "owner"), ("owner", "responsible", "manager", "director", "controller")),
    (("υποχρεωσ", "απαιτησ", "obligation", "requirement"), ("obligation", "requirements", "required", "must", "shall")),
    (("εγκρισ", "αποφασ", "approval", "decision"), ("approval", "approve", "decision", "review")),
    (("επισκοπ", "διοικητικ", "review", "management"), ("review", "management", "director")),
    (("συμφωνι", "συμφιλιωσ", "reconciliation", "reconcile"), ("reconciliation", "reconcile", "agreement", "review")),
)


def _query_tokens(question: str) -> list[str]:
    tokens = _tokenize(question)
    expanded = list(tokens)
    for prefixes, aliases in _CROSS_LANGUAGE_TERMS:
        if any(token.startswith(prefix) for token in tokens for prefix in prefixes):
            expanded.extend(aliases)
    return list(dict.fromkeys(expanded))


def vector_search(
    question: str,
    n_results: int = 10,
    document_filter: str | None = None,
    session_id: str = DEFAULT_SESSION_ID,
) -> list[dict]:
    """
    Returns chunks ranked by vector similarity:
    [{"text", "filename", "page_number", "chunk_index", "distance"}]
    """
    collection = get_collection()
    query_embedding = embed_query(question)

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        workspace_id=session_id, filename=document_filter,
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


def keyword_search(
    question: str,
    n_results: int = 10,
    document_filter: str | None = None,
    session_id: str = DEFAULT_SESSION_ID,
) -> list[dict]:
    """
    Returns chunks ranked by BM25 score:
    [{"text", "filename", "page_number", "chunk_index", "score"}]
    """
    collection = get_collection()
    corpus = collection.get(workspace_id=session_id, filename=document_filter, include=["documents", "metadatas"])

    docs = corpus["documents"]
    metas = corpus["metadatas"]
    if not docs:
        return []

    tokenized_corpus = [_tokenize(d) for d in docs]
    bm25 = BM25Okapi(tokenized_corpus)
    query_tokens = _query_tokens(question)
    scores = bm25.get_scores(query_tokens)

    # Do not give non-matching documents an artificial keyword rank. BM25 can
    # legitimately produce zero/negative scores for common terms, so require
    # token overlap rather than a positive score.
    query_set = set(query_tokens)
    matches = ((doc, meta, score) for doc, meta, score, tokens in zip(docs, metas, scores, tokenized_corpus)
               if query_set.intersection(tokens))
    ranked = sorted(matches, key=lambda x: x[2], reverse=True)[:n_results]

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


@scoped_operation
def hybrid_search(
    question: str,
    document_filter: str | None = None,
    n_final: int = DEFAULT_N_RESULTS,
    session_id: str = DEFAULT_SESSION_ID,
) -> list[dict]:
    vector_results = vector_search(question, n_results=10, document_filter=document_filter, session_id=session_id)
    keyword_results = keyword_search(question, n_results=10, document_filter=document_filter, session_id=session_id)
    fused = reciprocal_rank_fusion(vector_results, keyword_results, n_final=n_final)
    # Preserve up to two lexical candidates. Cross-language vector embeddings
    # can otherwise push a relevant keyword match just outside the final set.
    # Every candidate has already been restricted to the same workspace/file.
    reserved = {_chunk_key(c) for c in keyword_results[:min(2, n_final)]}
    selected = {_chunk_key(c) for c in fused}
    for candidate in keyword_results[:min(2, n_final)]:
        key = _chunk_key(candidate)
        if key in selected:
            continue
        for index in range(len(fused) - 1, -1, -1):
            if _chunk_key(fused[index]) not in reserved:
                selected.remove(_chunk_key(fused[index]))
                fused[index] = candidate
                selected.add(key)
                break
    # A table or paragraph may continue into the next chunk on the same
    # page. Keep one bounded continuation of the strongest lexical match, using
    # only the current workspace and optional document filter.
    if n_final >= 3 and len(keyword_results) >= 2:
        anchor = keyword_results[0]
        corpus = get_collection().get(workspace_id=session_id, filename=document_filter, include=["documents", "metadatas"])
        for text, meta in zip(corpus["documents"], corpus["metadatas"]):
            if (meta.get("filename") == anchor["filename"] and
                meta.get("page_number") == anchor["page_number"] and
                meta.get("chunk_index") == anchor["chunk_index"] + 1):
                continuation = {"text": text, "filename": meta["filename"],
                                "page_number": meta["page_number"], "chunk_index": meta["chunk_index"]}
                key = _chunk_key(continuation)
                if key not in selected:
                    for index in range(len(fused) - 1, -1, -1):
                        if _chunk_key(fused[index]) not in reserved:
                            fused[index] = continuation
                            break
                break
    return fused
