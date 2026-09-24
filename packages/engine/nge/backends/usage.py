# -*- coding: utf-8 -*-
"""Process-wide Nemotron / Nebius usage ledger.

Tracks **billed** chat calls (tokens when the API sends ``usage``), plus
router hits and failovers so we can see whether Ultra/Nano are actually
invoked or only *routed*.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Rough TF list rates HT $/MTok — label as estimate, not an invoice.
# Rough TF list rates HT $/MTok — label as estimate, not an invoice.
_EST = {
    "ultra": {"in": 1.00, "out": 3.00},
    "super": {"in": 0.30, "out": 0.90},
    "nano":  {"in": 0.10, "out": 0.30},  # if listed; else still label estimate
}

_ledger: Dict[str, Dict[str, Any]] = {}
_routes: Dict[str, int] = {}          # tier -> route events (may be chat-less)
_errors: Dict[str, int] = {}          # model id -> unavailable/errors
_failovers = 0                        # count of nano/ultra → super hops
_jsonl_path: Optional[Path] = None


def reset_usage() -> None:
    _ledger.clear()
    _routes.clear()
    _errors.clear()
    global _failovers
    _failovers = 0


def set_jsonl_path(path: Optional[Path]) -> None:
    global _jsonl_path
    _jsonl_path = path


def guess_tier(model: str) -> str:
    m = (model or "").lower()
    if "ultra" in m:
        return "ultra"
    if "nano" in m:
        return "nano"
    if "super" in m:
        return "super"
    return "?"


def record_route(tier: str, decision: str = "") -> None:
    t = (tier or "?").strip() or "?"
    _routes[t] = _routes.get(t, 0) + 1
    _append_jsonl({"kind": "route", "tier": t, "decision": decision})


def record_error(model: str, status: Optional[int] = None) -> None:
    mid = (model or "").strip() or "?"
    _errors[mid] = _errors.get(mid, 0) + 1
    _append_jsonl({"kind": "error", "model": mid, "status": status})


def record_failover(from_model: str, to_model: str, decision: str = "") -> None:
    global _failovers
    _failovers += 1
    _append_jsonl({
        "kind": "failover", "from": from_model, "to": to_model,
        "decision": decision,
    })


def record(model: str, prompt_tokens: Optional[int],
           completion_tokens: Optional[int], max_tokens: int) -> None:
    mid = (model or "").strip() or "?"
    row = _ledger.setdefault(mid, {
        "calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
        "prompt_unknown": 0, "completion_unknown": 0,
        "tier": guess_tier(mid),
    })
    row["calls"] += 1
    if prompt_tokens is None:
        row["prompt_unknown"] += 1
    else:
        row["prompt_tokens"] += int(prompt_tokens)
    if completion_tokens is None:
        row["completion_unknown"] += 1
    else:
        row["completion_tokens"] += int(completion_tokens)
    _append_jsonl({
        "kind": "chat", "model": mid, "tier": row["tier"],
        "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
        "max_tokens": max_tokens,
    })


def _append_jsonl(evt: dict) -> None:
    if _jsonl_path is None:
        return
    try:
        _jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        evt = {"t": round(time.time(), 3), **evt}
        with _jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(evt, ensure_ascii=False) + "\n")
    except OSError:
        pass


def snapshot() -> Dict[str, Dict[str, Any]]:
    return {k: dict(v) for k, v in _ledger.items()}


def routes_snapshot() -> Dict[str, int]:
    return dict(_routes)


def errors_snapshot() -> Dict[str, int]:
    return dict(_errors)


def failover_count() -> int:
    return _failovers


def estimate_usd_ht(prompt_tokens: int, completion_tokens: int,
                    tier: str = "super") -> float:
    rates = _EST.get(tier) or _EST["super"]
    return (prompt_tokens / 1e6) * rates["in"] + (
        completion_tokens / 1e6) * rates["out"]


def format_summary() -> str:
    """Concise: per billed model + route hits without chat + failovers."""
    rows = snapshot()
    lines: List[str] = ["[usage] billed chats (tier≈id) | routes may have no chat"]
    tin = tout = tcalls = 0
    est_total = 0.0
    for model, r in sorted(rows.items()):
        pin, pout, calls = r["prompt_tokens"], r["completion_tokens"], r["calls"]
        tin += pin
        tout += pout
        tcalls += calls
        tier = r.get("tier") or guess_tier(model)
        est = estimate_usd_ht(pin, pout, tier)
        est_total += est
        short = model.split("/")[-1] if "/" in model else model
        err = _errors.get(model, 0)
        err_s = f"  err={err}" if err else ""
        lines.append(
            f"[usage] {tier:<5} {short}  calls={calls}  in={pin}  out={pout}  "
            f"~${est:.4f}{err_s}")
    # Routes with zero chats (e.g. plan→ultra but 324M ran)
    billed_tiers = {guess_tier(m) for m in rows}
    for tier, n in sorted(_routes.items()):
        if tier not in billed_tiers or n > sum(
                r["calls"] for m, r in rows.items() if guess_tier(m) == tier):
            chat_n = sum(r["calls"] for m, r in rows.items() if guess_tier(m) == tier)
            if n > chat_n:
                lines.append(
                    f"[usage] {tier:<5} routed={n}  chat={chat_n}  "
                    f"(gap={n - chat_n} route-only)")
    if _failovers:
        lines.append(f"[usage] failover→super  count={_failovers}")
    if _errors and not rows:
        for mid, n in sorted(_errors.items()):
            lines.append(f"[usage] err {mid}  count={n}")
    if not rows and not _routes:
        return "[usage] (no nebius: calls this process)"
    lines.append(
        f"[usage] TOTAL  calls={tcalls}  in={tin}  out={tout}  "
        f"~${est_total:.4f} HT est (not invoice)")
    return "\n".join(lines)
