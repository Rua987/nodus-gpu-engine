"""GPU fleet layer - provision / monitor / free Nebius cloud GPUs.

``mock``   -> deterministic fleet with synthetic telemetry (no creds, CI)
``nebius`` -> Nebius cloud GPU instances (live path, skeleton)
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
    raise ValueError(f"unknown fleet mode: {mode!r}")


__all__ = ["GpuFleet", "GpuNode", "GpuNodeStatus", "build_fleet"]
