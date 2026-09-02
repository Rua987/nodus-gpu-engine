"""Nebius GPU fleet, backed by Token Factory sandbox sessions (ConTree SDK).

Each fleet node is a ConTree session (its own microVM). ``status()`` runs a
telemetry probe *inside* the node and parses it:

  - if ``nvidia-smi`` is present  -> real GPU util / mem / temp / power
  - otherwise                     -> CPU-side reading (loadavg, free) mapped
                                     into the same GpuNodeStatus shape

Signature-compatible with :class:`nge.fleet.mock.MockFleet`. Shares
``nge.nebius_client`` for auth, so it unlocks together with
``TokenFactorySandbox`` once Sandboxes beta access is granted.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from nge.fleet import telemetry
from nge.fleet.base import GpuFleet, GpuNode, GpuNodeStatus

DEFAULT_IMAGE = "python:3.12-slim"

# One line, CSV: util%, mem_used_MB, mem_total_MB, temp_C, power_W
_PROBE = (
    "if command -v nvidia-smi >/dev/null 2>&1; then "
    "nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,"
    "temperature.gpu,power.draw --format=csv,noheader,nounits | head -n1; "
    "else "
    "C=$(nproc 2>/dev/null || echo 1); "
    "L=$(awk '{print $1}' /proc/loadavg 2>/dev/null || echo 0); "
    "U=$(awk -v l=$L -v c=$C 'BEGIN{v=l*100/c; if(v>100)v=100; printf \"%.0f\", v}'); "
    "MU=$(free -m 2>/dev/null | awk '/Mem:/{print $3}'); "
    "MT=$(free -m 2>/dev/null | awk '/Mem:/{print $2}'); "
    "echo \"$U, ${MU:-0}, ${MT:-1024}, 0, 0\"; fi"
)


def _parse_probe(text: str) -> Optional[dict]:
    lines = (text or "").strip().splitlines()
    if not lines:
        return None
    parts = [p.strip() for p in lines[-1].split(",")]
    if len(parts) < 5:
        return None
    try:
        util, mu, mt, temp, power = (float(parts[0]), float(parts[1]),
                                     float(parts[2]), float(parts[3]), float(parts[4]))
    except ValueError:
        return None
    return {
        "util_pct": round(util, 1),
        "mem_used_gb": round(mu / 1024, 2),
        "mem_total_gb": round(mt / 1024, 2) or 1.0,
        "temp_c": round(temp, 1),
        "power_w": round(power, 1),
    }


class NebiusFleet(GpuFleet):
    mode = "nebius"

    def __init__(self, config=None) -> None:
        from nge import config as _cfg
        self.cfg = config or _cfg.load()
        self.image = getattr(self.cfg, "nebius_fleet_image", None) or DEFAULT_IMAGE
        self.region = self.cfg.nebius_region
        self._client = None
        self._nodes: Dict[str, dict] = {}     # id -> {session, gpu_type, state, job}
        self._next = 0

    def _client_ready(self):
        if self._client is None:
            from nge.nebius_client import assert_can_spawn, build_contree_client
            c = build_contree_client(self.cfg)
            assert_can_spawn(c)
            self._client = c
        return self._client

    def _session(self, nid: str):
        nd = self._nodes[nid]
        if nd.get("session") is None:
            img = self._client_ready().images.use(self.image)
            nd["session"] = img.session()
        return nd["session"]

    # -- lifecycle ------------------------------------------------------
    def provision(self, n: int, gpu_type: str = "H100") -> List[GpuNode]:
        self._client_ready()
        out: List[GpuNode] = []
        for _ in range(max(0, int(n))):
            nid = f"nb-{gpu_type.lower()}-{self._next:02d}"
            self._next += 1
            self._nodes[nid] = {"session": None, "gpu_type": gpu_type,
                                "state": "ready", "job": None}
            out.append(GpuNode(id=nid, gpu_type=gpu_type,
                               region=self.region, state="ready"))
        return out

    def allocate(self, job: str) -> GpuNode:
        for nid, nd in self._nodes.items():
            if nd["state"] == "ready":
                nd["state"], nd["job"] = "allocated", job
                return GpuNode(id=nid, gpu_type=nd["gpu_type"],
                               region=self.region, state="allocated", job=job)
        raise RuntimeError("no ready node in fleet - call gpu_provision first")

    def release(self, node_ids: Optional[List[str]] = None) -> List[str]:
        target = set(node_ids) if node_ids else set(self._nodes)
        released = []
        for nid in list(self._nodes):
            if nid not in target:
                continue
            sess = self._nodes[nid].get("session")
            for meth in ("close", "delete", "stop"):
                fn = getattr(sess, meth, None)
                if callable(fn):
                    try:
                        fn()
                    except Exception:
                        pass
                    break
            del self._nodes[nid]
            released.append(nid)
        return released

    # -- monitoring ---------------------------------------------------
    def status(self, node_id: Optional[str] = None) -> List[GpuNodeStatus]:
        out: List[GpuNodeStatus] = []
        for nid, nd in self._nodes.items():
            if node_id and nid != node_id:
                continue
            metrics = None
            try:
                res = self._session(nid).run(
                    args=["/bin/sh", "-c", _PROBE], timeout=30).wait()
                if getattr(res, "exit_code", 1) == 0:
                    metrics = _parse_probe(getattr(res, "stdout", ""))
            except Exception:
                metrics = None
            if metrics is None:
                out.append(GpuNodeStatus(
                    id=nid, state=nd["state"], util_pct=0.0, mem_used_gb=0.0,
                    mem_total_gb=0.0, temp_c=0.0, power_w=0.0, health="unknown"))
                continue
            out.append(GpuNodeStatus(
                id=nid, state=nd["state"],
                health=telemetry.health_from_metrics(
                    metrics["temp_c"], metrics["util_pct"], metrics["power_w"]),
                efficiency=telemetry.efficiency_score(
                    metrics["util_pct"], metrics["power_w"] or 1.0),
                **metrics))
        return out
