"""Nebius chat path: HTTP mocked, no API key file needed at import time."""
import json

import pytest


class _FakeResp:
    def __init__(self, payload, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text or json.dumps(payload)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _openai_shaped(text="ok", tool=None, usage=None, finish_reason="stop"):
    msg = {"role": "assistant", "content": text}
    if tool:
        msg["tool_calls"] = [{"id": "c1", "type": "function",
                              "function": {"name": tool, "arguments": "{}"}}]
    out = {"choices": [{"message": msg, "finish_reason": finish_reason}]}
    if usage is not None:
        out["usage"] = usage
    return out


def _fake_requests(post_fn):
    import requests as real_requests
    return type("R", (), {
        "post": staticmethod(post_fn),
        "RequestException": real_requests.RequestException,
    })()


def test_chat_nebius_sends_max_tokens_default(monkeypatch):
    from nge.backends import nebius
    from nge.backends import usage as _usage

    captured = {}
    _usage.reset_usage()

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["payload"] = json
        captured["auth"] = headers["Authorization"]
        return _FakeResp(_openai_shaped(
            "hello from nemotron",
            usage={"prompt_tokens": 10, "completion_tokens": 5}))

    monkeypatch.setattr(nebius, "requests", _fake_requests(fake_post))
    monkeypatch.setenv("NEBIUS_API_KEY", "sk-test-123")
    monkeypatch.setenv("NEBIUS_BASE_URL", "https://api.studio.nebius.com/v1")
    monkeypatch.delenv("NGE_NEMOTRON_MAX_TOKENS", raising=False)

    out = nebius.chat_nebius([{"role": "user", "content": "hi"}],
                             "nebius:nvidia/Llama-3.1-Nemotron-70B-Instruct-HF",
                             None)

    assert out["content"] == "hello from nemotron"
    assert out.get("finish_reason") == "stop"
    assert captured["url"] == "https://api.studio.nebius.com/v1/chat/completions"
    assert captured["payload"]["model"] == "nvidia/Llama-3.1-Nemotron-70B-Instruct-HF"
    assert captured["payload"]["max_tokens"] == 2048
    assert captured["auth"] == "Bearer sk-test-123"
    snap = _usage.snapshot()
    assert snap["nvidia/Llama-3.1-Nemotron-70B-Instruct-HF"]["calls"] == 1
    assert snap["nvidia/Llama-3.1-Nemotron-70B-Instruct-HF"]["prompt_tokens"] == 10
    assert snap["nvidia/Llama-3.1-Nemotron-70B-Instruct-HF"]["completion_tokens"] == 5


def test_chat_nebius_honors_max_tokens_override(monkeypatch):
    from nge.backends import nebius
    from nge.backends import usage as _usage

    captured = {}
    _usage.reset_usage()

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["payload"] = json
        return _FakeResp(_openai_shaped("x", usage={"prompt_tokens": 1,
                                                    "completion_tokens": 1}))

    monkeypatch.setattr(nebius, "requests", _fake_requests(fake_post))
    monkeypatch.setenv("NEBIUS_API_KEY", "sk-x")

    nebius.chat_nebius([{"role": "user", "content": "hi"}], "nebius:m", None,
                       max_tokens=256)
    assert captured["payload"]["max_tokens"] == 256


def test_chat_nebius_surfaces_finish_reason_length(monkeypatch):
    from nge.backends import nebius
    from nge.backends import usage as _usage

    _usage.reset_usage()

    def fake_post(url, json=None, headers=None, timeout=None):
        return _FakeResp(_openai_shaped(
            "--- a/x.py\n+++ b/x.py\n@@", finish_reason="length",
            usage={"prompt_tokens": 1, "completion_tokens": 2048}))

    monkeypatch.setattr(nebius, "requests", _fake_requests(fake_post))
    monkeypatch.setenv("NEBIUS_API_KEY", "sk-x")
    out = nebius.chat_nebius([{"role": "user", "content": "hi"}], "nebius:m")
    assert out["finish_reason"] == "length"


def test_chat_nebius_429_is_model_unavailable(monkeypatch):
    from nge.backends import nebius

    def fake_post(url, json=None, headers=None, timeout=None):
        return _FakeResp({}, status_code=429, text="rate limited")

    monkeypatch.setattr(nebius, "requests", _fake_requests(fake_post))
    monkeypatch.setenv("NEBIUS_API_KEY", "sk-x")
    with pytest.raises(nebius.ModelUnavailableError) as ei:
        nebius.chat_nebius([{"role": "user", "content": "hi"}], "nebius:m")
    assert ei.value.status == 429


def test_chat_nebius_503_is_model_unavailable(monkeypatch):
    from nge.backends import nebius

    def fake_post(url, json=None, headers=None, timeout=None):
        return _FakeResp({}, status_code=503, text="unavailable")

    monkeypatch.setattr(nebius, "requests", _fake_requests(fake_post))
    monkeypatch.setenv("NEBIUS_API_KEY", "sk-x")
    with pytest.raises(nebius.ModelUnavailableError) as ei:
        nebius.chat_nebius([{"role": "user", "content": "hi"}], "nebius:m")
    assert ei.value.status == 503


def test_resolve_patch_max_tokens_env(monkeypatch):
    from nge.backends import nebius
    monkeypatch.delenv("NGE_PATCH_MAX_TOKENS", raising=False)
    assert nebius.resolve_patch_max_tokens() == 2048
    monkeypatch.setenv("NGE_PATCH_MAX_TOKENS", "4096")
    assert nebius.resolve_patch_max_tokens() == 4096


def test_chat_nebius_needs_key(monkeypatch):
    from nge.backends import nebius
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="Nebius API key"):
        nebius.chat_nebius([{"role": "user", "content": "x"}], "nebius:m", None)


def test_dispatch_through_wrapped_chat_api(monkeypatch):
    """register.apply() -> nb.chat_api('nebius:..') reaches chat_nebius."""
    import nodus_backends as nb
    from nge.backends import nebius
    from nge.backends import register
    from nge.backends import usage as _usage

    _usage.reset_usage()

    def fake_post(url, json=None, headers=None, timeout=None):
        return _FakeResp(_openai_shaped("routed",
                                        usage={"prompt_tokens": 2,
                                               "completion_tokens": 3}))

    monkeypatch.setattr(nebius, "requests", _fake_requests(fake_post))
    monkeypatch.setenv("NEBIUS_API_KEY", "sk-x")
    register.apply()
    try:
        out = nb.chat_api([{"role": "user", "content": "hi"}], "nebius:m", None)
        assert out["content"] == "routed"
    finally:
        register.restore()


def test_usage_summary_and_reset():
    from nge.backends import usage as u
    u.reset_usage()
    u.record("nvidia/nemotron-3-super-120b-a12b", 100, 50, 2048)
    u.record("nvidia/nemotron-3-nano-30b-a3b", 20, 10, 256)
    u.record_route("ultra", "plan")
    u.record_route("ultra", "plan")
    text = u.format_summary()
    assert "super" in text and "nano" in text
    assert "TOTAL" in text
    assert "calls=" in text and "in=" in text
    assert "ultra" in text and "route-only" in text
    u.reset_usage()
    assert u.snapshot() == {}
    assert u.routes_snapshot() == {}


def test_retry_distribution_refuses_without_flag():
    import subprocess
    import sys
    from pathlib import Path
    eng = Path(__file__).resolve().parents[1]
    r = subprocess.run(
        [sys.executable, "-m", "bench.retry_distribution"],
        cwd=str(eng), capture_output=True, text=True)
    assert r.returncode == 2
    assert "i-know-cost" in (r.stderr + r.stdout)
