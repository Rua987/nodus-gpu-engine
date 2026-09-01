"""Nebius chat path: HTTP mocked, no API key file needed at import time."""
import json

import pytest


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _openai_shaped(text="ok", tool=None):
    msg = {"role": "assistant", "content": text}
    if tool:
        msg["tool_calls"] = [{"id": "c1", "type": "function",
                              "function": {"name": tool, "arguments": "{}"}}]
    return {"choices": [{"message": msg}]}


def test_chat_nebius_calls_openai_compatible(monkeypatch):
    import nodus_backends as nb
    from nge.backends import nebius

    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["model"] = json["model"]
        captured["auth"] = headers["Authorization"]
        return _FakeResp(_openai_shaped("hello from nemotron"))

    monkeypatch.setattr(nb, "requests", type("R", (), {"post": staticmethod(fake_post)}))
    monkeypatch.setenv("NEBIUS_API_KEY", "sk-test-123")
    monkeypatch.setenv("NEBIUS_BASE_URL", "https://api.studio.nebius.com/v1")

    out = nebius.chat_nebius([{"role": "user", "content": "hi"}],
                             "nebius:nvidia/Llama-3.1-Nemotron-70B-Instruct-HF", None)

    assert out["content"] == "hello from nemotron"
    assert captured["url"] == "https://api.studio.nebius.com/v1/chat/completions"
    assert captured["model"] == "nvidia/Llama-3.1-Nemotron-70B-Instruct-HF"  # prefix stripped
    assert captured["auth"] == "Bearer sk-test-123"


def test_chat_nebius_needs_key(monkeypatch):
    from nge.backends import nebius
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="Nebius API key"):
        nebius.chat_nebius([{"role": "user", "content": "x"}], "nebius:m", None)


def test_dispatch_through_wrapped_chat_api(monkeypatch):
    """register.apply() -> nb.chat_api('nebius:..') reaches chat_nebius."""
    import nodus_backends as nb
    from nge.backends import register

    monkeypatch.setattr(nb, "requests",
                        type("R", (), {"post": staticmethod(
                            lambda *a, **k: _FakeResp(_openai_shaped("routed")))}))
    monkeypatch.setenv("NEBIUS_API_KEY", "sk-x")
    register.apply()
    try:
        out = nb.chat_api([{"role": "user", "content": "hi"}], "nebius:m", None)
        assert out["content"] == "routed"
    finally:
        register.restore()
