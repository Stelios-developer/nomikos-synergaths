"""Small SQLite store for the staged document-intelligence case file.

The n8n workflow passes only a case_id between stages. The complete,
workspace-scoped case stays server-side so agents cannot accidentally mix
evidence from another document or another workspace.
"""
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from services.workspace_lock import scoped_operation

CASE_DB_PATH = os.getenv("DOCUMENT_CASE_DB_PATH", "./document_cases.db")


class CaseWriteConflict(RuntimeError):
    """Another request advanced the case after this request read it."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(CASE_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS document_cases (
            case_id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            status TEXT NOT NULL,
            stage TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_document_cases_workspace_file "
        "ON document_cases(workspace_id, filename, updated_at DESC)"
    )
    return conn


@scoped_operation
def create_case(case: dict) -> dict:
    from services.analysis_context import check_commit
    check_commit()
    now = _now()
    case = {**case, "created_at": now, "updated_at": now}
    conn = _get_conn()
    try:
        conn.execute(
            """
            INSERT INTO document_cases
            (case_id, workspace_id, filename, status, stage, payload, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case["case_id"],
                case["workspace_id"],
                case["document"]["filename"],
                case["status"],
                case["stage"],
                json.dumps(case, ensure_ascii=False),
                now,
                now,
            ),
        )
        check_commit()
        conn.commit()
    finally:
        conn.close()
    return case


@scoped_operation
def get_case(case_id: str, workspace_id: str) -> dict | None:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT payload FROM document_cases WHERE case_id = ? AND workspace_id = ?",
            (case_id, workspace_id),
        ).fetchone()
    finally:
        conn.close()
    return json.loads(row["payload"]) if row else None


@scoped_operation
def get_latest_case(filename: str, workspace_id: str) -> dict | None:
    conn = _get_conn()
    try:
        row = conn.execute(
            """
            SELECT payload FROM document_cases
            WHERE filename = ? AND workspace_id = ?
            ORDER BY updated_at DESC LIMIT 1
            """,
            (filename, workspace_id),
        ).fetchone()
    finally:
        conn.close()
    return json.loads(row["payload"]) if row else None


@scoped_operation
def delete_cases_for_document(filename: str, workspace_id: str) -> int:
    """Remove every stored analysis for one document in one workspace."""
    conn = _get_conn()
    try:
        cursor = conn.execute(
            "DELETE FROM document_cases WHERE filename = ? AND workspace_id = ?",
            (filename, workspace_id),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


@scoped_operation
def save_case(case: dict) -> dict:
    from services.analysis_context import check_commit
    check_commit()
    expected = case.get("updated_at")
    if not expected:
        raise CaseWriteConflict("Reload the case before saving a new stage.")
    now = _now()
    if datetime.fromisoformat(now) <= datetime.fromisoformat(expected):
        now = (datetime.fromisoformat(expected) + timedelta(microseconds=1)).isoformat()
    case = {**case, "updated_at": now}
    conn = _get_conn()
    try:
        cursor = conn.execute(
            """
            UPDATE document_cases
            SET status = ?, stage = ?, payload = ?, updated_at = ?
            WHERE case_id = ? AND workspace_id = ? AND updated_at = ?
            """,
            (
                case["status"],
                case["stage"],
                json.dumps(case, ensure_ascii=False),
                now,
                case["case_id"],
                case["workspace_id"],
                expected,
            ),
        )
        if cursor.rowcount != 1:
            # Do not distinguish stale/deleted/foreign-workspace cases on the wire.
            raise CaseWriteConflict("The case changed. Reload it before retrying this stage.")
        check_commit()
        conn.commit()
    finally:
        conn.close()
    return case


def snapshot_document_cases(filename: str, workspace_id: str) -> list[tuple]:
    conn = _get_conn()
    try:
        return [tuple(row) for row in conn.execute(
            "SELECT case_id, workspace_id, filename, status, stage, payload, created_at, updated_at "
            "FROM document_cases WHERE filename = ? AND workspace_id = ?", (filename, workspace_id))]
    finally:
        conn.close()


def restore_document_cases(filename: str, workspace_id: str, rows: list[tuple]) -> None:
    conn = _get_conn()
    try:
        with conn:
            conn.execute("DELETE FROM document_cases WHERE filename = ? AND workspace_id = ?", (filename, workspace_id))
            conn.executemany("INSERT INTO document_cases VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    finally:
        conn.close()
