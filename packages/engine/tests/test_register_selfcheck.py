"""register.verify() self-check on the nebius: monkey-patch."""
import pytest

from nge.backends import register


@pytest.fixture(autouse=True)
def _restore():
    yield
    register.restore()


def test_verify_passes_after_apply():
    register.apply()
    register.verify()          # must not raise


def test_verify_catches_a_broken_backend_patch(monkeypatch):
    register.apply()
    import nodus_backends as nb
    # simulate a vendored-Nodus change that un-does the patch
    monkeypatch.setattr(nb, "detect_backend", lambda m: "ollama")
    with pytest.raises(RuntimeError, match="not in effect"):
        register.verify()


def test_verify_detects_nodus_agent_reimport(monkeypatch):
    register.apply()
    try:
        import nodus_agent as na
    except Exception:
        pytest.skip("nodus_agent not importable")
    monkeypatch.setattr(na, "detect_backend", lambda m: "ollama")
    with pytest.raises(RuntimeError, match="nodus_agent"):
        register.verify()
