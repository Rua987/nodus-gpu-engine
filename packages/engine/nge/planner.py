"""Plan step = ordered tool names (the Nodus "brain / DSL").

Tries the vendored local 324M planner first, falls back to a deterministic
keyword heuristic, and optionally to Nemotron when ``NGE_PLAN_FALLBACK=nemotron``.

The fallback used to be *silent*: with no checkpoint on disk
``try_plan_tool_names`` returns ``None`` without raising, so every run quietly
planned with ``_heuristic`` - fifteen lines of hand-written keyword matching -
while reporting a vague "declined". Every demo printed ``plan(heuristic)`` and
nobody noticed the 324M model had never run. So:

* the checkpoint is resolved and **existence-checked here**, and a missing file
  says so, naming the path it looked for and how to point at another one;
* ``PlanResult.degraded`` is True whenever the real planner did not produce the
  plan, so callers (demo, report, event log) can say it out loud instead of
  printing a source name nobody reads.

Vocabulary is the fixed 8-tool coding set the 324M model was trained on. GPU /
fleet / sandbox steps are NOT planned here - the orchestrator wraps them
deterministically around this plan.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

CODING_TOOLS = ["bash", "read_file", "write_file", "edit_file",
                "glob", "grep", "web_fetch", "brave_search"]

# where the vendored planner keeps its weights when nothing overrides it
_NODUS_DIR = Path(__file__).resolve().parents[2] / "nodus"
DEFAULT_CKPT = _NODUS_DIR / "checkpoints" / "checkpoint_sft_plan_v5.pt"


@dataclass
class PlanResult:
    names: List[str]
    source: str             # nodus-324m | heuristic | nemotron
    note: str = ""
    degraded: bool = False  # True when the 324M planner did not produce this


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


def have_torch() -> bool:
    """Whether the planner's runtime dependency is importable.

    A named function rather than an inline try/import so tests can state the
    answer directly. Mocking the import machinery instead made three tests
    pass on a machine with torch and fail in CI without it - the failure that
    turned the whole matrix red.
    """
    try:
        import torch  # noqa: F401
        return True
    except Exception:
        return False


def resolve_ckpt(config=None) -> Path:
    """Checkpoint path: config value, then ``$NODUS_PLAN_CKPT``, then the
    vendored default. Returned whether or not it exists."""
    raw = ""
    if config is not None:
        raw = (getattr(config, "nodus_plan_ckpt", "") or "").strip()
    if not raw:
        raw = (os.environ.get("NODUS_PLAN_CKPT") or "").strip()
    return Path(raw).expanduser() if raw else DEFAULT_CKPT


# Checkpoint path that ``--heuristic-plan`` sets on purpose. Without its own
# note, the judge film opened on "324M planner checkpoint NOT FOUND at
# __nge_force_heuristic__/missing.pt" - in the terminal and in the HTML report -
# while the weights were on disk and simply not consulted.
FORCE_HEURISTIC = "__nge_force_heuristic__"
FORCED_NOTE = ("keyword heuristic requested (--heuristic-plan); the 324M "
               "checkpoint is not consulted")


def heuristic_forced(config=None) -> bool:
    return FORCE_HEURISTIC in resolve_ckpt(config).parts


def ckpt_status(config=None) -> Tuple[Path, bool, str]:
    """``(path, exists, human note)`` - lets a caller warn before a run."""
    p = resolve_ckpt(config)
    if FORCE_HEURISTIC in p.parts:
        return p, False, FORCED_NOTE
    try:
        if p.is_file():
            return p, True, f"324M planner: {p.name} ({p.stat().st_size / 1e6:.0f} MB)"
    except OSError:
        pass
    return p, False, (
        f"324M planner checkpoint NOT FOUND at {p} - planning falls back to the "
        f"hand-written keyword heuristic. Point at the weights with "
        f"NODUS_PLAN_CKPT=/path/to/checkpoint_sft_plan_v5.pt, or write that path "
        f"into packages/engine/.nodus_plan_ckpt")


def plan(task: str, allow_nemotron: Optional[bool] = None,
         config=None) -> PlanResult:
    ckpt, exists, note = ckpt_status(config)

    # 1) local 324M planner - only when the weights are actually on disk
    if exists:
        # torch is an optional extra (see requirements.txt). Without it the
        # planner cannot load at all, and try_plan_tool_names returns None the
        # same way it does for a declined task - so check first rather than
        # report "declined" for a model that never ran.
        if not have_torch():
            note = ("324M planner cannot run: torch is not installed "
                    "(`pip install torch`); using the hand-written keyword "
                    "heuristic")
        else:
            try:
                from nodus_plan_local import try_plan_tool_names
                names = try_plan_tool_names(task, ckpt_path=str(ckpt))
                if names:
                    return PlanResult(names=list(names), source="nodus-324m",
                                      note=f"planned by 324M ({ckpt.name})")
                # None means declined OR invalid OR failed to load - the
                # vendored helper does not distinguish, so neither do we
                note = ("324M planner returned no plan (declined the task, or "
                        "failed to load the checkpoint); using the "
                        "hand-written keyword heuristic")
            except Exception as exc:
                note = (f"324M planner failed to run: {type(exc).__name__}: "
                        f"{exc}; using the hand-written keyword heuristic")

    # 2) optional Nemotron fallback
    if allow_nemotron is None:
        allow_nemotron = os.environ.get("NGE_PLAN_FALLBACK", "").lower() == "nemotron"
    if allow_nemotron:
        try:
            from nge.backends.nebius import nemotron_plan_fallback
            names = nemotron_plan_fallback(task, CODING_TOOLS)
            if names:
                return PlanResult(names=names, source="nemotron", note=note,
                                  degraded=True)
        except Exception as exc:
            note = f"{note}; nemotron fallback failed: {type(exc).__name__}"

    # 3) deterministic heuristic - hand-written, and now labelled as such
    return PlanResult(names=_heuristic(task), source="heuristic", note=note,
                      degraded=True)
