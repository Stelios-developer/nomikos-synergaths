from unittest.mock import MagicMock, patch

from services import embeddings


def _fake_sentence_transformer(dim=8):
    fake_model = MagicMock()

    def fake_encode(texts, convert_to_numpy=True, show_progress_bar=False):
        import numpy as np
        return np.array([[float(i)] * dim for i in range(len(texts))])

    fake_model.encode.side_effect = fake_encode
    return fake_model


def test_embed_texts_empty_list_short_circuits():
    # No model load attempted for an empty list — would raise if
    # SentenceTransformer() were actually invoked here.
    assert embeddings.embed_texts([]) == []


def test_embed_texts_returns_one_vector_per_input(monkeypatch):
    monkeypatch.setattr(embeddings, "_model", _fake_sentence_transformer())
    result = embeddings.embed_texts(["hello", "world", "foo"])
    assert len(result) == 3
    assert all(isinstance(v, list) for v in result)


def test_embed_text_returns_single_vector(monkeypatch):
    monkeypatch.setattr(embeddings, "_model", _fake_sentence_transformer())
    result = embeddings.embed_text("hello")
    assert isinstance(result, list)
    assert len(result) == 8


def test_model_is_loaded_lazily_and_cached(monkeypatch):
    load_count = {"n": 0}

    class FakeSentenceTransformer:
        def __init__(self, name):
            load_count["n"] += 1
            self.name = name

        def encode(self, texts, convert_to_numpy=True, show_progress_bar=False):
            import numpy as np
            return np.array([[0.0] for _ in texts])

    monkeypatch.setattr(embeddings, "_model", None)
    with patch.dict("sys.modules", {"sentence_transformers": MagicMock(SentenceTransformer=FakeSentenceTransformer)}):
        embeddings.embed_texts(["a"])
        embeddings.embed_texts(["b"])

    assert load_count["n"] == 1  # loaded once, reused on the second call
