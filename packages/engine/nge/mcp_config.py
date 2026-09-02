"""Generate a resolved MCP config for the vendored Nodus runtime.

The committed ``nge/tools/mcp.json`` is a template. At run time we write a
config with absolute paths + the current interpreter so Nodus' ``McpBridge``
can spawn ``nge/tools/gpu_mcp_server.py`` as a stdio MCP server from any cwd.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

_ENGINE_DIR = Path(__file__).resolve().parent.parent          # packages/engine
_SERVER = _ENGINE_DIR / "nge" / "tools" / "gpu_mcp_server.py"

SERVER_NAME = "nge-gpu"


def build_config(fleet_mode: str = "mock", sandbox_mode: str = "mock",
                 jail: bool = True) -> dict:
    return {
        "mcpServers": {
            SERVER_NAME: {
                "command": sys.executable,
                "args": [str(_SERVER)],
                "env": {
                    "PYTHONPATH": str(_ENGINE_DIR),
                    "NGE_FLEET_MODE": fleet_mode,
                    "NGE_SANDBOX": sandbox_mode,
                    "NGE_JAIL": "on" if jail else "off",
                },
            }
        }
    }


def write_config(path: Optional[str | Path] = None, **kw) -> Path:
    path = Path(path) if path else (_ENGINE_DIR / "out" / "mcp.local.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_config(**kw), indent=2), encoding="utf-8")
    return path
