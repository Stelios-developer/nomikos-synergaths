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
import os

PDF_STORAGE_DIR = os.getenv(
    "PDF_STORAGE_DIR",
    os.path.join(os.path.dirname(__file__), "..", "storage", "pdfs"),
)
os.makedirs(PDF_STORAGE_DIR, exist_ok=True)


def _safe_path(filename: str) -> str:
    safe_name = os.path.basename(filename)
    return os.path.join(PDF_STORAGE_DIR, safe_name)


def save_pdf(filename: str, contents: bytes) -> str:
    """Writes the raw PDF bytes to permanent storage and returns the path."""
    path = _safe_path(filename)
    with open(path, "wb") as f:
        f.write(contents)
    return path


def delete_pdf(filename: str) -> None:
    """
    Removes any existing stored copy before a re-upload overwrites it.
    Deliberately swallows OSError: a failure to delete the OLD file (e.g. a
    permissions quirk on the underlying filesystem) must never block saving
    the NEW upload — `open(path, "wb")` in save_pdf overwrites it in place
    regardless. Found via a real end-to-end run against a mounted
    filesystem where `os.remove` raised PermissionError despite
    `os.path.exists` already having been checked — i.e. the exists-then-
    remove sequence isn't atomic/reliable across all filesystems, so a
    defensive try/except is the right fix independent of the specific
    underlying error.
    """
    path = _safe_path(filename)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def pdf_path(filename: str) -> str | None:
    """Returns the stored path for filename, or None if it isn't on disk
    (e.g. uploaded before this feature existed, or already deleted)."""
    path = _safe_path(filename)
    return path if os.path.exists(path) else None
