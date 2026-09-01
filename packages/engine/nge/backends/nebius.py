"""Nebius AI Studio backend (OpenAI-compatible) serving Nemotron models.

Nebius AI Studio exposes an OpenAI-compatible ``/chat/completions`` endpoint, so
we reuse Nodus' own generic helper ``nodus_backends._chat_openai_compatible``
(URL + Bearer key + tool schemas) and its response normaliser. Nothing here
duplicates the ReAct loop.
"""
from __future__ import annotations

from typing import List, Optional

from nge import config as _cfg

BACKEND_NAME = "nebius"


def is_nebius_model(model: str) -> bool:
    return (model or "").strip().lower().startswith(_cfg.NEBIUS_PREFIX)


def nebius_model_id(model: str) -> str:
    """``nebius:nvidia/...Nemotron...`` -> ``nvidia/...Nemotron...``."""
    m = (model or "").strip()
    if m.lower().startswith(_cfg.NEBIUS_PREFIX):
        return m[len(_cfg.NEBIUS_PREFIX):]
    return m


def assert_nebius_track(model: str) -> None:
    """When NGE_TRACK=nebius, block any non-Nebius LLM backend.

    Symmetric to ``nodus_backends.assert_hackathon_llm_model`` but for the
    Nebius "Coding & Agentic Engineering" submission. Leaves the Agentic Cinema
    guard (``NODUS_HACKATHON``) untouched.
    """
    if not _cfg.hackathon_track():
        return
    if not is_nebius_model(model):
        raise RuntimeError(
            f"NGE_TRACK=nebius allows only Nebius AI Studio models "
            f"(nebius:...). Got {model!r}. See docs/NEBIUS_TRACK.md."
        )


def chat_nebius(messages: list, model: str, tools: Optional[list]) -> dict:
    """One chat turn against Nebius AI Studio. Returns an Ollama-style message."""
    assert_nebius_track(model)
    import nodus_backends as nb  # vendored, on sys.path via nge/__init__

    cfg = _cfg.load()
    api_key = cfg.nebius_api_key()
    if not api_key:
        raise RuntimeError(
            "Nebius API key missing - create packages/engine/.nebius_api_key "
            "or set NEBIUS_API_KEY"
        )
    return nb._chat_openai_compatible(
        messages, nebius_model_id(model), tools, cfg.nebius_chat_url, api_key
    )


def nemotron_plan_fallback(task: str, allowed_tools: List[str]) -> Optional[List[str]]:
    """Skeleton: ask Nemotron for an ordered tool-name plan when the local 324M
    planner declines. Wired but intentionally minimal for this milestone.
    """
    prompt = (
        "You plan tool steps for a coding agent.\n"
        "Reply with ONLY a JSON array of tool names in order.\n"
        f"Allowed tools: {', '.join(allowed_tools)}\n"
        f"Task: {task}"
    )
    msg = chat_nebius([{"role": "user", "content": prompt}], _cfg.load().nemotron_model, None)
    import json
    try:
        names = json.loads((msg.get("content") or "").strip())
        if isinstance(names, list) and all(isinstance(n, str) for n in names):
            return [n for n in names if n in allowed_tools]
    except (ValueError, TypeError):
        pass
    return None
