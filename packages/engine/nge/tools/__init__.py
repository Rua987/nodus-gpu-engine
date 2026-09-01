"""GPU / sandbox tools exposed to the Nodus executor.

``handlers``        - plain Python functions over the fleet + sandbox layers
``gpu_mcp_server``  - stdlib JSON-RPC (MCP) stdio server wrapping those handlers,
                      so vendored Nodus can consume them via its existing
                      ``--mcp-servers`` path with zero code changes.
"""
from nge.tools import handlers  # noqa: F401

TOOL_NAMES = ("gpu_provision", "gpu_status", "gpu_allocate", "gpu_release", "run_in_sandbox")
