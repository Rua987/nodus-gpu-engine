"""Thermal / efficiency heuristics for fleet nodes.

A deliberately small, importable port of the ideas in ``packages/gpu-agents``
(three-tier thermal management: safety cutoff, warm band, efficiency zone).
The RTX-specific code there depends on ``nvidia-smi`` and Windows; here we keep
only the pure scoring so it runs anywhere and stays deterministic.
"""
from __future__ import annotations

# Data-centre GPU thresholds (H100/A100 class), not RTX gaming cards.
TEMP_THROTTLE_C = 87.0
TEMP_WARM_C = 78.0
POWER_CAP_W = 700.0


def health_from_metrics(temp_c: float, util_pct: float, power_w: float) -> str:
    """safety tier -> warm tier -> efficiency tier (mirrors gpu-agents)."""
    if temp_c >= TEMP_THROTTLE_C or power_w >= POWER_CAP_W:
        return "throttle"
    if temp_c >= TEMP_WARM_C:
        return "warm"
    return "ok"


def efficiency_score(util_pct: float, power_w: float) -> float:
    """Useful work per watt, normalised to ~0..1.

    High utilisation at moderate power scores best; idle-but-hot or
    power-capped nodes score low. Same spirit as gpu-agents'
    ``performance_scorer`` / ``sweet_spot_finder``.
    """
    if power_w <= 0:
        return 0.0
    raw = (util_pct / 100.0) / (power_w / POWER_CAP_W)
    return round(max(0.0, min(raw, 1.0)), 3)
