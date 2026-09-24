"""Nebius AI Cloud Compute GPU fleet (real VMs with nvidia-smi).

Distinct from :class:`nge.fleet.nebius.NebiusFleet`, which uses Token Factory
**Contree microVMs** (CPU only today). This module targets Compute instances
(``gpu-h100-sxm`` / ``gpu-h200-sxm`` …) via the Nebius Python SDK (``nebius``).

Status (2026-09-05): **skeleton** — interface + credential preflight only.
Provisioning a paid GPU VM requires an explicit operator **Go** (cost).
See ``docs/ENGINE_BACKLOG.md`` M1/M2 and ``docs/COMPUTE_GPU.md``.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

from nge.fleet.base import GpuFleet, GpuNode, GpuNodeStatus
from nge.fleet import telemetry


class ComputeGpuFleet(GpuFleet):
    """Real Nebius Compute GPU nodes — not Contree sandboxes."""

    mode = "compute"

    def __init__(self, config=None) -> None:
        from nge import config as _cfg
        self.cfg = config or _cfg.load()
        self._nodes: Dict[str, dict] = {}
        self._next = 0

    def provision(self, n: int, gpu_type: str = "H100") -> List[GpuNode]:
        raise NotImplementedError(
            "ComputeGpuFleet: not wired yet. Needs Nebius Compute SDK "
            "(platform gpu-h100-sxm / gpu-h200-sxm), SA credentials, subnet, "
            "boot disk (ubuntu*-cuda*). See docs/COMPUTE_GPU.md. "
            "Until then use fleet_mode=mock (demo) or nebius (TF Contree CPU)."
        )

    def status(self, node_id: Optional[str] = None) -> List[GpuNodeStatus]:
        raise NotImplementedError("ComputeGpuFleet.status: see provision()")

    def allocate(self, job: str, node_id: Optional[str] = None) -> GpuNode:
        raise NotImplementedError("ComputeGpuFleet.allocate: see provision()")

    def release(self, node_ids: Optional[List[str]] = None) -> List[str]:
        return []


def expected_probe_kind() -> str:
    """Compute VMs with CUDA images should expose nvidia-smi."""
    return telemetry.PROBE_NVIDIA


def check_credentials() -> dict:
    """Read-only: which Compute auth signals exist (no API call, no VM spawn).

    Returns a small dict for preflight banners / backlog. Never creates resources.
    """
    iam = bool(os.environ.get("NEBIUS_IAM_TOKEN", "").strip())
    sa_path = (
        os.environ.get("NEBIUS_SA_KEY_FILE", "").strip()
        or os.environ.get("NEBIUS_SERVICE_ACCOUNT_FILE", "").strip()
        or os.environ.get("YC_SERVICE_ACCOUNT_KEY_FILE", "").strip()
    )
    sa_file_ok = bool(sa_path) and Path(sa_path).is_file()
    project = bool(
        os.environ.get("NEBIUS_PROJECT_ID", "").strip()
        or os.environ.get("NEBIUS_FOLDER_ID", "").strip()
    )
    subnet = bool(os.environ.get("NEBIUS_SUBNET_ID", "").strip())
    try:
        import nebius  # noqa: F401
        sdk = True
    except ImportError:
        sdk = False
    ready = (iam or sa_file_ok) and project and sdk
    return {
        "sdk_installed": sdk,
        "iam_token": iam,
        "sa_key_file": sa_file_ok,
        "project_id": project,
        "subnet_id": subnet,
        "ready_for_wire": ready,
        "spawn_allowed": False,  # always False until explicit Go + code path
    }
