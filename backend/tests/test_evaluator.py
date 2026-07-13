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
