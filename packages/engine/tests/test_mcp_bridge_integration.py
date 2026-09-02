"""Nodus' real MCP client connects to our real MCP server and calls GPU tools.

Spawns `nge/tools/gpu_mcp_server.py` as a stdio MCP server (official `mcp` SDK)
and drives it through `nodus_mcp_client.McpBridge` — the exact path the Nodus
ReAct loop uses. No Ollama, no cloud. Skipped when `mcp` is not installed
(the default `requirements.txt`); run with `pip install -r requirements-local.txt`.
"""
import json

import pytest

pytest.importorskip("mcp")

from nge.mcp_config import write_config  # noqa: E402

try:
    from nodus_mcp_client import McpBridge  # noqa: E402
except Exception as exc:  # pragma: no cover
    pytest.skip(f"nodus_mcp_client unavailable: {exc}", allow_module_level=True)


@pytest.fixture
def bridge(tmp_path):
    cfg = write_config(tmp_path / "mcp.json", fleet_mode="mock", sandbox_mode="mock")
    b = McpBridge()
    err = b.connect_mcp("nge-gpu", str(cfg), cwd=str(tmp_path))
    assert err is None, f"connect_mcp failed: {err}"
    yield b
    b.close()


def _payload(tool_result):
    assert tool_result.success, getattr(tool_result, "error", tool_result)
    return json.loads(tool_result.output)


def test_bridge_lists_the_five_gpu_tools(bridge):
    names = {s["function"]["name"] for s in bridge.schemas()}
    for t in ("gpu_provision", "gpu_status", "gpu_allocate", "gpu_release", "run_in_sandbox"):
        assert f"nge-gpu.{t}" in names


def test_bridge_provision_status_release_roundtrip(bridge):
    prov = _payload(bridge.call("nge-gpu.gpu_provision", {"n": 2, "gpu_type": "H100"}))
    assert prov["provisioned"] == 2
    assert [n["id"] for n in prov["nodes"]] == ["nb-h100-00", "nb-h100-01"]

    st = _payload(bridge.call("nge-gpu.gpu_status", {}))
    assert st["count"] == 2
    assert all(0 <= n["util_pct"] <= 100 for n in st["nodes"])

    rel = _payload(bridge.call("nge-gpu.gpu_release", {}))
    assert rel["count"] == 2


def test_bridge_run_in_sandbox_and_capability_jail(bridge):
    bridge.call("nge-gpu.gpu_provision", {"n": 1})
    ok = _payload(bridge.call("nge-gpu.run_in_sandbox", {
        "command": "python -m pytest packages/nodus/tests -q", "node_id": "nb-h100-00"}))
    assert ok["exit_code"] == 1 and "FAILED" in ok["stdout"]

    blocked = _payload(bridge.call("nge-gpu.run_in_sandbox", {
        "command": "rm -rf /", "node_id": "nb-h100-00"}))
    assert blocked["blocked"] is True and blocked["exit_code"] == 126
