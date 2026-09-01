"""GPU MCP server: JSON-RPC handling + handler dispatch, plus raw handlers."""
import io
import json

from nge.tools import gpu_mcp_server as srv
from nge.tools import handlers


def test_initialize_and_tools_list():
    init = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert init["result"]["serverInfo"]["name"] == "nge-gpu"

    listed = srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in listed["result"]["tools"]}
    assert names == set(handlers.DISPATCH)
    for t in listed["result"]["tools"]:
        assert "inputSchema" in t and t["inputSchema"]["type"] == "object"


def test_notifications_initialized_is_noop():
    assert srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_tools_call_provision_then_status():
    handlers.reset_state()
    prov = srv.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": "gpu_provision", "arguments": {"n": 2}}})
    body = json.loads(prov["result"]["content"][0]["text"])
    assert body["provisioned"] == 2 and not prov["result"]["isError"]

    st = srv.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                     "params": {"name": "gpu_status", "arguments": {}}})
    assert json.loads(st["result"]["content"][0]["text"])["count"] == 2


def test_tools_call_unknown_is_tool_error():
    r = srv.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                    "params": {"name": "nope", "arguments": {}}})
    assert r["result"]["isError"] is True


def test_unknown_method_is_jsonrpc_error():
    r = srv.handle({"jsonrpc": "2.0", "id": 6, "method": "bogus"})
    assert r["error"]["code"] == -32601


def test_serve_reads_ndjson_stream():
    handlers.reset_state()
    stdin = io.StringIO("\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
    ]) + "\n")
    stdout = io.StringIO()
    srv.serve(stdin=stdin, stdout=stdout)
    lines = [json.loads(x) for x in stdout.getvalue().splitlines() if x.strip()]
    assert [l["id"] for l in lines] == [1, 2]  # notification produced no line


def test_run_in_sandbox_handler_pytest():
    handlers.reset_state()
    handlers.gpu_provision(n=1)
    out = handlers.run_in_sandbox(command="python -m pytest packages/nodus/tests -q",
                                  node_id="nb-h100-00")
    assert out["exit_code"] == 1 and out["ok"] is False
    assert "FAILED " in out["stdout"]
