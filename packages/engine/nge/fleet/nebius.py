"""Nebius cloud GPU fleet - live path (SKELETON).

Signature-compatible with :class:`MockFleet`. Two viable live backings:

1. **Nebius Cloud Compute** - raw GPU VMs. ``provision`` = create instances
   (preset ``gpu-h100-sxm``) via the Nebius IaaS API, wait for RUNNING;
   ``status`` = DCGM / Observability metrics; ``release`` = delete instances.
2. **Token Factory Sandboxes pool** (simpler, no IaaS creds) - treat each
   fleet node as a ConTree sandbox session; ``status`` reads ConTree's
   built-in Resource Tracking (CPU time, memory, I/O) instead of DCGM.

Network calls raise ``NotImplementedError`` until wired against an account.
"""
from __future__ import annotations

from typing import List, Optional

from nge.fleet.base import GpuFleet, GpuNode, GpuNodeStatus


class NebiusFleet(GpuFleet):
    mode = "nebius"

    def __init__(self, config=None) -> None:
        from nge import config as _cfg
        self.cfg = config or _cfg.load()
        self._api_key = self.cfg.nebius_api_key()
        self.project_id = self.cfg.nebius_project_id
        self.region = self.cfg.nebius_region

    def _require(self) -> None:
        if not self._api_key or not self.project_id:
            raise RuntimeError(
                "Nebius fleet not configured - set NEBIUS_API_KEY and "
                "NEBIUS_PROJECT_ID."
            )

    def provision(self, n: int, gpu_type: str = "H100") -> List[GpuNode]:
        self._require()
        # Nebius Compute: create N GPU instances (preset gpu-h100-sxm, ...),
        # wait for RUNNING, return their ids/addresses.
        raise NotImplementedError("Nebius fleet: provision instances")

    def status(self, node_id: Optional[str] = None) -> List[GpuNodeStatus]:
        self._require()
        # Nebius Observability / DCGM exporter -> util, mem, temp, power per node.
        raise NotImplementedError("Nebius fleet: poll telemetry")

    def allocate(self, job: str) -> GpuNode:
        self._require()
        raise NotImplementedError("Nebius fleet: allocate node to job")

    def release(self, node_ids: Optional[List[str]] = None) -> List[str]:
        self._require()
        # Nebius Compute: delete instances (stop billing).
        raise NotImplementedError("Nebius fleet: release instances")
