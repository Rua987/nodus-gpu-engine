"""Nebius GPU fleet, backed by Token Factory sandbox sessions (ConTree SDK).

Each fleet node is a ConTree session (its own microVM). ``status()`` runs a
telemetry probe *inside* the node via ``session.run(shell=...)`` (not bare
``args=`` — Contree requires ``shell`` or ``command``).

  - ``probe_kind=nvidia-smi``  -> real GPU util / mem / temp / power (+ name)
  - ``probe_kind=cpu-fallback`` -> no driver / no device; CPU load mapped in
  - ``probe_kind=failed``       -> probe did not run or stdout unparsable

Default TF images (``python:3.12-slim``) have **no** GPU device. Contree's
spawn API exposes CPU/disk limits only — importing a CUDA image does **not**
attach an H100. Set ``NGE_FLEET_HAS_GPU=1`` only when you know the runtime
really exposes NVIDIA devices. Node ids like ``nb-h100-00`` are labels.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from nge.fleet import telemetry
from nge.fleet.base import GpuFleet, GpuNode, GpuNodeStatus

DEFAULT_IMAGE = "python:3.12-slim"

# Portable sh (no awk gymnastics). One CSV line, tagged.
# nvidia-smi: nvidia-smi,util,mem_used_MB,mem_total_MB,temp,power,name
# cpu:       cpu-fallback,util,mem_used_MB,mem_total_MB,0,0,
_PROBE = r"""
if command -v nvidia-smi >/dev/null 2>&1; then
  line=$(nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,name --format=csv,noheader,nounits 2>/dev/null | head -n1)
  if [ -n "$line" ]; then
    echo "nvidia-smi,$line"
    exit 0
  fi
fi
C=$(nproc 2>/dev/null || echo 1)
L=$(cut -d' ' -f1 /proc/loadavg 2>/dev/null || echo 0)
U=$(awk -v l="$L" -v c="$C" 'BEGIN{v=l*100/c; if(v>100)v=100; printf "%.0f", v}' 2>/dev/null || echo 0)
MU=0
MT=1024
if command -v free >/dev/null 2>&1; then
  MU=$(free -m 2>/dev/null | awk '/Mem:/{print $3}')
  MT=$(free -m 2>/dev/null | awk '/Mem:/{print $2}')
fi
echo "cpu-fallback,${U:-0},${MU:-0},${MT:-1024},0,0,"
"""


def _parse_probe(text: str) -> Optional[dict]:
    """Parse probe stdout into metrics + ``probe_kind`` / ``gpu_class``."""
    lines = (text or "").strip().splitlines()
    if not lines:
        return None
    # Prefer the last tagged line (ignore banners / warnings above)
    line = lines[-1]
    for cand in reversed(lines):
        s = cand.strip()
        if s.startswith(telemetry.PROBE_NVIDIA + ",") or s.startswith(
                telemetry.PROBE_CPU + ","):
            line = s
            break
    parts = [p.strip() for p in line.split(",")]
    tagged = False
    kind = telemetry.PROBE_NVIDIA
    name = ""
    if parts and parts[0] in (telemetry.PROBE_NVIDIA, telemetry.PROBE_CPU):
        kind = parts[0]
        tagged = True
        parts = parts[1:]
    if len(parts) < 5:
        return None
    try:
        util, mu, mt, temp, power = (float(parts[0]), float(parts[1]),
                                     float(parts[2]), float(parts[3]), float(parts[4]))
    except ValueError:
        return None
    if len(parts) >= 6 and parts[5]:
        name = ",".join(parts[5:]).strip()
    if not tagged and temp == 0.0 and power == 0.0:
        kind = telemetry.PROBE_CPU

    if kind == telemetry.PROBE_CPU:
        gclass = telemetry.CLASS_NONE
    else:
        gclass = telemetry.gpu_class_from_name(name)

    return {
        "util_pct": round(util, 1),
        "mem_used_gb": round(mu / 1024, 2),
        "mem_total_gb": round(mt / 1024, 2) or 1.0,
        "temp_c": round(temp, 1),
        "power_w": round(power, 1),
        "probe_kind": kind,
        "gpu_class": gclass,
        "gpu_name": name,
    }


def _run_probe(session, probe: str = _PROBE, timeout: int = 30):
    """Contree: must pass ``shell=``, not ``args=['/bin/sh','-c',...]`` alone."""
    return session.run(shell=probe, timeout=timeout).wait()


class NebiusFleet(GpuFleet):
    mode = "nebius"

    def __init__(self, config=None) -> None:
        from nge import config as _cfg
        self.cfg = config or _cfg.load()
        self.image = (
            getattr(self.cfg, "nebius_fleet_image", None)
            or DEFAULT_IMAGE
        )
        self.region = self.cfg.nebius_region
        self._client = None
        self._nodes: Dict[str, dict] = {}
        self._next = 0
        self._last_probe_err: Dict[str, str] = {}

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

    def allocate(self, job: str, node_id: Optional[str] = None) -> GpuNode:
        if node_id:
            nd = self._nodes.get(node_id)
            if not nd or nd["state"] != "ready":
                raise RuntimeError(f"node {node_id!r} not ready for allocate")
            nd["state"], nd["job"] = "allocated", job
            return GpuNode(id=node_id, gpu_type=nd["gpu_type"],
                           region=self.region, state="allocated", job=job)
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
            self._last_probe_err.pop(nid, None)
            released.append(nid)
        return released

    # -- monitoring ---------------------------------------------------
    def status(self, node_id: Optional[str] = None) -> List[GpuNodeStatus]:
        out: List[GpuNodeStatus] = []
        for nid, nd in self._nodes.items():
            if node_id and nid != node_id:
                continue
            metrics = None
            err = ""
            try:
                res = _run_probe(self._session(nid))
                code = int(getattr(res, "exit_code", 1) or 0)
                stdout = getattr(res, "stdout", "") or ""
                stderr = getattr(res, "stderr", "") or ""
                if code == 0:
                    metrics = _parse_probe(stdout)
                if metrics is None:
                    err = (stderr or stdout or f"exit={code}")[:240]
            except Exception as exc:
                err = f"{type(exc).__name__}: {exc}"[:240]
                metrics = None
            self._last_probe_err[nid] = err
            if metrics is None:
                out.append(GpuNodeStatus(
                    id=nid, state=nd["state"], util_pct=0.0, mem_used_gb=0.0,
                    mem_total_gb=0.0, temp_c=0.0, power_w=0.0, health="unknown",
                    efficiency=0.0, probe_kind=telemetry.PROBE_FAILED,
                    gpu_class=telemetry.CLASS_NONE, gpu_name=""))
                continue
            gclass = metrics.pop("gpu_class")
            kind = metrics.pop("probe_kind")
            gname = metrics.pop("gpu_name", "")
            out.append(GpuNodeStatus(
                id=nid, state=nd["state"],
                health=telemetry.health_from_metrics(
                    metrics["temp_c"], metrics["util_pct"], metrics["power_w"],
                    gclass),
                efficiency=telemetry.efficiency_score(
                    metrics["util_pct"], metrics["power_w"] or 0.0, gclass),
                probe_kind=kind, gpu_class=gclass, gpu_name=gname,
                **metrics))
        return out
