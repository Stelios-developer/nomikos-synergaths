"""
Local embeddings via sentence-transformers — no API key, no external
network call at query/ingestion time. Replaces OpenAI's
text-embedding-3-small, which required OPENAI_API_KEY purely for
embeddings even when generation ran entirely on Claude.

The model downloads once on first use (~80MB, cached under
~/.cache/torch/sentence_transformers or HF_HOME) and then runs locally
for every embed call — free and offline after that.

IMPORTANT: PostgreSQL validates the embedding model and dimensions against
its stored configuration. Changing either requires an explicit verified
re-embedding migration; never delete the old vector data as a quick fix.
"""
import os

EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer  # lazy import -
        # keeps torch off the import path for anything that doesn't embed
        # OCR itself runs in the separate PDF safety worker.
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
