"""
Local embeddings via sentence-transformers — no API key, no external
network call at query/ingestion time. Replaces OpenAI's
text-embedding-3-small, which required OPENAI_API_KEY purely for
embeddings even when generation ran entirely on Claude.

The model downloads once on first use (~80MB, cached under
~/.cache/torch/sentence_transformers or HF_HOME) and then runs locally
for every embed call — free and offline after that.

IMPORTANT: embedding dimensionality is baked into whatever's already
stored in ChromaDB. If you've previously ingested documents with a
different embedding model/dimension, clear CHROMA_PERSIST_DIR (delete
the chroma_db folder) before switching, or ChromaDB will error on the
dimension mismatch.
"""
import os

EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer  # lazy import -
        # keeps torch off the import path for anything that doesn't embed
        # (mirrors the same lazy-import pattern used for EasyOCR).
        _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Batch-embeds a list of strings. Returns one vector per input."""
    if not texts:
        return []
    vectors = _get_model().encode(texts, convert_to_numpy=True, show_progress_bar=False)
    return vectors.tolist()


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]
