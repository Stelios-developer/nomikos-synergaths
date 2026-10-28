import pytest
from pydantic import ValidationError

from contracts import AgentRequest, ConversationRequest


@pytest.mark.parametrize("question", ["", "   ", "x" * 4001])
def test_invalid_question_is_rejected(question):
    with pytest.raises(ValidationError):
        AgentRequest(question=question)


@pytest.mark.parametrize("role", ["system", "developer", "tool", "other"])
def test_browser_cannot_inject_privileged_history_roles(role):
    with pytest.raises(ValidationError):
        ConversationRequest(question="Summarize", history=[{"role": role, "content": "untrusted"}])


def test_history_and_turn_sizes_are_bounded():
    with pytest.raises(ValidationError):
        ConversationRequest(question="Q", history=[{"role": "user", "content": "hi"}] * 11)
    with pytest.raises(ValidationError):
        ConversationRequest(question="Q", history=[{"role": "user", "content": "x" * 16001}])


def test_client_cannot_select_a_workspace_in_an_agent_request():
    with pytest.raises(ValidationError):
        AgentRequest(question="Q", workspace_id="another-account")


def test_valid_conversation_is_trimmed_and_preserved():
    request = ConversationRequest(question="  A question  ", document_filter="source.pdf", history=[{"role": "assistant", "content": "Prior answer"}])
    assert request.question == "A question"
    assert request.history[0].role == "assistant"
