"""Nebius Token Factory backend (OpenAI-compatible) serving Nemotron models.

HTTP is done here (not via vendored ``_chat_openai_compatible``) so we can set
``max_tokens``, record ``usage``, and surface ``finish_reason`` without editing
``packages/nodus/``.
"""
from __future__ import annotations

import os
from typing import List, Optional

import requests

from nge import config as _cfg
from nge.backends import usage as _usage

BACKEND_NAME = "nebius"

DEFAULT_MAX_TOKENS = 2048
SLOT_MAX_TOKENS = 256
# Patches reason first (see THINKING_DEFAULTS), and the reasoning counts
# against this ceiling: at 2048, 9/9 live patch calls were cut before a
# single diff line (bench/thinking_ab.py, 2026-10-01). Override with
# NGE_PATCH_MAX_TOKENS.
PATCH_MAX_TOKENS = 8192


class ModelUnavailableError(RuntimeError):
    """Token Factory returned 429 or 5xx — no silent failover to another tier."""

    def __init__(self, model: str, status: Optional[int], detail: str = ""):
        self.model = model
        self.status = status
        msg = f"model unavailable: {model}"
        if status is not None:
            msg += f" (HTTP {status})"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)


def is_nebius_model(model: str) -> bool:
    return (model or "").strip().lower().startswith(_cfg.NEBIUS_PREFIX)


def nebius_model_id(model: str) -> str:
    """``nebius:nvidia/...Nemotron...`` -> ``nvidia/...Nemotron...``."""
    m = (model or "").strip()
    if m.lower().startswith(_cfg.NEBIUS_PREFIX):
        return m[len(_cfg.NEBIUS_PREFIX):]
    return m


def assert_nebius_track(model: str) -> None:
    """When NGE_TRACK=nebius, block any non-Nebius LLM backend."""
    if not _cfg.hackathon_track():
        return
    if not is_nebius_model(model):
        raise RuntimeError(
            f"NGE_TRACK=nebius allows only Nebius AI Studio models "
            f"(nebius:...). Got {model!r}. See docs/NEBIUS_TRACK.md."
        )


def resolve_max_tokens(explicit: Optional[int] = None) -> int:
    if explicit is not None:
        return max(1, int(explicit))
    raw = (os.environ.get("NGE_NEMOTRON_MAX_TOKENS") or "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return DEFAULT_MAX_TOKENS


def resolve_patch_max_tokens() -> int:
    """Ceiling for patch/triage replies only."""
    raw = (os.environ.get("NGE_PATCH_MAX_TOKENS") or "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return PATCH_MAX_TOKENS


_ON = ("1", "on", "true", "yes")
_OFF = ("0", "off", "false", "no")

# Per call class, whether Nemotron 3 may reason before answering. ``None``
# sends nothing and leaves the model's own default (Super reasons by default).
# "short" = replies capped at SLOT_MAX_TOKENS (slot-fill, mission, plan
# fallback); "patch" = unified diffs. Measured live, 3 runs per arm on real
# Token Factory sandboxes (bench/thinking_ab.py, docs/FIX_LOOP.md):
#   short, reasoning on:  0/6 slot-fills usable (256/256 reasoning, empty)
#   short, reasoning off: 12/12 usable
#   patch, vendored suite (Windows-only failures):
#     off: 9/9 parsed, 4/9 invented context · on @8192: 0 invented, 1 real fix
#   patch, bench/bugbench (6 seeded bugs, held-out checks), 18 attempts each:
#     off: 16 correct, $0.006 · on @8192: 16 correct, $0.021 · on @2048: 15
# Patches keep reasoning: a tie on seeded bugs, the only hard-set fix came
# from it, and off is the measured cheap option (NGE_THINKING_PATCH=off).
THINKING_DEFAULTS = {"short": False, "patch": True}


def resolve_thinking(call_class: str) -> Optional[bool]:
    """Reasoning on/off for a call class; ``NGE_THINKING_<CLASS>`` overrides
    (``on`` / ``off``, or ``model`` to send nothing and keep the model's own).

    Reasoning tokens count against ``max_tokens`` and come back outside
    ``content``. Live, slot-fill at 256 returned 256 reasoning tokens and an
    empty reply on every call - the budget was spent before the answer began.
    """
    raw = (os.environ.get(f"NGE_THINKING_{call_class.upper()}") or "").strip().lower()
    if raw in _ON:
        return True
    if raw in _OFF:
        return False
    if raw == "model":
        return None
    return THINKING_DEFAULTS.get(call_class)


def _reasoning_tokens(usage: dict) -> Optional[int]:
    details = usage.get("completion_tokens_details") or {}
    val = details.get("reasoning_tokens")
    try:
        return None if val is None else int(val)
    except (TypeError, ValueError):
        return None


def _chat_nebius_http(messages: list, model_id: str, tools: Optional[list],
                      url: str, api_key: str, max_tokens: int,
                      thinking: Optional[bool] = None) -> dict:
    """POST chat/completions with max_tokens; record usage; return message."""
    import nodus_backends as nb  # vendored normaliser only

    payload: dict = {
        "model": model_id,
        "messages": messages,
        "stream": False,
        "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = tools
    if thinking is not None:
        # A system "/no_think" is ignored by Token Factory's Nemotron 3; the
        # chat template switch is what actually stops the reasoning.
        payload["chat_template_kwargs"] = {"enable_thinking": bool(thinking)}
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(url, json=payload, headers=headers,
                             timeout=nb.API_TIMEOUT)
    except requests.RequestException as exc:
        raise ModelUnavailableError(model_id, None, str(exc)) from exc

    if resp.status_code == 429 or resp.status_code >= 500:
        raise ModelUnavailableError(
            model_id, resp.status_code, (resp.text or "")[:200])
    # Unknown / wrong id often returns 404 — treat as unavailable for failover.
    if resp.status_code == 404:
        raise ModelUnavailableError(
            model_id, 404, (resp.text or "")[:200])

    resp.raise_for_status()
    data = resp.json()
    usage = data.get("usage") or {}
    pin = usage.get("prompt_tokens")
    pout = usage.get("completion_tokens")
    if pin is not None:
        try:
            pin = int(pin)
        except (TypeError, ValueError):
            pin = None
    if pout is not None:
        try:
            pout = int(pout)
        except (TypeError, ValueError):
            pout = None
    reasoning = _reasoning_tokens(usage)
    _usage.record(model_id, pin, pout, max_tokens, reasoning_tokens=reasoning,
                  thinking=thinking)
    msg = nb._normalize_openai_message(data)
    choices = data.get("choices") or []
    if choices:
        fr = choices[0].get("finish_reason")
        if fr:
            msg["finish_reason"] = fr
    if reasoning is not None:
        msg["reasoning_tokens"] = reasoning
    return msg


def chat_nebius(messages: list, model: str, tools: Optional[list] = None,
                max_tokens: Optional[int] = None,
                thinking: Optional[bool] = None) -> dict:
    """One chat turn against Nebius Token Factory. Returns an Ollama-style message."""
    assert_nebius_track(model)
    cfg = _cfg.load()
    api_key = cfg.nebius_api_key()
    if not api_key:
        raise RuntimeError(
            "Nebius API key missing - create packages/engine/.nebius_api_key "
            "or set NEBIUS_API_KEY"
        )
    cap = resolve_max_tokens(max_tokens)
    return _chat_nebius_http(
        messages, nebius_model_id(model), tools,
        cfg.nebius_chat_url, api_key, cap, thinking=thinking,
    )


def nemotron_plan_fallback(task: str, allowed_tools: List[str]) -> Optional[List[str]]:
    """Ask Nemotron for an ordered tool-name plan when the 324M planner cannot.

    Only reached with ``NGE_PLAN_FALLBACK=nemotron``. Names outside
    ``allowed_tools`` are dropped.
    """
    from nge import llm_text

    prompt = (
        "You plan tool steps for a coding agent.\n"
        "Reply with ONLY a JSON array of tool names in order, no prose.\n"
        f"Allowed tools: {', '.join(allowed_tools)}\n"
        f"Task: {task}"
    )
    try:
        msg = chat_nebius([{"role": "user", "content": prompt}],
                          _cfg.load().nemotron_model, None,
                          max_tokens=SLOT_MAX_TOKENS,
                          thinking=resolve_thinking("short"))
    except Exception:
        return None

    names = llm_text.json_array(msg)
    if not names or not all(isinstance(n, str) for n in names):
        return None
    kept = [n for n in names if n in allowed_tools]
    return kept or None
