# -*- coding: utf-8 -*-
"""Tests de la démo Nodus (script déterministe, sans checkpoint ni Ollama)."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import demo_agentic_cinema as demo  # noqa: E402
from nodus_grafana import GrafanaSink  # noqa: E402


def _sink() -> GrafanaSink:
    return GrafanaSink(mode="mock")


# ── Tâches curées ──────────────────────────────────────────────────────────

def test_demo_tasks_have_plans():
    assert set(demo.DEMO_TASKS) == {"inspect", "tune", "create", "media"}
    for spec in demo.DEMO_TASKS.values():
        assert spec["task"]
        assert isinstance(spec["plan"], list) and len(spec["plan"]) >= 1
        for step in spec["plan"]:
            assert len(step) == 2 and isinstance(step[0], str) and isinstance(step[1], dict)


def test_gold_plans_use_only_allowed_tools():
    # 8 outils natifs + gcs_upload (capability tool de livraison, côté harnais).
    allowed = {"bash", "read_file", "write_file", "edit_file", "glob", "grep",
               "web_fetch", "brave_search", "gcs_upload"}
    for spec in demo.DEMO_TASKS.values():
        for name, _ in spec["plan"]:
            assert name in allowed


# ── Exécuteur mock ─────────────────────────────────────────────────────────

def test_mock_execute_write_read_roundtrip():
    ws = {}
    ok, out = demo.mock_execute("write_file", {"path": "a.txt", "content": "hi"}, ws)
    assert ok and "wrote" in out
    assert ws["a.txt"] == "hi"
    ok, out = demo.mock_execute("read_file", {"path": "a.txt"}, ws)
    assert ok and out == "hi"


def test_mock_execute_edit_and_grep():
    ws = {"config.yaml": "debug: true\n"}
    ok, _ = demo.mock_execute("edit_file", {"path": "config.yaml", "old": "debug: true", "new": "debug: false"}, ws)
    assert ok and ws["config.yaml"] == "debug: false\n"
    ok, out = demo.mock_execute("grep", {"pattern": "debug", "path": "."}, ws)
    assert ok and "config.yaml" in out


def test_mock_execute_glob():
    ws = {"src/a.py": "", "src/b.py": "", "cfg.yaml": ""}
    ok, out = demo.mock_execute("glob", {"pattern": "*.py"}, ws)
    assert ok and "a.py" in out and "b.py" in out and "cfg.yaml" not in out


def test_mock_execute_read_missing_fails():
    ok, out = demo.mock_execute("read_file", {"path": "nope.txt"}, {})
    assert not ok and "not found" in out


# ── Flux d'événements ──────────────────────────────────────────────────────

def test_run_plan_emits_full_stream_in_order():
    sink = _sink()
    demo.run_plan(sink, "Read src/utils.py", [("read_file", {"path": "src/utils.py"})], {"src/utils.py": "x"}, "nodus")
    kinds = [e["kind"] for e in sink.events]
    assert kinds == ["task", "plan", "tool_call", "tool_result", "result"]
    text = sink.summary()
    assert "▶ task:" in text
    assert "∘ plan [nodus]" in text
    assert "↳ tool read_file" in text
    assert "● result:" in text
    sink.close()


def test_run_demo_default_uses_gold_inspect(monkeypatch):
    monkeypatch.setattr(demo, "_real_nodus_plan", lambda task: None)
    sink = _sink()
    meta = demo.run_demo(sink, use_real_nodus=True)
    plan_evt = next(e for e in sink.events if e["kind"] == "plan")
    assert plan_evt["source"] == "demo-gold"
    assert plan_evt["names"] == ["read_file", "write_file", "bash"]
    assert meta["workspace"]["config_demo.yaml"]  # le fichier a bien été créé
    sink.close()


def test_run_demo_gold_fallback_without_checkpoint(monkeypatch):
    monkeypatch.setattr(demo, "_real_nodus_plan", lambda task: None)
    sink = _sink()
    meta = demo.run_demo(sink, task_key="tune", use_real_nodus=True)
    plan_evt = next(e for e in sink.events if e["kind"] == "plan")
    assert plan_evt["source"] == "demo-gold"
    assert plan_evt["names"] == ["grep", "edit_file"]
    assert "debug: false" in meta["workspace"]["config.yaml"]
    sink.close()


def test_run_demo_uses_real_nodus_when_available(monkeypatch):
    monkeypatch.setattr(demo, "_real_nodus_plan", lambda task: ["grep", "edit_file"])
    sink = _sink()
    meta = demo.run_demo(sink, task_key="tune", use_real_nodus=True)
    plan_evt = next(e for e in sink.events if e["kind"] == "plan")
    assert plan_evt["source"] == "nodus"
    assert plan_evt["names"] == ["grep", "edit_file"]
    # args remplis par le harnais (le plan NODUS ne donne que des noms)
    calls = [e for e in sink.events if e["kind"] == "tool_call"]
    assert calls[0]["name"] == "grep" and "pattern" in json.loads(calls[0]["args"])
    assert "debug: false" in meta["workspace"]["config.yaml"]
    sink.close()


def test_run_demo_media_gold_delivers_to_gcs(monkeypatch):
    monkeypatch.setattr(demo, "_real_nodus_plan", lambda task: None)
    sink = _sink()
    meta = demo.run_demo(sink, task_key="media", use_real_nodus=True)
    plan_evt = next(e for e in sink.events if e["kind"] == "plan")
    assert plan_evt["names"] == ["read_file", "write_file", "gcs_upload", "bash"]
    calls = [e for e in sink.events if e["kind"] == "tool_call"]
    assert any(e["name"] == "gcs_upload" for e in calls)
    assert "gs://nodus-media-demo/production/shoot_day_brief.md" in sink.summary()
    assert "uploaded production/shoot_day_brief.md" in meta["summary"]
    sink.close()


def test_run_demo_media_real_nodus_appends_gcs_delivery(monkeypatch):
    # Le 324M émet ses 3 outils (pas gcs_upload) → le harnais append la livraison.
    monkeypatch.setattr(demo, "_real_nodus_plan",
                        lambda task: ["read_file", "write_file", "bash"])
    sink = _sink()
    meta = demo.run_demo(sink, task_key="media", use_real_nodus=True)
    plan_evt = next(e for e in sink.events if e["kind"] == "plan")
    assert plan_evt["names"] == ["read_file", "write_file", "bash", "gcs_upload"]
    calls = [e for e in sink.events if e["kind"] == "tool_call"]
    assert calls[-1]["name"] == "gcs_upload"
    sink.close()


def test_naive_plan_creates_nothing():
    ws = {}
    ok, out = demo.mock_execute("bash", {"command": "echo step1"}, ws)
    assert ok and "[simulated]" in out
    assert ws == {}


def test_naive_steps_is_a_copy():
    s1 = demo._naive_steps()
    s2 = demo._naive_steps()
    assert s1 == s2 and s1 is not s2
    s1[0][1]["command"] = "mutated"
    assert s2[0][1]["command"] == "echo step1"  # dicts internes copiés, pas partagés


# ── Remplissage d'args déterministe ────────────────────────────────────────

def test_default_args_deterministic_and_new_path():
    ws = {"src/main.py": "x"}
    a1 = demo._default_args("write_file", "Save a new file out.txt with a stub", ws)
    a2 = demo._default_args("write_file", "Save a new file out.txt with a stub", ws)
    assert a1 == a2
    assert a1["path"] == "out.txt"


def test_default_args_read_existing():
    ws = {"src/main.py": "x", "src/utils.py": "y"}
    a = demo._default_args("read_file", "Read src/utils.py", ws)
    assert a["path"] == "src/utils.py"


def test_default_args_edit_debug_when_present():
    ws = {"config.yaml": "debug: true\n"}
    a = demo._default_args("edit_file", "Find where 'debug' is configured, then update it to 'false'.", ws)
    assert a["path"] == "config.yaml"
    assert a["old"] == "debug: true" and a["new"] == "debug: false"


# ── Contraste plan vs no-plan ──────────────────────────────────────────────

def test_contrast_plan_beats_naive():
    task, plan_summary, naive_summary = demo.run_contrast("tune")
    assert "grep" in plan_summary and "edit_file" in plan_summary
    assert "plan [nodus]" in plan_summary
    assert "plan [naive]" in naive_summary
    assert "bash" in naive_summary and "edit_file" not in naive_summary
    assert task.startswith("Find where")


# ── Réal NODUS : ne jamais planter sans checkpoint ─────────────────────────

def test_real_nodus_plan_returns_none_without_checkpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("NODUS_PLAN_CKPT", str(tmp_path / "missing.pt"))
    assert demo._real_nodus_plan("any task") is None
