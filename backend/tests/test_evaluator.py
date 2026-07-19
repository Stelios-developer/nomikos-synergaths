from unittest.mock import patch

from services import evaluator


def test_evaluate_and_store_persists_scores():
    with patch.object(evaluator, "score", side_effect=[0.9, 0.8]):
        result = evaluator.evaluate_and_store(
            "what is x?", "x is y [1].", [{"text": "x is y", "filename": "a.pdf", "page_number": 1}]
        )
    assert result == {"faithfulness": 0.9, "relevance": 0.8}

    agg = evaluator.get_aggregate()
    assert agg["total_queries"] == 1
    assert agg["avg_faithfulness"] == 0.9
    assert agg["avg_relevance"] == 0.8


def test_get_aggregate_averages_across_multiple_queries():
    with patch.object(evaluator, "score", side_effect=[0.9, 0.8]):
        evaluator.evaluate_and_store("q1", "a1", [])
    with patch.object(evaluator, "score", side_effect=[0.5, 0.6]):
        evaluator.evaluate_and_store("q2", "a2", [])

    agg = evaluator.get_aggregate()
    assert agg["total_queries"] == 2
    assert abs(agg["avg_faithfulness"] - 0.7) < 1e-6
    assert abs(agg["avg_relevance"] - 0.7) < 1e-6
    assert len(agg["history"]) == 2
    assert agg["history"][0]["question"] == "q2"  # most recent first


def test_get_aggregate_empty_db_returns_zeros():
    agg = evaluator.get_aggregate()
    assert agg == {"avg_faithfulness": 0.0, "avg_relevance": 0.0, "total_queries": 0, "history": []}


def test_relevance_score_without_history_has_no_history_block():
    captured_prompt = {}

    def fake_score(prompt):
        captured_prompt["value"] = prompt
        return 0.9

    with patch.object(evaluator, "score", side_effect=fake_score):
        evaluator.relevance_score("what about deductions?", [{"text": "x", "filename": "a.pdf", "page_number": 1}])

    assert "Ιστορικό συνομιλίας" not in captured_prompt["value"]


def test_relevance_score_with_history_includes_it_in_prompt():
    captured_prompt = {}

    def fake_score(prompt):
        captured_prompt["value"] = prompt
        return 0.9

    history = [
        {"role": "user", "content": "What is the travel expense cap?"},
        {"role": "assistant", "content": "It's €12,000 per employee [1]."},
    ]

    with patch.object(evaluator, "score", side_effect=fake_score):
        evaluator.relevance_score(
            "and what's needed above that amount?",
            [{"text": "requires CFO pre-approval", "filename": "a.pdf", "page_number": 2}],
            history,
        )

    assert "Ιστορικό συνομιλίας" in captured_prompt["value"]
    assert "travel expense cap" in captured_prompt["value"]
    assert "€12,000" in captured_prompt["value"]


def test_evaluate_and_store_passes_history_through_to_relevance_only():
    captured = {}

    def fake_relevance_score(question, chunks, history=None):
        captured["relevance_history"] = history
        return 0.4

    def fake_faithfulness_score(answer, chunks):
        captured["faithfulness_called_without_history"] = True
        return 0.95

    history = [{"role": "user", "content": "earlier question"}, {"role": "assistant", "content": "earlier answer"}]

    with patch.object(evaluator, "relevance_score", side_effect=fake_relevance_score), \
         patch.object(evaluator, "faithfulness_score", side_effect=fake_faithfulness_score):
        result = evaluator.evaluate_and_store("follow-up?", "answer text", [], history)

    assert captured["relevance_history"] == history
    assert captured["faithfulness_called_without_history"] is True  # faithfulness has no history param at all
    assert result == {"faithfulness": 0.95, "relevance": 0.4}
