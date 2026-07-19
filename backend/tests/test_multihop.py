from unittest.mock import patch

import services.multihop as multihop

RATE_CHUNK = {"text": "The R&D deduction rate is 24%.", "filename": "tax.pdf", "page_number": 2, "chunk_index": 0}
DEPR_CHUNK = {"text": "Equipment depreciation is 15% per year.", "filename": "tax.pdf", "page_number": 4, "chunk_index": 1}


def _fake_hybrid_search(sub_question, document_filter=None, session_id=None):
    if "deduction" in sub_question.lower() or "24" in sub_question:
        return [RATE_CHUNK]
    if "depreciation" in sub_question.lower():
        return [DEPR_CHUNK]
    return []


def test_decompose_parses_json_list_of_subquestions():
    with patch.object(multihop, "complete", return_value='["what is the R&D rate?", "what is the depreciation rate?"]'):
        result = multihop._decompose("compound question")
    assert result == ["what is the R&D rate?", "what is the depreciation rate?"]


def test_decompose_falls_back_to_atomic_on_unparseable_response():
    with patch.object(multihop, "complete", return_value="I'm not sure how to split this."):
        result = multihop._decompose("some question")
    assert result == ["some question"]


def test_decompose_falls_back_to_atomic_when_too_many_subquestions():
    too_many = '["a", "b", "c", "d", "e"]'  # 5 > MAX_SUBQUESTIONS (4)
    with patch.object(multihop, "complete", return_value=too_many):
        result = multihop._decompose("some question")
    assert result == ["some question"]


def test_research_subquestion_applies_corrective_rag_grading():
    chunks = [RATE_CHUNK, DEPR_CHUNK]
    with patch.object(multihop, "hybrid_search", return_value=chunks), \
         patch.object(multihop, "_grade_chunks", return_value=[True, False]):
        result = multihop._research_subquestion("what is the R&D rate?", None)
    assert result == [RATE_CHUNK]


def test_research_subquestion_falls_back_to_unfiltered_when_nothing_graded_relevant():
    chunks = [RATE_CHUNK]
    with patch.object(multihop, "hybrid_search", return_value=chunks), \
         patch.object(multihop, "_grade_chunks", return_value=[False]):
        result = multihop._research_subquestion("q", None)
    assert result == [RATE_CHUNK]  # falls back rather than losing the only candidate entirely


def test_run_research_stream_decomposes_and_merges_subquestion_chunks():
    subqs = ["what is the R&D deduction rate?", "what is the equipment depreciation rate?"]

    def fake_stream_answer(question, chunks, history=None):
        for tok in ["24% ", "and ", "15%."]:
            yield tok

    with patch.object(multihop, "_decompose", return_value=subqs), \
         patch.object(multihop, "hybrid_search", side_effect=_fake_hybrid_search), \
         patch.object(multihop, "_grade_chunks", return_value=[True]), \
         patch.object(multihop, "stream_answer", side_effect=fake_stream_answer), \
         patch.object(multihop, "evaluate_and_store", return_value={"faithfulness": 0.9}):
        events = list(multihop.run_research_stream("compound question"))

    kinds = [k for k, _ in events]
    assert kinds[0] == "subquestions"
    assert kinds.count("subretrieval") == 2
    assert kinds.count("token") == 3
    assert kinds[-1] == "done"

    assert events[0][1] == subqs

    subretrievals = [payload for kind, payload in events if kind == "subretrieval"]
    by_sq = {s["sub_question"]: s["citations"] for s in subretrievals}
    assert by_sq[subqs[0]][0]["filename"] == "tax.pdf"
    assert by_sq[subqs[0]][0]["page"] == 2
    assert by_sq[subqs[1]][0]["page"] == 4

    done_citations = events[-1][1]["citations"]
    assert {c["page"] for c in done_citations} == {2, 4}  # merged from both sub-questions


def test_run_research_stream_dedupes_chunks_shared_across_subquestions():
    subqs = ["sub one", "sub two"]

    def fake_stream_answer(question, chunks, history=None):
        yield "answer"

    with patch.object(multihop, "_decompose", return_value=subqs), \
         patch.object(multihop, "hybrid_search", return_value=[RATE_CHUNK]), \
         patch.object(multihop, "_grade_chunks", return_value=[True]), \
         patch.object(multihop, "stream_answer", side_effect=fake_stream_answer), \
         patch.object(multihop, "evaluate_and_store", return_value=None):
        events = list(multihop.run_research_stream("q"))

    done_citations = next(payload for kind, payload in events if kind == "done")["citations"]
    assert len(done_citations) == 1  # same chunk retrieved for both sub-questions -> deduped once


def test_run_research_stream_handles_single_atomic_question_without_concurrency():
    with patch.object(multihop, "_decompose", return_value=["atomic question"]), \
         patch.object(multihop, "hybrid_search", return_value=[RATE_CHUNK]), \
         patch.object(multihop, "_grade_chunks", return_value=[True]), \
         patch.object(multihop, "stream_answer", return_value=iter(["answer"])), \
         patch.object(multihop, "evaluate_and_store", return_value=None):
        events = list(multihop.run_research_stream("atomic question"))

    kinds = [k for k, _ in events]
    assert kinds.count("subretrieval") == 1


def test_run_research_stream_yields_fallback_message_when_nothing_found_anywhere():
    with patch.object(multihop, "_decompose", return_value=["q1", "q2"]), \
         patch.object(multihop, "hybrid_search", return_value=[]), \
         patch.object(multihop, "stream_answer") as mock_stream_answer:
        events = list(multihop.run_research_stream("nothing relevant uploaded"))

    kinds = [k for k, _ in events]
    assert "token" in kinds
    assert kinds[-1] == "done"
    assert events[-1][1]["citations"] == []
    mock_stream_answer.assert_not_called()  # never reaches generation with zero merged chunks
