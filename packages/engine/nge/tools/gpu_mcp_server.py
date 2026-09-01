"""Minimal MCP (Model Context Protocol) stdio server for the GPU / sandbox tools.

Stdlib only. Speaks newline-delimited JSON-RPC 2.0 on stdin/stdout and implements
the subset Nodus' ``McpBridge`` needs: ``initialize``, ``tools/list``,
``tools/call`` (+ the ``notifications/initialized`` no-op).

Run standalone:   python -m nge.tools.gpu_mcp_server
Wire into Nodus:  see packages/engine/nge/tools/mcp.json
"""
from __future__ import annotations

import json
import sys
from typing import Any, Dict

from nge.tools import handlers

SERVER_NAME = "nge-gpu"
PROTOCOL_VERSION = "2024-11-05"


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
    serve()
