"""The nebius: route installs cleanly and does not regress Agentic Cinema."""
import pytest


@pytest.fixture
def restored():
    from nge.backends import register
    register.apply()
    yield
    register.restore()


def test_detect_backend_routes_nebius(restored):
    import nodus_backends as nb
    assert nb.detect_backend("nebius:nvidia/Llama-3.1-Nemotron-70B-Instruct-HF") == "nebius"


def test_agentic_cinema_backends_untouched(restored):
    import nodus_backends as nb
    assert nb.detect_backend("vertex:gemini-2.5-flash") == "vertex"
    assert nb.detect_backend("gemini:gemini-2.5-flash") == "gemini"
    assert nb.detect_backend("claude-sonnet-4-5") == "anthropic"
    assert nb.detect_backend("qwen3.5:2b") == "ollama"


def test_restore_is_clean():
    from nge.backends import register
    import nodus_backends as nb
    orig = nb.detect_backend
    register.apply()
    assert nb.detect_backend is not orig
    register.restore()
    assert nb.detect_backend is orig
    assert nb.detect_backend("nebius:x") == "ollama"  # no longer special


def test_nebius_track_guard(monkeypatch, restored):
    from nge.backends import nebius
    monkeypatch.setenv("NGE_TRACK", "nebius")
    with pytest.raises(RuntimeError):
        nebius.assert_nebius_track("vertex:gemini-2.5-flash")
    nebius.assert_nebius_track("nebius:whatever")  # ok
