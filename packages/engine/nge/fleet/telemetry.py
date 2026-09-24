"""Thermal / efficiency heuristics for fleet nodes.

A deliberately small, importable port of the ideas in ``packages/gpu-agents``
(three-tier thermal management: safety cutoff, warm band, efficiency zone).
The RTX-specific code there depends on ``nvidia-smi`` and Windows; here we keep
only the pure scoring so it runs anywhere and stays deterministic.

**Probe honesty:** Token Factory microVMs often have *no* NVIDIA driver. Their
CPU fallback reports temp=0 / power=0 — that is a *setup*, not a failed H100.
Callers must gate remediations on ``probe_kind`` (see ``has_real_gpu_metrics``).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

# Data-centre GPU thresholds (H100 / A100 / L40 class).
_DATACENTER = {"throttle_c": 87.0, "warm_c": 78.0, "power_cap_w": 700.0}
# Consumer / workstation (RTX 40xx-class ballpark — not identical SKUs).
_CONSUMER = {"throttle_c": 83.0, "warm_c": 75.0, "power_cap_w": 450.0}

# Back-compat aliases used by older tests / imports
TEMP_THROTTLE_C = _DATACENTER["throttle_c"]
TEMP_WARM_C = _DATACENTER["warm_c"]
POWER_CAP_W = _DATACENTER["power_cap_w"]

PROBE_NVIDIA = "nvidia-smi"
PROBE_CPU = "cpu-fallback"
PROBE_SYNTHETIC = "synthetic"   # MockFleet demo
PROBE_FAILED = "failed"

CLASS_DATACENTER = "datacenter"
CLASS_CONSUMER = "consumer"
CLASS_NONE = "none"
CLASS_SYNTHETIC = "synthetic"


def thresholds_for(gpu_class: str) -> Dict[str, float]:
    if gpu_class == CLASS_CONSUMER:
        return dict(_CONSUMER)
    return dict(_DATACENTER)


def gpu_class_from_name(name: Optional[str]) -> str:
    """Map an ``nvidia-smi`` product name to a coarse class."""
    n = (name or "").strip().lower()
    if not n:
        return CLASS_DATACENTER
    if any(k in n for k in ("geforce", "rtx", "gtx", "quadro")):
        return CLASS_CONSUMER
    if any(k in n for k in ("h100", "h200", "a100", "a10", "l40", "l4", "v100",
                            "tesla", "b200", "gb200")):
        return CLASS_DATACENTER
    return CLASS_DATACENTER


def has_real_gpu_metrics(tele: Optional[Dict[str, Any]]) -> bool:
    """True when metrics come from nvidia-smi (or a synthetic demo GPU)."""
    if not tele:
        return False
    return tele.get("probe_kind") in (PROBE_NVIDIA, PROBE_SYNTHETIC)


def health_from_metrics(temp_c: float, util_pct: float, power_w: float,
                        gpu_class: str = CLASS_DATACENTER) -> str:
    """safety tier -> warm tier -> efficiency tier (mirrors gpu-agents)."""
    th = thresholds_for(gpu_class)
    if temp_c >= th["throttle_c"] or power_w >= th["power_cap_w"]:
        return "throttle"
    if temp_c >= th["warm_c"]:
        return "warm"
    return "ok"


def efficiency_score(util_pct: float, power_w: float,
                     gpu_class: str = CLASS_DATACENTER) -> float:
    """Useful work per watt, normalised to ~0..1."""
    cap = thresholds_for(gpu_class)["power_cap_w"]
    if power_w <= 0:
        return 0.0
    raw = (util_pct / 100.0) / (power_w / cap)
    return round(max(0.0, min(raw, 1.0)), 3)
