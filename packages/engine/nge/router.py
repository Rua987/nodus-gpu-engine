"""Nemotron tier router - the right model for the right decision.

The pitch: *don't call one model for everything*. Reasoning-heavy, rare
decisions go to the big model; the fast background chatter goes to the small one.

    ultra  (Nemotron 3 Ultra 550b)  - planning, orchestration decisions
    super  (Nemotron 3 Super 120b)  - argument slot-fill, failure triage  [default]
    nano   (Nemotron 3 Nano 30b)    - telemetry digests, quick classification

``model_for(decision, cfg)`` returns the concrete ``nebius:...`` id so it can be
handed straight to ``chat_fn(messages, model, tools)``.
"""
from __future__ import annotations

from typing import Dict

# decision kind -> tier
ROUTING: Dict[str, str] = {
    "plan": "ultra",
    "orchestrate": "ultra",
    "replan": "ultra",
    "slotfill": "super",
    "triage": "super",
    "telemetry_digest": "nano",
    "classify": "nano",
    "healthcheck": "nano",
}

DEFAULT_TIER = "super"


def tier_for(decision: str) -> str:
    return ROUTING.get(decision, DEFAULT_TIER)


def model_for(decision: str, cfg) -> str:
    tier = tier_for(decision)
    return {
        "ultra": cfg.nemotron_ultra,
        "super": cfg.nemotron_super,
        "nano": cfg.nemotron_nano,
    }[tier]


def route(decision: str, cfg) -> dict:
    """Full routing record for the event log / report."""
    tier = tier_for(decision)
    return {"decision": decision, "tier": tier, "model": model_for(decision, cfg)}
