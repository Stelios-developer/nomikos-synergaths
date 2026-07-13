from unittest.mock import MagicMock, patch

from services import agent


def _fake_openai_rephrase(rephrased_text="rephrased query"):
    fake = MagicMock()
    fake.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content=rephrased_text))
    ]
    return fake


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

    fake_openai = _fake_openai_rephrase("better query")

    with patch.object(agent, "hybrid_search", return_value=[
            {"text": "x", "filename": "a.pdf", "page_number": 1, "chunk_index": 0}]), \
         patch.object(agent, "yes_no", side_effect=fake_yes_no), \
         patch.object(agent, "_openai", return_value=fake_openai), \
         patch.object(agent, "generate_answer", return_value="ANSWER2"):
        result = agent.run_agent("what is x?")

    assert result["iteration"] == 1
    assert result["question"] == "better query"
    assert result["answer"] == "ANSWER2"


def test_run_agent_stops_at_max_iterations():
    fake_openai = _fake_openai_rephrase()

    with patch.object(agent, "hybrid_search", return_value=[]), \
         patch.object(agent, "yes_no", return_value=False), \
         patch.object(agent, "_openai", return_value=fake_openai), \
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

    fake_openai = _fake_openai_rephrase("condensed query")

    with patch.object(agent, "hybrid_search", return_value=[
            {"text": "x", "filename": "a.pdf", "page_number": 1, "chunk_index": 0}]), \
         patch.object(agent, "yes_no", side_effect=fake_yes_no), \
         patch.object(agent, "_openai", return_value=fake_openai):
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
