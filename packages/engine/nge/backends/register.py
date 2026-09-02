"""Reversible monkey-patch that adds the ``nebius:`` backend to vendored Nodus.

Why patch instead of edit: the plan mandates *isolated integration* - the
``packages/nodus`` tree stays byte-for-byte upstream so its Agentic Cinema demo
keeps working. ``apply()`` wraps two pure-ish functions:

    nodus_backends.detect_backend   -> "nebius" for nebius:* ids, else original
    nodus_backends.chat_api         -> chat_nebius for nebius, else original

Both the module attributes and the names already bound inside ``nodus_agent``
(``from nodus_backends import chat_api, detect_backend``) are repointed.
``restore()`` undoes everything (used by tests).
"""
from __future__ import annotations

from nge.backends import nebius as _nebius

_ORIG: dict = {}
_APPLIED = False


def _wrap_detect_backend(orig):
    def detect_backend(model: str) -> str:
        if _nebius.is_nebius_model(model):
            return _nebius.BACKEND_NAME
        return orig(model)
    detect_backend.__wrapped__ = orig  # type: ignore[attr-defined]
    return detect_backend


def _wrap_chat_api(orig):
    def chat_api(messages: list, model: str, tools=None) -> dict:
        if _nebius.is_nebius_model(model):
            return _nebius.chat_nebius(messages, model, tools)
        return orig(messages, model, tools)
    chat_api.__wrapped__ = orig  # type: ignore[attr-defined]
    return chat_api


_PROBE = "nebius:__register_selfcheck__"


def verify() -> None:
    """Fail loud if the patch is not actually in effect where it must be.

    Guards against a vendored-Nodus refactor changing import style (e.g.
    ``nodus_agent`` re-importing ``detect_backend`` after apply()) silently
    routing ``nebius:`` models to Ollama.
    """
    import nodus_backends as nb
    if nb.detect_backend(_PROBE) != _nebius.BACKEND_NAME:
        raise RuntimeError(
            "register: monkey-patch not in effect on nodus_backends.detect_backend "
            "- vendored Nodus may have changed. nebius: models would misroute.")
    if getattr(nb.chat_api, "__wrapped__", None) is None:
        raise RuntimeError("register: nodus_backends.chat_api is not the wrapper")
    try:
        import nodus_agent as na
    except Exception:
        return
    if na.detect_backend(_PROBE) != _nebius.BACKEND_NAME:
        raise RuntimeError(
            "register: nodus_agent.detect_backend not repointed - it likely "
            "re-imported the name from nodus_backends after apply().")


def apply() -> None:
    """Idempotently install the nebius: routes. Safe to call many times."""
    global _APPLIED
    if _APPLIED:
        return
    import nodus_backends as nb

    _ORIG["nb.detect_backend"] = nb.detect_backend
    _ORIG["nb.chat_api"] = nb.chat_api
    nb.detect_backend = _wrap_detect_backend(nb.detect_backend)
    nb.chat_api = _wrap_chat_api(nb.chat_api)

    # Repoint names already imported into nodus_agent, if it is loaded.
    try:
        import nodus_agent as na
        _ORIG["na.detect_backend"] = na.detect_backend
        _ORIG["na.chat_api"] = na.chat_api
        na.detect_backend = nb.detect_backend
        na.chat_api = nb.chat_api
    except Exception:  # nodus_agent optional at this layer
        pass

    _APPLIED = True
    verify()


def restore() -> None:
    global _APPLIED
    if not _APPLIED:
        return
    import nodus_backends as nb
    nb.detect_backend = _ORIG["nb.detect_backend"]
    nb.chat_api = _ORIG["nb.chat_api"]
    if "na.detect_backend" in _ORIG:
        import nodus_agent as na
        na.detect_backend = _ORIG["na.detect_backend"]
        na.chat_api = _ORIG["na.chat_api"]
    _ORIG.clear()
    _APPLIED = False


def is_applied() -> bool:
    return _APPLIED
