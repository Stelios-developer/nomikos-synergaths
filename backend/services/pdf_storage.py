"""
Persists uploaded PDFs to disk so citations can later be traced back to
the original page (see routers/documents.py :: get_page_image).

Before this module existed, /upload wrote the file to a NamedTemporaryFile
that got deleted right after ingestion — chunks lived on in ChromaDB, but
the source PDF was gone, so there was no way to show *where* on the page
an answer came from. Storing a permanent copy (keyed by filename) fixes
that at negligible cost: PDFs are small relative to the embeddings/vector
index already being persisted.

Path traversal note: `filename` comes from the client (multipart upload
filename), so we strip it down to os.path.basename before touching the
filesystem.
"""
import hashlib
import os
import tempfile

from services.session_scope import DEFAULT_SESSION_ID

PDF_STORAGE_DIR = os.getenv(
    "PDF_STORAGE_DIR",
    os.path.join(os.path.dirname(__file__), "..", "storage", "pdfs"),
)
os.makedirs(PDF_STORAGE_DIR, exist_ok=True)


def _safe_path(filename: str, session_id: str = DEFAULT_SESSION_ID) -> str:
    # The session/workspace identifier can come from an HTTP header, so never
    # use it as a path component directly. A stable hash also prevents two
    # tenants that upload the same filename from overwriting each other's PDF.
    scope = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    # A browser filename can legally contain characters that Windows refuses
    # in a real filesystem path (for example `:` or `?`). Keep the original
    # name only in document metadata and use an opaque, deterministic storage
    # name instead. This also prevents filename disclosure in the storage tree.
    original_name = os.path.basename(filename)
    name_hash = hashlib.sha256(original_name.encode("utf-8")).hexdigest()
    return os.path.join(PDF_STORAGE_DIR, scope, f"{name_hash}.pdf")


def storage_usage_bytes(session_id: str = DEFAULT_SESSION_ID) -> int:
    """Return the current raw-PDF storage footprint for one user workspace."""
    scope = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    folder = os.path.join(PDF_STORAGE_DIR, scope)
    if not os.path.isdir(folder):
        return 0
    return sum(
        entry.stat().st_size
        for entry in os.scandir(folder)
        if entry.is_file() and entry.name.lower().endswith(".pdf")
    )


def save_pdf(
    filename: str, contents: bytes, session_id: str = DEFAULT_SESSION_ID
) -> str:
    """Writes the raw PDF bytes to permanent storage and returns the path."""
    path = _safe_path(filename, session_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(contents)
    return path


def stage_pdf(filename: str, contents: bytes, session_id: str = DEFAULT_SESSION_ID) -> str:
    """Keep a replacement separate from the active source during extraction."""
    destination = _safe_path(filename, session_id)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    fd, staged_path = tempfile.mkstemp(prefix=".incoming-", suffix=".tmp", dir=os.path.dirname(destination))
    try:
        with os.fdopen(fd, "wb") as staged:
            staged.write(contents)
            staged.flush()
            os.fsync(staged.fileno())
    except Exception:
        os.unlink(staged_path)
        raise
    return staged_path


def commit_staged_pdf(filename: str, staged_path: str, session_id: str = DEFAULT_SESSION_ID) -> str:
    destination = _safe_path(filename, session_id)
    os.replace(staged_path, destination)
    return destination


def discard_staged_pdf(staged_path: str) -> None:
    try:
        os.unlink(staged_path)
    except FileNotFoundError:
        pass


def delete_pdf(filename: str, session_id: str = DEFAULT_SESSION_ID) -> None:
    """Remove the stored source, raising if removal fails.

    A user-facing deletion must never report success while the PDF remains.
    Missing files are harmless, so retries after partial cleanup are safe.
    """
    path = _safe_path(filename, session_id)
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def pdf_path(filename: str, session_id: str = DEFAULT_SESSION_ID) -> str | None:
    """Returns the stored path for filename, or None if it isn't on disk
    (e.g. uploaded before this feature existed, or already deleted)."""
    path = _safe_path(filename, session_id)
    return path if os.path.exists(path) else None
