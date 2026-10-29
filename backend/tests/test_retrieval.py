from unittest.mock import patch

from db.vector_store import get_collection
from services import retrieval
from services.session_scope import DEFAULT_SESSION_ID


def _seed_collection():
    # session_id is stamped here because real ingestion (services/ingestion.py)
    # always stamps it on every chunk; without it these rows would silently
    # fail retrieval.py's session-scoped where_clause() filter (a metadata
    # key that's simply absent never matches an equality filter), which
    # isn't what these tests are meant to exercise.
    col = get_collection()
    col.add(
        workspace_id=DEFAULT_SESSION_ID,
        ids=["a", "b", "c"],
        embeddings=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        documents=[
            "The tax deduction rules changed in 2024.",
            "Bananas and apples are common fruits.",
            "Corporate tax deduction guidelines require documentation.",
        ],
        metadatas=[
            {"filename": "tax.pdf", "page_number": 1, "chunk_index": 0, "session_id": DEFAULT_SESSION_ID},
            {"filename": "fruit.pdf", "page_number": 1, "chunk_index": 0, "session_id": DEFAULT_SESSION_ID},
            {"filename": "tax.pdf", "page_number": 2, "chunk_index": 1, "session_id": DEFAULT_SESSION_ID},
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


def test_greek_risk_question_finds_english_risk_and_mitigation_chunks():
    col = get_collection()
    col.add(
        workspace_id="greek-test",
        ids=["g1", "g2", "g3"], embeddings=[[1, 0, 0]] * 3,
        documents=["Decision center and proposed actions.",
                   "Known risks and mitigations: late filing may cause a penalty. Weekly readiness review is required.",
                   "General introduction and policy purpose."],
        metadatas=[{"filename": "policy.pdf", "page_number": 2, "chunk_index": i, "session_id": "greek-test"} for i in range(3)],
    )
    results = retrieval.keyword_search("Ποιοι είναι οι βασικοί κίνδυνοι και ποιες ενέργειες προτείνονται;", session_id="greek-test")
    assert any("late filing" in item["text"] for item in results)
    assert all("General introduction" not in item["text"] for item in results)


def test_keyword_search_does_not_rank_nonmatching_chunks():
    _seed_collection()
    assert retrieval.keyword_search("unmatchedtermxyz") == []


def test_hybrid_preserves_relevant_lexical_candidates_when_vectors_dominate():
    vectors = [{"filename": "case.pdf", "chunk_index": i, "page_number": 1, "text": f"vector {i}"} for i in range(5)]
    lexical = [{"filename": "case.pdf", "chunk_index": 20 + i, "page_number": 2, "text": f"risk {i}"} for i in range(2)]
    with patch.object(retrieval, "vector_search", return_value=vectors), patch.object(retrieval, "keyword_search", return_value=lexical):
        result = retrieval.hybrid_search("κίνδυνοι", document_filter="case.pdf", session_id="tenant", n_final=5)
    assert len(result) == 5
    assert {20, 21} <= {row["chunk_index"] for row in result}


def test_greek_management_and_reconciliation_question_finds_english_milestones():
    col = get_collection()
    col.add(workspace_id="milestones", ids=["m1", "m2", "m3"], embeddings=[[1, 0, 0]] * 3,
            documents=["30 June 2026 Management review of draft tax position Finance Director",
                       "15 July 2026 Final reconciliation and legal review Tax Manager",
                       "Travel receipts are due within 45 days"],
            metadatas=[{"filename": "policy.pdf", "page_number": 2, "chunk_index": i, "session_id": "milestones"} for i in range(3)])
    results = retrieval.keyword_search("Ποιες είναι οι προθεσμίες για τη διοικητική επισκόπηση και την τελική συμφωνία;", session_id="milestones")
    assert {0, 1} <= {row["chunk_index"] for row in results}


def test_hybrid_preserves_same_page_continuation_without_crossing_workspace():
    col = get_collection()
    for scope, document in [("tenant-a", "A risk and its first mitigation"), ("tenant-b", "PRIVATE OTHER WORKSPACE")]:
        col.add(workspace_id=scope, ids=[scope+"0", scope+"1"], embeddings=[[1,0,0],[1,0,0]],
                documents=["risk heading", document], metadatas=[
                    {"filename":"case.pdf","page_number":2,"chunk_index":i,"session_id":scope} for i in range(2)])
    vectors = [{"filename":"case.pdf","page_number":1,"chunk_index":i+10,"text":"unrelated"} for i in range(5)]
    lexical = [{"filename":"case.pdf","page_number":2,"chunk_index":0,"text":"risk heading"},
               {"filename":"case.pdf","page_number":1,"chunk_index":0,"text":"intro"}]
    with patch.object(retrieval,"vector_search",return_value=vectors), patch.object(retrieval,"keyword_search",return_value=lexical):
        rows = retrieval.hybrid_search("risk",document_filter="case.pdf",session_id="tenant-a",n_final=5)
    assert "A risk and its first mitigation" in [row["text"] for row in rows]
    assert all("PRIVATE OTHER WORKSPACE" not in row["text"] for row in rows)
