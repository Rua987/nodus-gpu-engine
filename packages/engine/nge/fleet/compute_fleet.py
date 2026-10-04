"""Compute Phase 3: a GpuFleet made of real Nebius AI Cloud GPU VMs.

Architecture A (docs/COMPUTE_GPU.md): the fleet gives the orchestrator real
``nvidia-smi`` telemetry; the shards still run in Token Factory sandboxes.
Built on the Phase 2 probe's parts - same create call, same LF-bytes SSH, same
labels, same cloud-init power-off - so the same guarantees hold:

- nothing is created unless ``NGE_COMPUTE_SPAWN=1``;
- the first provision refuses while a labelled VM from an earlier run exists;
- every VM powers itself off after ``max_minutes`` + grace, whatever happens
  to this process; ``python -m nge.fleet.compute cleanup`` deletes leftovers;
- a provision that fails half-way deletes what it had created;
- ``release()`` never raises; what it could not delete is kept in
  ``undeleted`` for the caller to report.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from nge.fleet import telemetry
from nge.fleet.base import GpuFleet, GpuNode, GpuNodeStatus

DEFAULT_MAX_MINUTES = 15
_BURN_SRC = Path(__file__).with_name("gpu_burn.cu")
# appended to the telemetry probe: who is on the GPU right now
_APPS = ("echo __NGE_APPS__\n"
         "nvidia-smi --query-compute-apps=pid,process_name,used_memory "
         "--format=csv,noheader 2>/dev/null || true\n")


class ComputeGpuFleet(GpuFleet):
    """Real Nebius Compute GPU nodes - not Contree sandboxes."""

    mode = "compute"

    def __init__(self, config=None, *, api=None, target: Optional[Dict[str, str]] = None,
                 ssh: Optional[Callable] = None, ssh_key=None, public_key: Optional[str] = None,
                 max_minutes: Optional[float] = None,
                 gpu_runtime: bool = False,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 log: Callable[[str], None] = print) -> None:
        from nge import config as _cfg
        self.cfg = config or _cfg.load()
        self._api, self._target = api, target
        self._ssh, self._key, self._pub = ssh, ssh_key, public_key
        self.max_minutes = float(max_minutes or os.environ.get("NGE_COMPUTE_MAX_MINUTES")
                                 or DEFAULT_MAX_MINUTES)
        self._clock, self._sleep, self._log = clock, sleep, log
        # True when shards run on the VMs themselves (contention runs): each VM
        # then sets up a venv at boot and is ready only once that is done.
        self.gpu_runtime = bool(gpu_runtime) or getattr(self.cfg, "sandbox_mode", "") == "compute"
        self._nodes: Dict[str, dict] = {}      # node id -> {instance_id, ip, state, job, gpu}
        self._next = 0
        self._checked_leftovers = False
        self._sdk = None
        self.undeleted: List[str] = []

    # -- wiring (only touched when a VM is really wanted) ---------------------
    def _ensure_wired(self) -> None:
        if self._api is not None and self._target is not None and self._key is not None:
            return
        from nge.fleet import compute as _c, compute_inventory as ci, compute_probe as cp
        engine = _c._engine_dir()
        creds = _c.key_files("phase2")["credentials"]
        self._sdk = ci.build_sdk(engine, creds)
        if self._api is None:
            self._api = cp.ComputeApi(self._sdk)
        if self._target is None:
            from nge import config as _cfg
            project = _cfg.load_value("nebius_compute_project_id", "NEBIUS_COMPUTE_PROJECT_ID")
            self._target = ci.recommend(ci.inventory(ci.NebiusReadApi(self._sdk), project))
            if not self._target:
                raise RuntimeError("no bootable GPU target in the inventory")
        if self._key is None:
            self._key, self._pub = cp.ensure_ssh_key(engine)
        if self._ssh is None:
            self._ssh = cp.run_ssh

    # -- GpuFleet -------------------------------------------------------------
    def provision(self, n: int, gpu_type: str = "H100") -> List[GpuNode]:
        if os.environ.get("NGE_COMPUTE_SPAWN") != "1":
            raise RuntimeError("ComputeGpuFleet creates paid GPU VMs: set NGE_COMPUTE_SPAWN=1 "
                               "to allow it (docs/COMPUTE_GPU.md)")
        from nge.fleet import compute_probe as cp
        self._ensure_wired()
        if not self._checked_leftovers:
            left = self._api.list_labeled(self._target["project_id"])
            if left:
                raise RuntimeError("labelled GPU VM(s) from an earlier run still exist "
                                   f"{[v['name'] for v in left]} - run cleanup first")
            self._checked_leftovers = True
        gpu = self._target["platform"]
        deadline = self._clock() + self.max_minutes * 60
        user_data = cp.cloud_init(self._pub, poweroff_after_minutes=int(self.max_minutes)
                                  + cp.POWEROFF_GRACE_MINUTES,
                                  gpu_runtime=self.gpu_runtime)
        made: List[str] = []
        try:
            pending = []
            for _ in range(max(0, int(n))):
                nid = f"cg-{gpu.replace('gpu-', '')}-{self._next:02d}"
                self._next += 1
                name = f"{cp.NAME_PREFIX}{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-{nid}"
                iid, op = self._api.create(self._target, name, user_data,
                                           deadline - self._clock())
                self._nodes[nid] = {"instance_id": iid, "ip": None, "state": "provisioning",
                                    "job": None, "gpu": gpu}
                made.append(nid)
                pending.append((nid, op))
                self._log(f"[compute-fleet] create sent {nid} ({iid})")
            for nid, op in pending:
                self._api.wait_op(op, deadline - self._clock())
            for nid in made:
                self._wait_ready(nid, deadline)
        except BaseException:
            self.release(made)                 # half a fleet is still paid for
            raise
        return [self._as_node(nid) for nid in made]

    def _wait_ready(self, nid: str, deadline: float) -> None:
        from nge.fleet.nebius import _PROBE
        node = self._nodes[nid]
        while True:
            st = self._api.get(node["instance_id"])
            if st["state"] == "ERROR":
                raise RuntimeError(f"{nid} entered ERROR state")
            if st["state"] == "RUNNING" and st["public_ip"]:
                node["ip"] = st["public_ip"]
                break
            if self._clock() > deadline:
                raise TimeoutError(f"{nid} not running before the deadline")
            self._sleep(10)
        from nge.fleet import compute_probe as cp
        # With a runtime, ready = cloud-init finished the venv; if cloud-init
        # itself failed (exit 8) waiting on would only bill the VM to the deadline.
        check = (f"if [ ! -f {cp.READY_MARKER} ]; then\n"
                 '  case "$(cloud-init status 2>/dev/null)" in *error*) '
                 "cloud-init status --long 2>&1 | tail -5; exit 8;; esac\n"
                 f"  exit 7\nfi\n{_PROBE}") if self.gpu_runtime else _PROBE
        while True:                            # ready = SSH answers the probe
            rc, out, err = self._ssh(node["ip"], self._key, check, timeout=30.0)
            if rc == 8:
                raise RuntimeError(f"{nid}: cloud-init failed - {out.strip()[-300:]}")
            if rc == 0 and out.strip():
                node["state"] = "ready"
                self._log(f"[compute-fleet] {nid} ready at {node['ip']}")
                return
            if self._clock() > deadline:
                raise TimeoutError(f"{nid}: no SSH answer before the deadline: {err.strip()[:160]}")
            self._sleep(15)

    def status(self, node_id: Optional[str] = None) -> List[GpuNodeStatus]:
        from nge.fleet.nebius import _PROBE, _parse_probe
        out: List[GpuNodeStatus] = []
        for nid, node in self._nodes.items():
            if node_id and nid != node_id:
                continue
            if node["state"] == "gone":
                continue
            rc, text, _err = (self._ssh(node["ip"], self._key, _PROBE + _APPS, timeout=30.0)
                              if node["ip"] else (1, "", "no ip"))
            text, _, apps = text.partition("__NGE_APPS__")
            apps = "; ".join(l.strip() for l in apps.splitlines() if l.strip())
            m = _parse_probe(text) if rc == 0 else None
            if not m:
                out.append(GpuNodeStatus(id=nid, state=node["state"], util_pct=0.0,
                                         mem_used_gb=0.0, mem_total_gb=0.0, temp_c=0.0,
                                         power_w=0.0, health="unknown",
                                         probe_kind=telemetry.PROBE_FAILED))
                continue
            cls = m["gpu_class"]
            out.append(GpuNodeStatus(
                id=nid, state=node["state"], util_pct=m["util_pct"],
                mem_used_gb=m["mem_used_gb"], mem_total_gb=m["mem_total_gb"],
                temp_c=m["temp_c"], power_w=m["power_w"],
                health=telemetry.health_from_metrics(m["temp_c"], m["util_pct"],
                                                     m["power_w"], cls),
                efficiency=telemetry.efficiency_score(m["util_pct"], m["power_w"], cls),
                probe_kind=m["probe_kind"], gpu_class=cls, gpu_name=m["gpu_name"],
                gpu_processes=apps))
        return out

    # -- used by the compute sandbox and the contention run ------------------
    def run_on(self, node_id: str, script: str, timeout: float):
        """(rc, stdout, stderr) of ``script`` run on the node's VM over SSH."""
        node = self._nodes.get(node_id)
        if not node or node["state"] == "gone" or not node["ip"]:
            return 1, "", f"node {node_id!r} has no running VM"
        return self._ssh(node["ip"], self._key, script, timeout=timeout)

    def induce_load(self, node_id: str, seconds: int) -> Dict[str, object]:
        """Start a GPU job on ``node_id`` that keeps every SM busy for ``seconds``
        and then exits on its own: the declared neighbour of the contention run.
        Built from ``gpu_burn.cu`` with the image's nvcc, detached from SSH."""
        src = _BURN_SRC.read_text(encoding="utf-8")
        script = (
            "set -e\nexport PATH=/usr/local/cuda/bin:$PATH\n"
            "mkdir -p /tmp/nge_load && cd /tmp/nge_load\n"
            f"cat > gpu_burn.cu <<'NGE_EOF'\n{src}\nNGE_EOF\n"
            "nvcc -O2 -o nge_burn gpu_burn.cu\n"
            f"setsid nohup ./nge_burn {int(seconds)} > burn.log 2>&1 < /dev/null &\n"
            "sleep 5\n"
            "nvidia-smi --query-gpu=utilization.gpu,power.draw --format=csv,noheader,nounits\n")
        rc, out, err = self.run_on(node_id, script, timeout=180.0)
        self._log(f"[compute-fleet] induced load on {node_id}: rc={rc} {out.strip()[:80]}")
        return {"ok": rc == 0, "seconds": int(seconds),
                "how": "gpu_burn.cu (FMA loop on every SM), built with nvcc on the VM",
                "reading_after_5s": out.strip()[-120:],
                "error": "" if rc == 0 else (err.strip() or out.strip())[-300:]}

    def allocate(self, job: str, node_id: Optional[str] = None) -> GpuNode:
        for nid, node in self._nodes.items():
            if node["state"] == "ready" and (node_id is None or nid == node_id):
                node["state"], node["job"] = "allocated", job
                return self._as_node(nid)
        if node_id:
            raise RuntimeError(f"node {node_id!r} not ready for allocate")
        raise RuntimeError("no ready node in fleet - call gpu_provision first")

    def release(self, node_ids: Optional[List[str]] = None) -> List[str]:
        targets = list(node_ids) if node_ids else list(self._nodes)
        released = []
        for nid in targets:
            node = self._nodes.get(nid)
            if not node or node["state"] == "gone":
                continue
            try:
                self._api.delete(node["instance_id"], timeout=600)
                node["state"], node["job"] = "gone", None
                released.append(nid)
                self._log(f"[compute-fleet] deleted {nid}")
            except Exception as exc:           # never raise from cleanup; say so
                self.undeleted.append(node["instance_id"])
                self._log(f"[compute-fleet] WARNING delete failed for {nid}: "
                          f"{type(exc).__name__}: {str(exc)[:160]}")
        return released

    def _as_node(self, nid: str) -> GpuNode:
        node = self._nodes[nid]
        return GpuNode(id=nid, gpu_type=node["gpu"],
                       region=(self._target or {}).get("region", ""),
                       state=node["state"], job=node["job"])

    def nodes(self) -> List[GpuNode]:
        return [self._as_node(nid) for nid in self._nodes]
