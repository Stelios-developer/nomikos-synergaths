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


def test_complete_uses_openai_by_default(monkeypatch):
    from unittest.mock import MagicMock
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content="  hi there  "))
    ]
    monkeypatch.setattr(llm, "_openai", lambda: fake_client)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    result = llm.complete("say hi", max_tokens=5)

    assert result == "hi there"  # stripped
    fake_client.chat.completions.create.assert_called_once_with(
        timeout=120,
        model=llm.OPENAI_MODEL,
        messages=[{"role": "user", "content": "say hi"}],
        max_tokens=5,
    )


def test_complete_uses_anthropic_when_provider_set(monkeypatch):
    from unittest.mock import MagicMock
    fake_client = MagicMock()
    fake_client.messages.create.return_value.content = [MagicMock(text="  hi from claude  ")]
    monkeypatch.setattr(llm, "_anthropic", lambda: fake_client)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")

    result = llm.complete("say hi", max_tokens=5)

    assert result == "hi from claude"
    fake_client.messages.create.assert_called_once_with(
        timeout=120,
        model=llm.ANTHROPIC_MODEL,
        max_tokens=5,
        messages=[{"role": "user", "content": "say hi"}],
    )


def test_yes_no_and_score_follow_anthropic_provider(monkeypatch):
    from unittest.mock import MagicMock
    fake_client = MagicMock()
    fake_client.messages.create.return_value.content = [MagicMock(text="YES")]
    monkeypatch.setattr(llm, "_anthropic", lambda: fake_client)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")

    assert llm.yes_no("does this suffice?") is True
    fake_client.messages.create.assert_called_with(
        timeout=120,
        model=llm.ANTHROPIC_MODEL, max_tokens=5,
        messages=[{"role": "user", "content": "does this suffice?"}],
    )

    fake_client.messages.create.return_value.content = [MagicMock(text="0.75")]
    assert llm.score("rate this") == 0.75


def test_generate_answer_uses_anthropic_when_configured(monkeypatch):
    from unittest.mock import MagicMock
    fake_client = MagicMock()
    fake_client.messages.create.return_value.content = [MagicMock(text="claude's answer [1].")]
    monkeypatch.setattr(llm, "_anthropic", lambda: fake_client)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")

    result = llm.generate_answer("what is x?", [{"filename": "a.pdf", "page_number": 1, "text": "x is y"}])

    assert result == "claude's answer [1]."
    call_kwargs = fake_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == llm.ANTHROPIC_MODEL
    assert call_kwargs["system"] == llm.SYSTEM_PROMPT


def test_call_with_tools_openai_returns_tool_call(monkeypatch):
    from unittest.mock import MagicMock
    fake_tool_call = MagicMock()
    fake_tool_call.function.name = "run_code"
    fake_tool_call.function.arguments = '{"code": "print(1)"}'

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content=None, tool_calls=[fake_tool_call]))
    ]
    monkeypatch.setattr(llm, "_openai", lambda: fake_client)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    tools = [{"name": "run_code", "description": "run it", "parameters": {"type": "object", "properties": {}}}]
    result = llm.call_with_tools("do something", tools)

    assert result["tool_call"] == {"name": "run_code", "input": {"code": "print(1)"}}

    call_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["tools"][0]["type"] == "function"
    assert call_kwargs["tools"][0]["function"]["name"] == "run_code"


def test_call_with_tools_openai_returns_none_when_no_tool_invoked(monkeypatch):
    from unittest.mock import MagicMock
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content="just some text", tool_calls=None))
    ]
    monkeypatch.setattr(llm, "_openai", lambda: fake_client)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    tools = [{"name": "finish", "description": "stop", "parameters": {"type": "object", "properties": {}}}]
    result = llm.call_with_tools("wrap it up", tools)

    assert result["tool_call"] is None
    assert result["text"] == "just some text"


def test_call_with_tools_anthropic_returns_tool_call(monkeypatch):
    from unittest.mock import MagicMock
    tool_use_block = MagicMock(type="tool_use", input={"code": "print(2)"})
    tool_use_block.name = "run_code"  # MagicMock(name=...) sets the mock's repr, not an attribute — must assign after

    fake_client = MagicMock()
    fake_client.messages.create.return_value.content = [tool_use_block]
    monkeypatch.setattr(llm, "_anthropic", lambda: fake_client)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")

    tools = [{"name": "run_code", "description": "run it", "parameters": {"type": "object", "properties": {}}}]
    result = llm.call_with_tools("do something", tools)

    assert result["tool_call"] == {"name": "run_code", "input": {"code": "print(2)"}}

    call_kwargs = fake_client.messages.create.call_args.kwargs
    assert call_kwargs["tools"][0]["name"] == "run_code"
    assert call_kwargs["tools"][0]["input_schema"] == tools[0]["parameters"]


def test_call_with_tools_anthropic_returns_none_when_only_text(monkeypatch):
    from unittest.mock import MagicMock
    text_block = MagicMock(type="text", text="here is my answer")

    fake_client = MagicMock()
    fake_client.messages.create.return_value.content = [text_block]
    monkeypatch.setattr(llm, "_anthropic", lambda: fake_client)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")

    tools = [{"name": "finish", "description": "stop", "parameters": {"type": "object", "properties": {}}}]
    result = llm.call_with_tools("wrap it up", tools)

    assert result["tool_call"] is None
    assert result["text"] == "here is my answer"
