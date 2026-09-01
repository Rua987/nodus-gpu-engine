"""Plan step = ordered tool names (the Nodus "brain / DSL").

Tries the vendored local 324M planner first
(``nodus_plan_local.try_plan_tool_names`` -> names, or ``None`` when it declines
or torch/checkpoint is absent). Falls back to a deterministic keyword heuristic,
and optionally to Nemotron (skeleton) when ``NGE_PLAN_FALLBACK=nemotron``.

Vocabulary is the fixed 8-tool coding set the 324M model was trained on. GPU /
fleet / sandbox steps are NOT planned here - the orchestrator wraps them
deterministically around this plan.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional

CODING_TOOLS = ["bash", "read_file", "write_file", "edit_file",
                "glob", "grep", "web_fetch", "brave_search"]


@dataclass
class PlanResult:
    names: List[str]
    source: str            # nodus-324m | heuristic | nemotron | heuristic(after-nemotron)
    note: str = ""


def _heuristic(task: str) -> List[str]:
    t = task.lower()
    names: List[str] = []
    if any(w in t for w in ("find", "locate", "search for file", "list", "which file")):
        names.append("glob")
    if any(w in t for w in ("test", "pytest", "run", "suite", "triage", "failing")):
        names.append("bash")
    if any(w in t for w in ("read", "inspect", "look at", "open")):
        names.append("read_file")
    if any(w in t for w in ("fix", "edit", "change", "patch", "update")):
        names.append("edit_file")
    if any(w in t for w in ("report", "write", "deliver", "summar", "consolidat")):
        names.append("write_file")
    if any(w in t for w in ("http", "url", "fetch", "download")):
        names.append("web_fetch")
    return names or ["bash", "write_file"]


def plan(task: str, allow_nemotron: Optional[bool] = None) -> PlanResult:
    # 1) local 324M planner (vendored)
    try:
        from nodus_plan_local import try_plan_tool_names
        names = try_plan_tool_names(task)
        if names:
            return PlanResult(names=list(names), source="nodus-324m")
    except Exception as exc:  # missing torch / checkpoint / import path
        note = f"local planner unavailable: {type(exc).__name__}"
    else:
        note = "local planner declined (label != valid)"

    # 2) optional Nemotron fallback (skeleton)
    if allow_nemotron is None:
        allow_nemotron = os.environ.get("NGE_PLAN_FALLBACK", "").lower() == "nemotron"
    if allow_nemotron:
        try:
            from nge.backends.nebius import nemotron_plan_fallback
            names = nemotron_plan_fallback(task, CODING_TOOLS)
            if names:
                return PlanResult(names=names, source="nemotron", note=note)
        except Exception as exc:
            note = f"{note}; nemotron fallback failed: {type(exc).__name__}"

    # 3) deterministic heuristic
    return PlanResult(names=_heuristic(task), source="heuristic", note=note)
