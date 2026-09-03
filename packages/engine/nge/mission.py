"""Turn an engineer's natural-language mission into a run scenario.

The engineer expresses the *what*:

    nge run --mission "Run my pytest suite in ./tests/unit across 3 H100s
                       and self-heal if a node throttles"

and this maps it to the *how* (the scenario dict the orchestrator consumes):
shard count, GPU type, target path, artifacts, self-heal intent. Deterministic
and testable; ``--live`` can later route the mission through Nemotron Ultra for
richer extraction, but the structured fields below cover the common shapes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

_GPU_RE = re.compile(r"\b(H100|A100|L40S|H200|GB200)s?\b", re.I)
_COUNT_RE = re.compile(
    r"(\d+)\s*(?:x\s*)?(?:H100|A100|L40S|H200|GB200|gpus?|nodes?|workers?|"
    r"instances?|shards?|replicas?)\b", re.I)
_ACROSS_RE = re.compile(r"\bacross\s+(\d+)\b", re.I)
_PATH_RE = re.compile(r"(?:\bin\s+|\bat\s+|\bfrom\s+|`)(\.?/?[\w./-]+/[\w./*-]+)")
_ARTIFACT_RE = re.compile(r"\b([\w./-]+\.(?:xml|md|json|txt|html|log))\b", re.I)

_SELF_HEAL = ("self-heal", "self heal", "auto-repair", "auto repair", "auto-migrate",
              "migrate", "throttl", "reallocat", "move them", "s'auto", "auto-migre")
_NO_FIX = ("no fix", "don't fix", "do not fix", "skip fix", "report only",
           "just report", "no patch")


@dataclass
class Mission:
    task: str
    shards: int = 3
    gpu_type: str = "H100"
    target: str = "packages/nodus/tests"
    collect: List[str] = field(default_factory=list)
    self_heal: bool = True
    auto_fix: bool = True
    derived: List[str] = field(default_factory=list)

    def scenario(self) -> dict:
        return {"name": "mission", "task": self.task, "shards": self.shards,
                "gpu_type": self.gpu_type, "target": self.target,
                "collect": self.collect}


def parse_mission(text: str) -> Mission:
    t = (text or "").strip()
    if not t:
        raise ValueError("empty mission")
    low = t.lower()
    m = Mission(task=t)
    why: List[str] = []

    gm = _GPU_RE.search(t)
    if gm:
        m.gpu_type = gm.group(1).upper()
        why.append(f"gpu={m.gpu_type} (named)")

    cm = _COUNT_RE.search(t) or _ACROSS_RE.search(t)
    if cm:
        n = int(cm.group(1))
        if 1 <= n <= 64:
            m.shards = n
            why.append(f"{n} shards (from {cm.group(0).strip()!r})")

    pm = _PATH_RE.search(t)
    if pm:
        m.target = pm.group(1).strip("`")
        why.append(f"target={m.target}")

    arts = _ARTIFACT_RE.findall(t)
    if arts:
        m.collect = sorted(set(arts))
        why.append(f"collect={m.collect}")

    if any(k in low for k in _SELF_HEAL):
        m.self_heal = True
        why.append("self-heal=on (explicit)")
    if any(k in low for k in _NO_FIX):
        m.auto_fix = False
        why.append("auto-fix=off (report-only)")

    m.derived = why or ["defaults (nothing structured extracted)"]
    return m
