"""Small reversible runtime patches to the vendored Nodus runtime.

Same philosophy as ``nge/backends/register.py``: never edit ``packages/nodus``,
adjust it in memory instead.

``neutralize_mcp_prompt()`` — Nodus injects a **Godot-flavoured** system block
(`_GODOT_MCP_PROMPT`) whenever *any* MCP bridge is connected (nodus_agent.py
~1280, unconditional). For the GPU engine that block is off-topic and derails
small local models into hallucinating `run_scene(res://scenes/Main.tscn)`.
This swaps it for a neutral one.
"""
from __future__ import annotations

_ORIG_MCP_PROMPT = None

_NEUTRAL_MCP_PROMPT = """
MCP servers are connected. Tools are namespaced server.tool
(e.g. nge-gpu.gpu_provision, nge-gpu.gpu_status, nge-gpu.run_in_sandbox,
nge-gpu.gpu_release). Always call them with their full qualified name from
AVAILABLE TOOLS. Use nge-gpu.* for GPU fleet provisioning, telemetry and
sandboxed execution; use read_file / write_file / bash only for local files.
"""


def neutralize_mcp_prompt() -> None:
    global _ORIG_MCP_PROMPT
    import nodus_agent as na
    if _ORIG_MCP_PROMPT is None:
        _ORIG_MCP_PROMPT = na._GODOT_MCP_PROMPT
    na._GODOT_MCP_PROMPT = _NEUTRAL_MCP_PROMPT


def restore_mcp_prompt() -> None:
    global _ORIG_MCP_PROMPT
    if _ORIG_MCP_PROMPT is None:
        return
    import nodus_agent as na
    na._GODOT_MCP_PROMPT = _ORIG_MCP_PROMPT
    _ORIG_MCP_PROMPT = None
