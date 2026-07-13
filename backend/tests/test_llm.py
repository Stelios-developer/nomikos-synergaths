from services import llm


def test_provider_defaults_to_openai(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert llm.provider() == "openai"


def test_provider_reads_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    assert llm.provider() == "anthropic"


def test_build_context_numbers_and_labels_chunks():
    chunks = [
        {"filename": "a.pdf", "page_number": 1, "text": "first chunk"},
        {"filename": "b.pdf", "page_number": 3, "text": "second chunk"},
    ]
    context = llm._build_context(chunks)
    assert "[1]" in context and "[2]" in context
    assert "a.pdf" in context and "page 1" in context
    assert "b.pdf" in context and "page 3" in context


def test_yes_no_parses_affirmative_response(monkeypatch):
    from unittest.mock import MagicMock
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content="YES"))
    ]
    monkeypatch.setattr(llm, "_openai", lambda: fake_client)
    assert llm.yes_no("does this suffice?") is True


def test_yes_no_parses_negative_response(monkeypatch):
    from unittest.mock import MagicMock
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content="NO"))
    ]
    monkeypatch.setattr(llm, "_openai", lambda: fake_client)
    assert llm.yes_no("does this suffice?") is False


def test_score_clamps_to_0_1_range(monkeypatch):
    from unittest.mock import MagicMock
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content="1.5"))
    ]
    monkeypatch.setattr(llm, "_openai", lambda: fake_client)
    assert llm.score("rate this") == 1.0


def test_score_falls_back_to_0_5_on_unparseable_response(monkeypatch):
    from unittest.mock import MagicMock
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content="not a number"))
    ]
    monkeypatch.setattr(llm, "_openai", lambda: fake_client)
    assert llm.score("rate this") == 0.5


def test_history_messages_empty_when_no_history():
    assert llm._history_messages(None) == []
    assert llm._history_messages([]) == []


def test_history_messages_truncates_to_max():
    long_history = [{"role": "user", "content": f"msg{i}"} for i in range(20)]
    result = llm._history_messages(long_history)
    assert len(result) == llm.MAX_HISTORY_MESSAGES
    assert result[-1]["content"] == "msg19"  # keeps the most recent turns


def test_generate_answer_includes_history_in_openai_messages(monkeypatch):
    from unittest.mock import MagicMock
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content="the answer"))
    ]
    monkeypatch.setattr(llm, "_openai", lambda: fake_client)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    history = [{"role": "user", "content": "earlier question"}, {"role": "assistant", "content": "earlier answer"}]
    result = llm.generate_answer("follow-up question", [], history)

    assert result == "the answer"
    sent_messages = fake_client.chat.completions.create.call_args.kwargs["messages"]
    assert sent_messages[0]["role"] == "system"
    assert sent_messages[1] == history[0]
    assert sent_messages[2] == history[1]
    assert "follow-up question" in sent_messages[3]["content"]
