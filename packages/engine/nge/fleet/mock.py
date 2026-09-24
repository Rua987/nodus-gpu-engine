"""Deterministic GPU fleet - synthetic but plausible telemetry.

Node metrics are a pure function of (node index, poll tick), so a demo run and
a CI run produce identical numbers. No credentials, no network.
"""
from __future__ import annotations

import hashlib
from typing import List, Optional

from nge.fleet.base import GpuFleet, GpuNode, GpuNodeStatus
from nge.fleet import telemetry

_MEM_TOTAL_GB = {"H100": 80.0, "A100": 40.0, "L40S": 48.0}


def _wave(*parts, lo: float, hi: float) -> float:
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    frac = int(h[:8], 16) / 0xFFFFFFFF
    return round(lo + frac * (hi - lo), 1)


class MockFleet(GpuFleet):
    mode = "mock"

    def __init__(self) -> None:
        self._nodes: List[GpuNode] = []
        self._hot: set = set()          # ids that run in a "bad rack"
        self._next = 0                  # monotonic id counter (never reused)
        self._tick = 0

    # -- lifecycle ------------------------------------------------------------
    def provision(self, n: int, gpu_type: str = "H100") -> List[GpuNode]:
        first_batch = self._next == 0
        new = []
        for i in range(max(0, int(n))):
            node = GpuNode(id=f"nb-{gpu_type.lower()}-{self._next:02d}", gpu_type=gpu_type,
                           region="eu-north1", state="ready")
            self._next += 1
            # Deterministic "bad rack": in the FIRST provisioning batch, every
            # 3rd node runs hot -> throttles under load, so the orchestrator
            # feedback loop has something real to react to. Replacement / fix
            # nodes provisioned later are always healthy.
            if first_batch and (i % 3 == 2):
                self._hot.add(node.id)
            new.append(node)
        self._nodes.extend(new)
        return list(new)

    def allocate(self, job: str, node_id: Optional[str] = None) -> GpuNode:
        if node_id:
            for node in self._nodes:
                if node.id == node_id and node.state == "ready":
                    node.state = "allocated"
                    node.job = job
                    return node
            raise RuntimeError(f"node {node_id!r} not ready for allocate")
        for node in self._nodes:
            if node.state == "ready":
                node.state = "allocated"
                node.job = job
                return node
        raise RuntimeError("no ready node in fleet - call gpu_provision first")

    def release(self, node_ids: Optional[List[str]] = None) -> List[str]:
        target = set(node_ids) if node_ids else {n.id for n in self._nodes}
        released = []
        for node in self._nodes:
            if node.id in target and node.state != "gone":
                node.state = "gone"
                node.job = None
                released.append(node.id)
        self._nodes = [n for n in self._nodes if n.state != "gone"]
        return released

    # -- monitoring ---------------------------------------------------------
    def status(self, node_id: Optional[str] = None) -> List[GpuNodeStatus]:
        self._tick += 1
        out: List[GpuNodeStatus] = []
        for idx, node in enumerate(self._nodes):
            if node_id and node.id != node_id:
                continue
            busy = node.state == "allocated"
            hot = node.id in self._hot and busy
            util = _wave(node.id, self._tick, "util", lo=55 if busy else 1,
                         hi=99 if busy else 8)
            power = _wave(node.id, self._tick, "pow",
                          lo=705 if hot else (380 if busy else 90),
                          hi=735 if hot else (690 if busy else 140))
            temp = _wave(node.id, self._tick, "temp",
                         lo=88 if hot else (62 if busy else 34),
                         hi=95 if hot else (86 if busy else 45))
            mem_total = _MEM_TOTAL_GB.get(node.gpu_type, 80.0)
            mem_used = _wave(node.id, self._tick, "mem", lo=8, hi=mem_total * 0.95)
            out.append(GpuNodeStatus(
                id=node.id, state=node.state, util_pct=util,
                mem_used_gb=mem_used, mem_total_gb=mem_total, temp_c=temp,
                power_w=power, health=telemetry.health_from_metrics(temp, util, power),
                efficiency=telemetry.efficiency_score(util, power),
                probe_kind=telemetry.PROBE_SYNTHETIC,
                gpu_class=telemetry.CLASS_SYNTHETIC,
                gpu_name=f"mock-{node.gpu_type}",
            ))
        return out

    # -- test helper ------------------------------------------------------
    def nodes(self) -> List[GpuNode]:
        return list(self._nodes)
