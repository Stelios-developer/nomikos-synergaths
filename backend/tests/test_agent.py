from unittest.mock import patch

from services import agent


def test_run_agent_succeeds_immediately_without_rephrasing():
    with patch.object(agent, "hybrid_search", return_value=[
            {"text": "x", "filename": "a.pdf", "page_number": 1, "chunk_index": 0}]), \
         patch.object(agent, "_grade_chunks", return_value=[True]), \
         patch.object(agent, "generate_answer", return_value="ANSWER") as mock_generate:
        result = agent.run_agent("what is x?")

    assert result["iteration"] == 0
    assert result["answer"] == "ANSWER"
    assert result["should_retry"] is False
    mock_generate.assert_called_once()


def test_run_agent_rephrases_once_then_succeeds():
    call_count = {"n": 0}

    def fake_grade_chunks(question, chunks):
        call_count["n"] += 1
        return [call_count["n"] > 1]  # nothing relevant on 1st evaluate, relevant on 2nd

    with patch.object(agent, "hybrid_search", return_value=[
            {"text": "x", "filename": "a.pdf", "page_number": 1, "chunk_index": 0}]), \
         patch.object(agent, "_grade_chunks", side_effect=fake_grade_chunks), \
         patch.object(agent, "complete", return_value="better query"), \
         patch.object(agent, "generate_answer", return_value="ANSWER2"):
        result = agent.run_agent("what is x?")

    assert result["iteration"] == 1
    assert result["question"] == "better query"
    assert result["answer"] == "ANSWER2"


def test_run_agent_stops_at_max_iterations():
    with patch.object(agent, "hybrid_search", return_value=[]), \
         patch.object(agent, "_grade_chunks", return_value=[]), \
         patch.object(agent, "complete", return_value="rephrased"), \
         patch.object(agent, "generate_answer", return_value="ANSWER3") as mock_generate:
        result = agent.run_agent("what is x?")

    assert result["iteration"] == agent.MAX_ITERATIONS
    assert result["should_retry"] is False
    mock_generate.assert_called_once()  # generate still runs exactly once, after giving up retrying


def test_agentic_retrieve_mirrors_graph_retry_behavior():
    call_count = {"n": 0}

    def fake_grade_chunks(question, chunks):
        call_count["n"] += 1
        return [call_count["n"] > 1]

    with patch.object(agent, "hybrid_search", return_value=[
            {"text": "x", "filename": "a.pdf", "page_number": 1, "chunk_index": 0}]), \
         patch.object(agent, "_grade_chunks", side_effect=fake_grade_chunks), \
         patch.object(agent, "complete", return_value="condensed query"):
        final_query, chunks, iterations = agent.agentic_retrieve("what is x?")

    assert final_query == "condensed query"
    assert iterations == 1
    assert len(chunks) == 1


def test_agentic_retrieve_no_retry_needed():
    with patch.object(agent, "hybrid_search", return_value=[
            {"text": "x", "filename": "a.pdf", "page_number": 1, "chunk_index": 0}]), \
         patch.object(agent, "_grade_chunks", return_value=[True]):
        final_query, chunks, iterations = agent.agentic_retrieve("what is x?")

    assert final_query == "what is x?"
    assert iterations == 0


def test_condense_question_noop_without_history():
    # No history -> no LLM call at all (would raise if complete() were hit,
    # since it's not patched here).
    result = agent._condense_question("what about deductions?", [])
    assert result == "what about deductions?"


def test_condense_question_rewrites_followup_using_history():
    history = [
        {"role": "user", "content": "What are the 2024 tax deduction rules?"},
        {"role": "assistant", "content": "They changed to require X and Y [1]."},
    ]
    with patch.object(agent, "complete", return_value="What are the requirements X and Y for 2024 tax deductions?"):
        result = agent._condense_question("what about the second one?", history)
    assert result == "What are the requirements X and Y for 2024 tax deductions?"


def test_run_agent_uses_condensed_question_for_retrieval_but_raw_for_generation():
    history = [{"role": "user", "content": "Tell me about deductions."},
               {"role": "assistant", "content": "Sure, here's what the docs say [1]."}]

    captured_generate_args = {}

    def fake_generate_answer(question, chunks, hist):
        captured_generate_args["question"] = question
        captured_generate_args["history"] = hist
        return "ANSWER"

    with patch.object(agent, "hybrid_search", return_value=[
            {"text": "x", "filename": "a.pdf", "page_number": 1, "chunk_index": 0}]) as mock_search, \
         patch.object(agent, "_grade_chunks", return_value=[True]), \
         patch.object(agent, "complete", return_value="standalone deduction question"), \
         patch.object(agent, "generate_answer", side_effect=fake_generate_answer):
        result = agent.run_agent("what about the second one?", history=history)

    # retrieval used the condensed, standalone query
    mock_search.assert_called_once_with(
        "standalone deduction question", document_filter=None, session_id=agent.DEFAULT_SESSION_ID
    )
    # generation used the raw follow-up question + full history
    assert captured_generate_args["question"] == "what about the second one?"
    assert captured_generate_args["history"] == history
    assert result["answer"] == "ANSWER"


def test_agentic_retrieve_condenses_before_searching():
    history = [{"role": "user", "content": "Tell me about deductions."},
               {"role": "assistant", "content": "Sure [1]."}]

    with patch.object(agent, "hybrid_search", return_value=[
            {"text": "x", "filename": "a.pdf", "page_number": 1, "chunk_index": 0}]) as mock_search, \
         patch.object(agent, "_grade_chunks", return_value=[True]), \
         patch.object(agent, "complete", return_value="standalone query"):
        final_query, chunks, iterations = agent.agentic_retrieve("what about the second one?", history=history)

    assert final_query == "standalone query"
    mock_search.assert_called_once_with(
        "standalone query", document_filter=None, session_id=agent.DEFAULT_SESSION_ID
    )


# --- Corrective RAG: per-chunk grading ---------------------------------

def test_evaluate_filters_out_chunks_graded_irrelevant():
    # 3 retrieved chunks, only the 1st and 3rd graded relevant -> only
    # those 2 should survive into generation, unlike the old whole-batch
    # yes/no check which would have kept (or dropped) all 3 together.
    chunks = [
        {"text": "relevant one", "filename": "a.pdf", "page_number": 1, "chunk_index": 0},
        {"text": "off topic noise", "filename": "a.pdf", "page_number": 2, "chunk_index": 1},
        {"text": "relevant two", "filename": "a.pdf", "page_number": 3, "chunk_index": 2},
    ]
    captured = {}

    def fake_generate_answer(question, gen_chunks, hist):
        captured["chunks"] = gen_chunks
        return "ANSWER"

    with patch.object(agent, "hybrid_search", return_value=chunks), \
         patch.object(agent, "_grade_chunks", return_value=[True, False, True]), \
         patch.object(agent, "generate_answer", side_effect=fake_generate_answer):
        result = agent.run_agent("what is x?")

    assert [c["text"] for c in captured["chunks"]] == ["relevant one", "relevant two"]
    assert result["should_retry"] is False


def test_evaluate_retries_when_no_chunks_graded_relevant():
    chunks = [{"text": "off topic", "filename": "a.pdf", "page_number": 1, "chunk_index": 0}]

    with patch.object(agent, "hybrid_search", return_value=chunks), \
         patch.object(agent, "_grade_chunks", return_value=[False]), \
         patch.object(agent, "complete", return_value="rephrased query"), \
         patch.object(agent, "generate_answer", return_value="ANSWER"):
        result = agent.run_agent("what is x?")

    # nothing ever graded relevant across MAX_ITERATIONS retries -> gives up
    assert result["iteration"] == agent.MAX_ITERATIONS


def test_grade_chunks_parses_json_bool_list_from_llm_response():
    chunks = [
        {"text": "a", "filename": "a.pdf", "page_number": 1, "chunk_index": 0},
        {"text": "b", "filename": "a.pdf", "page_number": 1, "chunk_index": 1},
    ]
    with patch.object(agent, "complete", return_value="Here you go: [true, false]"):
        result = agent._grade_chunks("question", chunks)
    assert result == [True, False]


def test_grade_chunks_falls_back_to_all_relevant_on_unparseable_response():
    chunks = [
        {"text": "a", "filename": "a.pdf", "page_number": 1, "chunk_index": 0},
        {"text": "b", "filename": "a.pdf", "page_number": 1, "chunk_index": 1},
    ]
    with patch.object(agent, "complete", return_value="I'm not sure, sorry."):
        result = agent._grade_chunks("question", chunks)
    assert result == [True, True]


def test_grade_chunks_falls_back_when_list_length_mismatches_chunk_count():
    chunks = [
        {"text": "a", "filename": "a.pdf", "page_number": 1, "chunk_index": 0},
        {"text": "b", "filename": "a.pdf", "page_number": 1, "chunk_index": 1},
    ]
    with patch.object(agent, "complete", return_value="[true]"):  # only 1 flag for 2 chunks
        result = agent._grade_chunks("question", chunks)
    assert result == [True, True]
