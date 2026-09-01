# -*- coding: utf-8 -*-
"""Tests du sink de télémétrie Grafana (mode mock — sans token, déterministe)."""

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import nodus_grafana as lg  # noqa: E402
from nodus_grafana import GrafanaSink, sink_from_env, EVENT_KINDS, mcp_grafana_command  # noqa: E402


def test_mock_record_kind_validation():
    sink = GrafanaSink(mode="mock")
    sink.record("task", task="hello")
    sink.record("plan", source="nodus", names=["read_file"])
    # kind inconnu → normalisé vers "task" (ne bloque jamais un run)
    sink.record("bogus_kind", x=1)
    assert len(sink.events) == 3
    assert sink.events[0]["kind"] == "task"
    assert sink.events[2]["kind"] == "task"
    assert sink.events[1]["source"] == "nodus"
    sink.close()


def test_mock_jsonl_output(tmp_path):
    path = tmp_path / "events.jsonl"
    sink = GrafanaSink(mode="mock", jsonl_path=str(path))
    sink.record("tool_call", name="grep", args='{"pattern": "x"}')
    sink.record("tool_result", name="grep", success=True, output="hits")
    sink.close()
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    evt = json.loads(lines[0])
    assert evt["kind"] == "tool_call" and evt["name"] == "grep"


def test_off_mode_noop():
    sink = GrafanaSink(mode="off")
    sink.record("task", task="x")
    assert sink.events == []
    sink.close()


def test_summary_timeline():
    sink = GrafanaSink(mode="mock")
    sink.record("task", task="make a file")
    sink.record("plan", source="nodus", names=["read_file", "write_file"])
    sink.record("tool_call", name="read_file", args="{}")
    sink.record("tool_result", name="read_file", success=True, output="ok")
    sink.record("result", answer="done")
    text = sink.summary()
    assert "▶ task: make a file" in text
    assert "∘ plan [nodus]" in text
    assert "↳ tool read_file" in text
    assert "● result: done" in text
    sink.close()


def test_event_kinds_set():
    assert set(EVENT_KINDS) == {"task", "plan", "tool_call", "tool_result", "verdict", "result"}


def test_sink_from_env_mock(monkeypatch):
    monkeypatch.delenv("NODUS_GRAFANA", raising=False)
    sink = sink_from_env()
    assert sink.mode == "mock"
    sink.close()


def test_sink_from_env_jsonl(monkeypatch, tmp_path):
    target = tmp_path / "out.jsonl"
    monkeypatch.setenv("NODUS_GRAFANA", f"jsonl:{target}")
    sink = sink_from_env()
    assert sink.mode == "mock"
    assert sink._jsonl is not None
    sink.record("plan", source="nodus", names=[])
    assert target.exists()
    sink.close()


def test_sink_from_env_off(monkeypatch):
    monkeypatch.setenv("NODUS_GRAFANA", "off")
    sink = sink_from_env()
    assert sink.mode == "off"
    sink.record("task", task="x")
    assert sink.events == []
    sink.close()


def test_context_manager_closes(tmp_path):
    path = tmp_path / "ctx.jsonl"
    with GrafanaSink(mode="mock", jsonl_path=str(path)) as sink:
        sink.record("plan", source="cloud", steps=3)
    # __exit__ close() ne doit pas lever
    assert path.exists()


# ── Lanceur mcp-grafana (uvx / npx / override) ────────────────────────────

def test_mcp_grafana_command_override():
    cmd = mcp_grafana_command(override="python server.py --port 9000")
    assert cmd[0]  # premier token résolu en chemin complet (shutil.which)
    assert cmd[1] == ["server.py", "--port", "9000"]


def test_mcp_grafana_command_env_override(monkeypatch):
    monkeypatch.setenv("NODUS_GRAFANA_SERVER", "npx -y @leval/mcp-grafana")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    cmd = mcp_grafana_command()
    assert cmd == ("npx", ["-y", "@leval/mcp-grafana"])


def test_mcp_grafana_command_prefers_pip_console_script(monkeypatch):
    # console script pip `mcp-grafana` (log stderr → transport stdio propre)
    # prioritaire sur uvx puis npx.
    monkeypatch.delenv("NODUS_GRAFANA_SERVER", raising=False)
    monkeypatch.setattr(
        shutil, "which",
        lambda name: "mcp-grafana.exe" if name == "mcp-grafana" else None,
    )
    cmd = mcp_grafana_command()
    assert cmd == ("mcp-grafana.exe", [])


def test_mcp_grafana_command_prefers_uvx(monkeypatch):
    monkeypatch.delenv("NODUS_GRAFANA_SERVER", raising=False)
    monkeypatch.setattr(
        shutil, "which",
        lambda name: "uvx.exe" if name == "uvx" else None,
    )
    cmd = mcp_grafana_command()
    assert cmd == ("uvx.exe", ["mcp-grafana"])


def test_mcp_grafana_command_npx_fallback_resolves_path(monkeypatch):
    monkeypatch.delenv("NODUS_GRAFANA_SERVER", raising=False)
    monkeypatch.setattr(
        shutil, "which",
        lambda name: r"C:\Program Files\nodejs\npx.CMD" if name == "npx" else None,
    )
    cmd = mcp_grafana_command()
    # chemin complet requis (npx.CMD ne se lance pas par nom nu sur Windows)
    assert cmd == (r"C:\Program Files\nodejs\npx.CMD", ["-y", "@leval/mcp-grafana"])


def test_mcp_grafana_command_none_without_launcher(monkeypatch):
    monkeypatch.delenv("NODUS_GRAFANA_SERVER", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert mcp_grafana_command() is None


def test_connect_mcp_falls_back_to_mock_without_launcher(monkeypatch):
    monkeypatch.setattr(lg, "mcp_grafana_command", lambda *a, **k: None)
    sink = GrafanaSink(mode="mcp", url="https://x.grafana.net", token="glsa_dummy")
    assert sink.mode == "mock"
    assert any("launcher not found" in e for e in sink.errors)
    sink.close()


def test_connect_mcp_forwards_org_id_env(monkeypatch):
    """mcp-grafana lit GRAFANA_ORG_ID (org numérique) — sinon org_id=0 → 503."""
    monkeypatch.setattr(lg, "mcp_grafana_command", lambda *a, **k: ("mcp-grafana", []))
    seen = {}

    class _FakeBridge:
        def connect_servers(self, cfg_path, names):
            seen["cfg"] = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
            return None

        def close(self):
            pass

    monkeypatch.setattr("nodus_mcp_client.McpBridge", _FakeBridge)

    monkeypatch.setenv("GRAFANA_ORG_ID", "1")
    sink = GrafanaSink(mode="mcp", url="https://x.grafana.net", token="glsa_dummy")
    assert sink.mode == "mcp"
    assert seen["cfg"]["mcpServers"]["grafana"]["env"]["GRAFANA_ORG_ID"] == "1"
    sink.close()

    monkeypatch.delenv("GRAFANA_ORG_ID", raising=False)
    sink2 = GrafanaSink(mode="mcp", url="https://x.grafana.net", token="glsa_dummy")
    assert "GRAFANA_ORG_ID" not in seen["cfg"]["mcpServers"]["grafana"]["env"]
    sink2.close()


# ── Résolution du préfixe réel (mcp-grafana.*, pas la clé config grafana) ─────

class _FakeRegistry:
    def __init__(self, entries):
        self.entries = entries


class _FakeBridge:
    def __init__(self, entries):
        self.registry = _FakeRegistry(entries)
        self.calls = []

    def call(self, qname, args):
        self.calls.append((qname, args))


def test_sink_resolves_mcp_grafana_prefix():
    sink = GrafanaSink(mode="mock")
    sink._bridge = _FakeBridge(
        {"mcp-grafana.create_annotation": object(), "mcp-grafana.search_dashboards": object()}
    )
    assert sink._resolve_tool("create_annotation") == "mcp-grafana.create_annotation"
    assert sink._resolve_tool("search_dashboards") == "mcp-grafana.search_dashboards"
    assert sink._resolve_tool("missing_tool") is None
    sink.close()


def test_push_annotation_uses_resolved_qualified_name():
    bridge = _FakeBridge({"mcp-grafana.create_annotation": object()})
    sink = GrafanaSink(mode="mock")
    sink._bridge = bridge
    sink.mode = "mcp"
    sink.record("plan", source="nodus", names=["read_file"])
    assert bridge.calls and bridge.calls[0][0] == "mcp-grafana.create_annotation"
    payload = bridge.calls[0][1]
    assert "plan" in payload["tags"][-1]
    assert "read_file" in payload["text"]
    sink.close()


def test_push_annotation_records_error_when_tool_missing():
    sink = GrafanaSink(mode="mock")
    sink._bridge = _FakeBridge({})
    sink.mode = "mcp"
    sink.record("result", answer="done")
    assert any("not registered" in e for e in sink.errors)
    sink.close()


def test_search_dashboards_resolves_prefix():
    bridge = _FakeBridge({"mcp-grafana.search_dashboards": object()})
    sink = GrafanaSink(mode="mock")
    sink._bridge = bridge
    sink.mode = "mcp"
    sink.search_dashboards("health")
    assert bridge.calls and bridge.calls[0][0] == "mcp-grafana.search_dashboards"
    assert bridge.calls[0][1] == {"query": "health"}
    sink.close()


def test_push_annotation_counts_confirmed_pushes():
    bridge = _FakeBridge({"mcp-grafana.create_annotation": object()})
    sink = GrafanaSink(mode="mock")
    sink._bridge = bridge
    sink.mode = "mcp"
    for _ in range(3):
        sink.record("result", answer="ok")
    assert sink.pushed == 3
    assert sink.errors == []
    sink.close()


def test_push_annotation_retries_once_on_429(monkeypatch):
    calls = {"n": 0}

    class _Flaky:
        def __init__(self, entries):
            self.registry = _FakeRegistry(entries)

        def call(self, qname, args):
            calls["n"] += 1
            if calls["n"] == 1:
                return type("R", (), {"success": False, "error": "429 rate limit"})()
            return type("R", (), {"success": True})()

    sink = GrafanaSink(mode="mock")
    sink._bridge = _Flaky({"mcp-grafana.create_annotation": object()})
    sink.mode = "mcp"
    monkeypatch.setattr("nodus_grafana.time.sleep", lambda s: None)
    sink.record("result", answer="ok")
    assert calls["n"] == 2  # un seul retry après le 429
    assert sink.pushed == 1
    assert sink.errors == []
    sink.close()
