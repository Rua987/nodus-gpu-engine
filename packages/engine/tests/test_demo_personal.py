"""Personal demo modes (--local / --deepseek) stay off the Nebius track."""
import pytest


def test_deepseek_refuses_nebius_track(monkeypatch):
    monkeypatch.setenv("NGE_TRACK", "nebius")
    from nge import demo_nebius as d
    rc = d.main(["--deepseek", "--max-rounds", "1"])
    assert rc == 2


def test_local_refuses_nebius_track(monkeypatch):
    monkeypatch.setenv("NGE_TRACK", "nebius")
    from nge import demo_nebius as d
    rc = d.main(["--local", "--max-rounds", "1"])
    assert rc == 2


def test_deepseek_rejects_ollama_model_name(monkeypatch):
    monkeypatch.delenv("NGE_TRACK", raising=False)
    from nge import demo_nebius as d
    rc = d.main(["--deepseek", "--model", "qwen3.5:2b", "--max-rounds", "1"])
    assert rc == 2


def test_needs_ollama_false_for_deepseek_chat():
    from nge.demo_nebius import _needs_ollama
    assert _needs_ollama("deepseek-chat") is False
    assert _needs_ollama("qwen3.5:2b") is True


def test_mutual_exclusion_live_deepseek():
    from nge import demo_nebius as d
    with pytest.raises(SystemExit):
        d.main(["--live", "--deepseek"])
