"""Tool implementations: fleet + sandbox behind five JSON-in/JSON-out functions.

A process-wide :class:`EngineState` holds the live fleet, sandbox and the set of
provisioned nodes so a multi-step run (provision -> run x N -> release) shares
context. ``reset_state()`` wipes it (tests, and each demo run).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from nge import config as _cfg
from nge.fleet import build_fleet
from nge.fleet.base import GpuFleet
from nge.sandbox import build_sandbox
from nge.sandbox.base import Sandbox, SandboxSpec

# JSON schemas in the shape Nodus/OpenAI expect (function-calling tools).
TOOL_SCHEMAS: List[dict] = [
    {
        "name": "gpu_provision",
        "description": "Provision N GPU nodes on the Nebius cloud fleet. Call once before running work.",
        "parameters": {
            "type": "object",
            "properties": {
                "n": {"type": "integer", "description": "Number of GPU nodes", "default": 1},
                "gpu_type": {"type": "string", "description": "H100 | A100 | L40S", "default": "H100"},
            },
            "required": ["n"],
        },
    },
    {
        "name": "gpu_status",
        "description": "Poll live telemetry (util, mem, temp, power, health, efficiency) for the fleet or one node.",
        "parameters": {
            "type": "object",
            "properties": {"node_id": {"type": "string", "description": "Optional node id to filter"}},
            "required": [],
        },
    },
    {
        "name": "gpu_allocate",
        "description": "Reserve one ready node for a named job.",
        "parameters": {
            "type": "object",
            "properties": {"job": {"type": "string", "description": "Job name"}},
            "required": ["job"],
        },
    },
    {
        "name": "gpu_release",
        "description": "Release nodes (stop billing). Omit node_ids to release the whole fleet.",
        "parameters": {
            "type": "object",
            "properties": {
                "node_ids": {"type": "array", "items": {"type": "string"},
                             "description": "Node ids to release; empty = all"},
            },
            "required": [],
        },
    },
    {
        "name": "run_in_sandbox",
        "description": "Run one shell command in an isolated Token Factory sandbox pinned to a fleet node. Returns exit_code, stdout, stderr and any collected artifacts.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run"},
                "node_id": {"type": "string", "description": "Fleet node to pin the sandbox to"},
                "files": {"type": "object", "description": "{relpath: content} to seed the workdir"},
                "collect": {"type": "array", "items": {"type": "string"},
                            "description": "Artifact paths to read back"},
                "timeout": {"type": "integer", "description": "Seconds", "default": 120},
            },
            "required": ["command"],
        },
    },
]


@dataclass
class EngineState:
    config: _cfg.Config = field(default_factory=_cfg.load)
    _fleet: Optional[GpuFleet] = None
    _sandbox: Optional[Sandbox] = None

    @property
    def fleet(self) -> GpuFleet:
        if self._fleet is None:
            self._fleet = build_fleet(self.config.fleet_mode, self.config)
        return self._fleet

    @property
    def sandbox(self) -> Sandbox:
        if self._sandbox is None:
            self._sandbox = build_sandbox(self.config.sandbox_mode, self.config)
        return self._sandbox


_STATE = EngineState()


def reset_state(config: Optional[_cfg.Config] = None) -> EngineState:
    """Fresh fleet + sandbox. Pass a Config to pin modes explicitly."""
    global _STATE
    _STATE = EngineState(config=config or _cfg.load())
    return _STATE


def state() -> EngineState:
    return _STATE


# --- the five tools ---------------------------------------------------------

def gpu_provision(n: int = 1, gpu_type: str = "H100") -> dict:
    nodes = _STATE.fleet.provision(int(n), gpu_type=gpu_type)
    return {"provisioned": len(nodes), "nodes": [x.as_dict() for x in nodes]}


def gpu_status(node_id: Optional[str] = None) -> dict:
    rows = _STATE.fleet.status(node_id=node_id or None)
    return {"count": len(rows), "nodes": [r.as_dict() for r in rows]}


def gpu_allocate(job: str) -> dict:
    node = _STATE.fleet.allocate(job)
    return {"node_id": node.id, "job": job, "state": node.state}


def gpu_release(node_ids: Optional[List[str]] = None) -> dict:
    released = _STATE.fleet.release(node_ids or None)
    return {"released": released, "count": len(released)}


def run_in_sandbox(command: str, node_id: Optional[str] = None,
                   files: Optional[Dict[str, str]] = None,
                   collect: Optional[List[str]] = None, timeout: int = 120) -> dict:
    if _STATE.config.jail:
        from nge import policy
        ok, reason = policy.check_command(command, strict=True)
        if not ok:
            return {
                "sandbox_id": None, "node_id": node_id,
                "exit_code": 126, "ok": False, "blocked": True,
                "stdout": "", "stderr": f"[capability jail] {reason}",
                "duration_s": 0.0, "artifacts": {},
            }

    sbx = _STATE.sandbox
    sid = sbx.create(SandboxSpec(node_id=node_id, gpu=True))
    try:
        if files:
            sbx.put_files(sid, files)
        res = sbx.exec(sid, command, timeout=int(timeout))
        artifacts = sbx.collect(sid, collect) if collect else {}
        return {
            "sandbox_id": sid, "node_id": node_id,
            "exit_code": res.exit_code, "ok": res.ok,
            "stdout": res.stdout, "stderr": res.stderr,
            "duration_s": res.duration_s, "artifacts": artifacts,
        }
    finally:
        sbx.destroy(sid)


DISPATCH = {
    "gpu_provision": gpu_provision,
    "gpu_status": gpu_status,
    "gpu_allocate": gpu_allocate,
    "gpu_release": gpu_release,
    "run_in_sandbox": run_in_sandbox,
}


def call(name: str, arguments: Optional[dict] = None) -> dict:
    """Dispatch by tool name with a dict of arguments."""
    if name not in DISPATCH:
        raise KeyError(f"unknown tool: {name!r}")
    return DISPATCH[name](**(arguments or {}))
