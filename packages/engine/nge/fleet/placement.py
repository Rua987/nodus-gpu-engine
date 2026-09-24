"""Pick a GPU destination before migrating a shard (don't move fire → fire).

Pure scoring over telemetry dicts / :class:`GpuNodeStatus` asdicts.
No provision / API calls here — the orchestrator supplies candidates.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence


# Refuse destinations that are already in the danger band.
_REFUSE_HEALTH = frozenset({"throttle", "unknown"})


@dataclass(frozen=True)
class WorkloadNeeds:
    """What the shard about to move roughly needs."""
    min_mem_free_gb: float = 8.0
    max_temp_c: float = 78.0          # prefer at/below warm threshold
    max_util_pct: float = 85.0
    allow_warm: bool = False          # if False, health must be ok


@dataclass(frozen=True)
class PlacementDecision:
    node_id: Optional[str]
    score: float
    reason: str
    refused: List[str]                # node ids skipped + why (short)


def _f(row: Dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def mem_free_gb(row: Dict[str, Any]) -> float:
    return max(0.0, _f(row, "mem_total_gb") - _f(row, "mem_used_gb"))


def eligible(row: Dict[str, Any], needs: WorkloadNeeds) -> Optional[str]:
    """Return None if OK, else a short refusal reason."""
    state = (row.get("state") or "").lower()
    if state and state not in ("ready",):
        return f"state={state}"
    health = (row.get("health") or "unknown").lower()
    if health in _REFUSE_HEALTH:
        return f"health={health}"
    if health == "warm" and not needs.allow_warm:
        return "health=warm"
    if _f(row, "temp_c") > needs.max_temp_c:
        return f"temp={_f(row, 'temp_c'):.1f}>max"
    if mem_free_gb(row) < needs.min_mem_free_gb:
        return f"mem_free={mem_free_gb(row):.1f}<need"
    if _f(row, "util_pct") > needs.max_util_pct:
        return f"util={_f(row, 'util_pct'):.1f}>max"
    return None


def score_candidate(row: Dict[str, Any], needs: WorkloadNeeds) -> float:
    """Higher = better destination. Ineligible rows should not be scored."""
    # Cooler, more free mem, lower util, higher efficiency.
    temp = _f(row, "temp_c")
    util = _f(row, "util_pct")
    free = mem_free_gb(row)
    eff = _f(row, "efficiency", 0.5)
    # Normalize roughly into a single score.
    return (
        (needs.max_temp_c - temp) * 2.0
        + free * 0.5
        + (needs.max_util_pct - util) * 0.3
        + eff * 10.0
    )


def pick_replacement(
    candidates: Sequence[Dict[str, Any]],
    needs: Optional[WorkloadNeeds] = None,
    exclude_ids: Optional[Sequence[str]] = None,
) -> PlacementDecision:
    """Choose the best ready node that fits ``needs``.

    Analogy: before moving a victim out of a burning house, check which
    neighbouring house is cool, has room, and isn't already crowded.
    """
    needs = needs or WorkloadNeeds()
    exclude = set(exclude_ids or ())
    refused: List[str] = []
    best_id: Optional[str] = None
    best_score = float("-inf")

    for row in candidates:
        nid = str(row.get("id") or "")
        if not nid or nid in exclude:
            continue
        why = eligible(row, needs)
        if why:
            refused.append(f"{nid}:{why}")
            continue
        sc = score_candidate(row, needs)
        if sc > best_score:
            best_score = sc
            best_id = nid

    if best_id is None:
        return PlacementDecision(
            node_id=None, score=0.0,
            reason="no eligible destination (would move fire to fire)",
            refused=refused,
        )
    return PlacementDecision(
        node_id=best_id, score=round(best_score, 2),
        reason="coolest fit with free mem / headroom",
        refused=refused,
    )
