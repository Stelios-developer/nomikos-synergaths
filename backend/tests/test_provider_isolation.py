import os

import pytest
import services.llm as llm


def test_unit_suite_does_not_inherit_provider_credentials():
    assert 'OPENAI_API_KEY' not in os.environ
    assert 'ANTHROPIC_API_KEY' not in os.environ
    with pytest.raises(RuntimeError, match='Live AI clients are disabled'):
        llm._openai()
    with pytest.raises(RuntimeError, match='Live AI clients are disabled'):
        llm._anthropic()


def test_a_test_can_explicitly_supply_a_fake_provider(monkeypatch):
    fake = object()
    monkeypatch.setattr(llm, '_openai', lambda: fake)
    assert llm._openai() is fake
