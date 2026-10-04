"""Isolated execution layer.

``mock``          -> deterministic in-process sandbox (no creds, CI)
``token_factory`` -> Nebius Token Factory Sandboxes (live path)
``compute``       -> a directory on a Compute GPU VM, over SSH (GPU shards)
"""
from nge.sandbox.base import ExecResult, Sandbox, SandboxSpec


def build_sandbox(mode: str, config=None, fleet=None) -> Sandbox:
    mode = (mode or "mock").lower()
    if mode == "mock":
        from nge.sandbox.mock import MockSandbox
        return MockSandbox()
    if mode == "token_factory":
        from nge.sandbox.token_factory import TokenFactorySandbox
        return TokenFactorySandbox(config)
    if mode == "compute":
        from nge.sandbox.compute import ComputeSandbox
        return ComputeSandbox(fleet)
    raise ValueError(f"unknown sandbox mode: {mode!r}")


__all__ = ["Sandbox", "SandboxSpec", "ExecResult", "build_sandbox"]
