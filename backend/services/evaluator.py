"""
Evaluation layer: faithfulness + context-relevance scoring via LLM
judgment (gpt-4o-mini, same as services.llm.score — cheap, no separate
evaluation model needed per the brief). Scores persist to SQLite for
simplicity; GET /evaluation aggregates from the same table.
"""
import os
import sqlite3
from datetime import datetime, timezone

from services.llm import score

DB_PATH = os.getenv("EVAL_DB_PATH", "./evaluation.db")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            faithfulness REAL NOT NULL,
            relevance REAL NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    return conn


def faithfulness_score(answer: str, chunks: list[dict]) -> float:
    context = "\n\n".join(c["text"] for c in chunks)
    prompt = (
        f"Αποσπάσματα εγγράφων:\n{context}\n\nΑπάντηση: {answer}\n\n"
        "Η απάντηση περιέχει πληροφορίες που ΔΕΝ υπάρχουν στα παραπάνω αποσπάσματα; "
        "Score 0.0-1.0 όπου 1.0 = πλήρως faithful (καμία εξωτερική πληροφορία)."
    )
    return score(prompt)


def relevance_score(question: str, chunks: list[dict]) -> float:
    context = "\n\n".join(c["text"] for c in chunks)
    prompt = (
        f"Ερώτηση: {question}\n\nΑποσπάσματα:\n{context}\n\n"
        "Πόσο σχετικά είναι τα αποσπάσματα με την ερώτηση; "
        "Score 0.0-1.0 όπου 1.0 = πλήρως σχετικά."
    )
    return score(prompt)


def evaluate_and_store(question: str, answer: str, chunks: list[dict]) -> dict:
    """Runs both scores and persists the result. Called after the streamed
    answer finishes (see routers/query.py)."""
    faithfulness = faithfulness_score(answer, chunks)
    relevance = relevance_score(question, chunks)

    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO evaluations (question, answer, faithfulness, relevance, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (question, answer, faithfulness, relevance, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

    return {"faithfulness": faithfulness, "relevance": relevance}


def get_aggregate() -> dict:
    conn = _get_conn()
    try:
        total, avg_f, avg_r = conn.execute(
            "SELECT COUNT(*), AVG(faithfulness), AVG(relevance) FROM evaluations"
        ).fetchone()

        rows = conn.execute(
            "SELECT question, faithfulness, relevance, created_at FROM evaluations "
            "ORDER BY id DESC LIMIT 10"
        ).fetchall()
    finally:
        conn.close()

    return {
        "avg_faithfulness": round(avg_f, 3) if avg_f is not None else 0.0,
        "avg_relevance": round(avg_r, 3) if avg_r is not None else 0.0,
        "total_queries": total or 0,
        "history": [
            {"question": q, "faithfulness": f, "relevance": r, "created_at": c}
            for q, f, r, c in rows
        ],
    }
