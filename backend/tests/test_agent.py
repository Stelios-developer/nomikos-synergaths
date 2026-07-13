from unittest.mock import patch

from services import agent


def test_run_agent_succeeds_immediately_without_rephrasing():
    with patch.object(agent, "hybrid_search", return_value=[
            {"text": "x", "filename": "a.pdf", "page_number": 1, "chunk_index": 0}]), \
         patch.object(agent, "yes_no", return_value=True), \
         patch.object(agent, "generate_answer", return_value="ANSWER") as mock_generate:
        result = agent.run_agent("what is x?")

    assert result["iteration"] == 0
    assert result["answer"] == "ANSWER"
    assert result["should_retry"] is False
    mock_generate.assert_called_once()


def test_run_agent_rephrases_once_then_succeeds():
    call_count = {"n": 0}

    def fake_yes_no(prompt):
        call_count["n"] += 1
        return call_count["n"] > 1  # NO on first evaluate, YES on second

    with patch.object(agent, "hybrid_search", return_value=[
            {"text": "x", "filename": "a.pdf", "page_number": 1, "chunk_index": 0}]), \
         patch.object(agent, "yes_no", side_effect=fake_yes_no), \
         patch.object(agent, "complete", return_value="better query"), \
         patch.object(agent, "generate_answer", return_value="ANSWER2"):
        result = agent.run_agent("what is x?")

    assert result["iteration"] == 1
    assert result["question"] == "better query"
    assert result["answer"] == "ANSWER2"


def test_run_agent_stops_at_max_iterations():
    with patch.object(agent, "hybrid_search", return_value=[]), \
         patch.object(agent, "yes_no", return_value=False), \
         patch.object(agent, "complete", return_value="rephrased"), \
         patch.object(agent, "generate_answer", return_value="ANSWER3") as mock_generate:
        result = agent.run_agent("what is x?")

    assert result["iteration"] == agent.MAX_ITERATIONS
    assert result["should_retry"] is False
    mock_generate.assert_called_once()  # generate still runs exactly once, after giving up retrying


def test_agentic_retrieve_mirrors_graph_retry_behavior():
    call_count = {"n": 0}

    def fake_yes_no(prompt):
        call_count["n"] += 1
        return call_count["n"] > 1

    with patch.object(agent, "hybrid_search", return_value=[
            {"text": "x", "filename": "a.pdf", "page_number": 1, "chunk_index": 0}]), \
         patch.object(agent, "yes_no", side_effect=fake_yes_no), \
         patch.object(agent, "complete", return_value="condensed query"):
        final_query, chunks, iterations = agent.agentic_retrieve("what is x?")

    assert final_query == "condensed query"
    assert iterations == 1
    assert len(chunks) == 1


def test_agentic_retrieve_no_retry_needed():
    with patch.object(agent, "hybrid_search", return_value=[
            {"text": "x", "filename": "a.pdf", "page_number": 1, "chunk_index": 0}]), \
         patch.object(agent, "yes_no", return_value=True):
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
         patch.object(agent, "yes_no", return_value=True), \
         patch.object(agent, "complete", return_value="standalone deduction question"), \
         patch.object(agent, "generate_answer", side_effect=fake_generate_answer):
        result = agent.run_agent("what about the second one?", history=history)

    # retrieval used the condensed, standalone query
    mock_search.assert_called_once_with("standalone deduction question", document_filter=None)
    # generation used the raw follow-up question + full history
    assert captured_generate_args["question"] == "what about the second one?"
    assert captured_generate_args["history"] == history
    assert result["answer"] == "ANSWER"


def test_agentic_retrieve_condenses_before_searching():
    history = [{"role": "user", "content": "Tell me about deductions."},
               {"role": "assistant", "content": "Sure [1]."}]

    with patch.object(agent, "hybrid_search", return_value=[
            {"text": "x", "filename": "a.pdf", "page_number": 1, "chunk_index": 0}]) as mock_search, \
         patch.object(agent, "yes_no", return_value=True), \
         patch.object(agent, "complete", return_value="standalone query"):
        final_query, chunks, iterations = agent.agentic_retrieve("what about the second one?", history=history)

    assert final_query == "standalone query"
    mock_search.assert_called_once_with("standalone query", document_filter=None)
