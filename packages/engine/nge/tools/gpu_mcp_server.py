"""MCP (Model Context Protocol) stdio server for the GPU / sandbox tools.

Two implementations of the same 5 tools:

* ``build_server()`` — the **real** server on the official ``mcp`` SDK (1.x,
  ``FastMCP``). This is what Nodus' ``McpBridge`` (``ClientSessionGroup``)
  connects to. Requires ``pip install "mcp<2"`` (see requirements-local.txt).
* ``handle()`` / ``serve()`` — a stdlib-only newline-delimited JSON-RPC 2.0
  fallback (``initialize`` / ``tools/list`` / ``tools/call``). Zero deps, used
  by the unit tests and as a last resort.

``python -m nge.tools.gpu_mcp_server`` runs the SDK server, falling back to the
stdlib loop if ``mcp`` is not installed.
"""
from __future__ import annotations

import json
import sys
from typing import Any, Dict

from nge.tools import handlers

SERVER_NAME = "nge-gpu"
PROTOCOL_VERSION = "2024-11-05"


# ── real server (official mcp SDK, 1.x) ──────────────────────────────────────

def build_server():
    """Return a FastMCP server exposing the 5 GPU/sandbox tools."""
    import logging
    from mcp.server.fastmcp import FastMCP

    logging.getLogger("mcp").setLevel(logging.WARNING)
    try:
        server = FastMCP(SERVER_NAME, log_level="WARNING")
    except TypeError:  # older/newer signature
        server = FastMCP(SERVER_NAME)
    for schema in handlers.TOOL_SCHEMAS:
        fn = handlers.DISPATCH[schema["name"]]
        server.add_tool(fn, name=schema["name"], description=schema["description"])
    return server


def serve_sdk() -> None:
    build_server().run()  # stdio transport by default


def _mcp_tools() -> list:
    """Nodus/OpenAI schema -> MCP tool objects (inputSchema)."""
    return [
        {"name": s["name"], "description": s["description"], "inputSchema": s["parameters"]}
        for s in handlers.TOOL_SCHEMAS
    ]


def handle(request: Dict[str, Any]) -> Dict[str, Any] | None:
    """Return a JSON-RPC response dict, or None for notifications."""
    method = request.get("method")
    req_id = request.get("id")

    if method == "initialize":
        return _ok(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": "0.1.0"},
        })

    if method in ("notifications/initialized", "initialized"):
        return None

    if method == "tools/list":
        return _ok(req_id, {"tools": _mcp_tools()})

    if method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            result = handlers.call(name, args)
            return _ok(req_id, {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                "isError": False,
            })
        except Exception as exc:  # surface tool errors as MCP tool errors
            return _ok(req_id, {
                "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
                "isError": True,
            })

    return _err(req_id, -32601, f"method not found: {method}")


def _ok(req_id, result) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id, code, message) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def serve(stdin=None, stdout=None) -> None:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            continue
        response = handle(request)
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()


if __name__ == "__main__":  # pragma: no cover
    try:
        serve_sdk()
    except ImportError:
        sys.stderr.write("[nge-gpu] mcp SDK not installed - stdlib JSON-RPC fallback\n")
        serve()
