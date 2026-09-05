"""One chat client, built from config - so no module can bypass the proxy."""

import pytest

from server import config, llm
from server.agent import post_call_analysis as pca


def test_chat_client_uses_configured_base_url(monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", "k")
    monkeypatch.setattr(config, "OPENAI_BASE_URL", "https://proxy.example/v1")
    assert str(llm.chat_client().base_url).startswith("https://proxy.example/v1")


def test_chat_client_defaults_to_openai(monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", "k")
    monkeypatch.setattr(config, "OPENAI_BASE_URL", None)
    assert "api.openai.com" in str(llm.chat_client().base_url)


def test_chat_client_requires_a_key(monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    with pytest.raises(RuntimeError):
        llm.chat_client()


def test_post_call_validation_handles_fenced_json_and_bad_values():
    text = '```json\n{"summary": "Paid", "outcome": "nonsense", "memory_facts": [{"key": "salary_day", "value": "25th"}], "next_action": {"type": "bogus"}}\n```'
    out = pca._validate_analysis(text)
    assert out["summary"] == "Paid"
    assert out["outcome"] == "answered"          # unknown outcome falls back
    assert out["memory_facts"] == [{"key": "salary_day", "value": "25th"}]
    assert out["next_action"]["type"] == "none"  # unknown action falls back
