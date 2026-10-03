"""Cause / urgency notes for auto-fixes (symptoms → why kept or skipped).

Not a medical diagnosis and not an LLM essay: deterministic tags from the
failure error, heuristic hint, and verify outcome — so a human can see
*fragility* (your bearing → ball-joint → engine-mount chain) before the next
patch.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence


def _file_of(test: str) -> str:
    return (test or "").split("::")[0]


def cluster_size(test: str, all_failures: Sequence[dict]) -> int:
    """How many unique failures share this test file (fragility signal)."""
    root = _file_of(test)
    if not root:
        return 1
    return sum(1 for f in all_failures if _file_of(f.get("test", "")) == root)


def urgency_for(*, verified: bool, has_patch: bool, reason: str,
                regressions: Optional[List[str]] = None,
                same_file_failures: int = 1) -> str:
    """low | medium | high — triage priority, not a SLA."""
    reason = (reason or "").lower()
    if regressions:
        return "high"          # patch hurt neighbours = systemic risk
    if "still failing" in reason or "broke " in reason:
        return "high"
    if "no output" in reason or "blocked" in reason:
        return "high"
    if not has_patch or "no patch" in reason or "context" in reason:
        # unknown fix path — watch this module
        return "medium" if same_file_failures <= 1 else "high"
    if verified:
        # fixed, but a crowded file means the area is still fragile
        return "medium" if same_file_failures >= 2 else "low"
    return "medium"


def annotate_fix(
    failure: dict,
    *,
    reason: str,
    verified: bool,
    has_patch: bool,
    regressions: Optional[List[str]] = None,
    all_failures: Optional[Sequence[dict]] = None,
) -> Dict[str, Any]:
    """Fields to merge into a fix record for reports."""
    all_failures = all_failures or []
    symptom = (failure.get("error") or "").strip()
    # the sentences below add their own full stop; hints usually end in one
    hint = (failure.get("proposed_fix") or "").strip().rstrip(".")
    n = cluster_size(failure.get("test", ""), all_failures)
    urg = urgency_for(
        verified=verified, has_patch=has_patch, reason=reason or "",
        regressions=regressions, same_file_failures=n,
    )
    # Human-readable chain (analogy: symptom → likely area → urgency)
    if verified and has_patch:
        why = (reason or "re-tested green in a fresh sandbox")
        cause = (
            f"Symptom: {symptom[:160]}. "
            f"Action: patch applied and suite stayed green. "
            f"Hint was: {hint or '(none)'}."
        )
    elif not has_patch:
        why = reason or "no patch proposed"
        cause = (
            f"Symptom: {symptom[:160]}. "
            f"No patch produced — cannot clear the symptom yet. "
            f"Hint: {hint or '(none)'}."
        )
    else:
        why = reason or "patch rejected"
        cause = (
            f"Symptom: {symptom[:160]}. "
            f"Patch tried but not kept ({why}). "
            f"Hint: {hint or '(none)'}."
        )
    fragility = (
        f"same file has {n} failing test(s)" if n > 1
        else "single failure in this file"
    )
    return {
        "reason": why,
        "symptom": symptom[:300],
        "hint": hint,
        "cause": cause,
        "urgency": urg,
        "fragility": fragility,
        "same_file_failures": n,
    }
