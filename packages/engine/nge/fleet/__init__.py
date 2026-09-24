"""GPU fleet layer - provision / monitor / free nodes.

``mock``    -> deterministic fleet with synthetic telemetry (no creds, CI)
``nebius``  -> Token Factory Contree microVMs (CPU; probe cpu-fallback)
``compute`` -> Nebius AI Cloud GPU VMs (skeleton — real H100/H200 path)
"""
from nge.fleet.base import GpuFleet, GpuNode, GpuNodeStatus


def build_fleet(mode: str, config=None) -> GpuFleet:
    mode = (mode or "mock").lower()
    if mode == "mock":
        from nge.fleet.mock import MockFleet
        return MockFleet()
    if mode == "nebius":
        from nge.fleet.nebius import NebiusFleet
        return NebiusFleet(config)
    if mode == "compute":
        from nge.fleet.compute import ComputeGpuFleet
        return ComputeGpuFleet(config)
    raise ValueError(f"unknown fleet mode: {mode!r}")


__all__ = ["GpuFleet", "GpuNode", "GpuNodeStatus", "build_fleet"]
