from unittest.mock import patch

from db.chroma_client import get_collection
from services import retrieval


def _seed_collection():
    col = get_collection()
    col.add(
        ids=["a", "b", "c"],
        embeddings=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        documents=[
            "The tax deduction rules changed in 2024.",
            "Bananas and apples are common fruits.",
            "Corporate tax deduction guidelines require documentation.",
        ],
        metadatas=[
            {"filename": "tax.pdf", "page_number": 1, "chunk_index": 0},
            {"filename": "fruit.pdf", "page_number": 1, "chunk_index": 0},
            {"filename": "tax.pdf", "page_number": 2, "chunk_index": 1},
        ],
    )
    return col


def test_vector_search_ranks_by_similarity():
    _seed_collection()
    with patch.object(retrieval, "embed_query", return_value=[0.9, 0.1, 0]):
        results = retrieval.vector_search("tax deduction rules", n_results=3)
    assert results[0]["filename"] == "tax.pdf"
    assert results[0]["chunk_index"] == 0
    assert results[0]["distance"] < results[-1]["distance"]


def test_vector_search_respects_document_filter():
    _seed_collection()
    with patch.object(retrieval, "embed_query", return_value=[0.9, 0.1, 0]):
        results = retrieval.vector_search("tax", n_results=10, document_filter="fruit.pdf")
    assert len(results) == 1
    assert results[0]["filename"] == "fruit.pdf"


def test_keyword_search_finds_matching_terms():
    _seed_collection()
    results = retrieval.keyword_search("tax deduction", n_results=10)
    filenames = [r["filename"] for r in results]
    assert "tax.pdf" in filenames


def test_keyword_search_empty_collection_returns_empty():
    # no _seed_collection() call — collection is empty
    results = retrieval.keyword_search("anything", n_results=10)
    assert results == []


def test_reciprocal_rank_fusion_merges_two_ranked_lists():
    vector_results = [
        {"filename": "a.pdf", "chunk_index": 0, "text": "x"},
        {"filename": "b.pdf", "chunk_index": 0, "text": "y"},
    ]
    keyword_results = [
        {"filename": "b.pdf", "chunk_index": 0, "text": "y"},
        {"filename": "c.pdf", "chunk_index": 0, "text": "z"},
    ]
    fused = retrieval.reciprocal_rank_fusion(vector_results, keyword_results, n_final=3)
    fused_filenames = {c["filename"] for c in fused}
    assert fused_filenames == {"a.pdf", "b.pdf", "c.pdf"}
    # b.pdf appears in both lists (rank 1 in each) -> highest combined RRF score
    assert fused[0]["filename"] == "b.pdf"


def test_reciprocal_rank_fusion_respects_n_final():
    vector_results = [{"filename": f"{i}.pdf", "chunk_index": 0, "text": "x"} for i in range(5)]
    fused = retrieval.reciprocal_rank_fusion(vector_results, [], n_final=2)
    assert len(fused) == 2


def test_hybrid_search_document_filter_applies_to_both_paths():
    _seed_collection()
    with patch.object(retrieval, "embed_query", return_value=[0.9, 0.1, 0]):
        results = retrieval.hybrid_search("tax deduction", document_filter="tax.pdf")
    assert all(r["filename"] == "tax.pdf" for r in results)
