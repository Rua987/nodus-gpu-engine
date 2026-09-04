"""Planner checkpoint resolution and the loudness of the fallback.

Regression: with no checkpoint on disk `try_plan_tool_names` returns None
without raising, so every run silently planned with the hand-written keyword
heuristic while reporting a vague "declined". Every demo printed
`plan(heuristic)` for weeks and nobody read it.
"""
import pytest

from nge import config as _cfg
from nge import planner


class _Cfg:
    def __init__(self, ckpt=""):
        self.nodus_plan_ckpt = ckpt


# -- resolution --------------------------------------------------------------

def test_resolves_the_vendored_default_when_nothing_is_set(monkeypatch):
    monkeypatch.delenv("NODUS_PLAN_CKPT", raising=False)
    assert planner.resolve_ckpt(None) == planner.DEFAULT_CKPT
    assert planner.resolve_ckpt(_Cfg("")) == planner.DEFAULT_CKPT


def test_env_overrides_the_default(monkeypatch, tmp_path):
    p = tmp_path / "w.pt"
    monkeypatch.setenv("NODUS_PLAN_CKPT", str(p))
    assert planner.resolve_ckpt(None) == p


def test_config_wins_over_env(monkeypatch, tmp_path):
    env_p, cfg_p = tmp_path / "env.pt", tmp_path / "cfg.pt"
    monkeypatch.setenv("NODUS_PLAN_CKPT", str(env_p))
    assert planner.resolve_ckpt(_Cfg(str(cfg_p))) == cfg_p


def test_config_field_exists_and_is_loaded():
    assert hasattr(_cfg.load(), "nodus_plan_ckpt")


# -- the fallback must be loud ----------------------------------------------

def test_missing_checkpoint_is_reported_as_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("NODUS_PLAN_CKPT", str(tmp_path / "absent.pt"))
    path, exists, note = planner.ckpt_status(None)
    assert exists is False
    assert "NOT FOUND" in note
    assert str(path) in note                      # says where it looked
    assert "NODUS_PLAN_CKPT" in note              # says how to fix it


def test_present_checkpoint_is_reported_with_its_size(monkeypatch, tmp_path):
    p = tmp_path / "w.pt"
    p.write_bytes(b"x" * 2_000_000)
    monkeypatch.setenv("NODUS_PLAN_CKPT", str(p))
    _, exists, note = planner.ckpt_status(None)
    assert exists is True and "w.pt" in note and "MB" in note


def test_plan_without_a_checkpoint_is_flagged_degraded(monkeypatch, tmp_path):
    """The bug: this used to be indistinguishable from a real 324M plan."""
    monkeypatch.setenv("NODUS_PLAN_CKPT", str(tmp_path / "absent.pt"))
    r = planner.plan("Run the pytest suite", allow_nemotron=False)
    assert r.degraded is True
    assert r.source == "heuristic"
    assert "NOT FOUND" in r.note
    assert r.names == planner._heuristic("Run the pytest suite")


def test_the_324m_planner_is_not_even_called_without_weights(monkeypatch, tmp_path):
    """Guards the wasted-import path *and* documents the intent: no weights,
    no attempt, no misleading 'declined'."""
    monkeypatch.setenv("NODUS_PLAN_CKPT", str(tmp_path / "absent.pt"))
    called = []
    import sys, types
    fake = types.ModuleType("nodus_plan_local")
    fake.try_plan_tool_names = lambda *a, **k: called.append(1) or ["bash"]
    monkeypatch.setitem(sys.modules, "nodus_plan_local", fake)

    r = planner.plan("anything", allow_nemotron=False)
    assert called == [], "planner must not run without its weights"
    assert r.degraded is True


def test_a_real_plan_is_not_degraded(monkeypatch, tmp_path):
    p = tmp_path / "w.pt"
    p.write_bytes(b"x")
    monkeypatch.setenv("NODUS_PLAN_CKPT", str(p))
    import sys, types
    fake = types.ModuleType("nodus_plan_local")
    fake.try_plan_tool_names = lambda *a, **k: ["bash", "edit_file"]
    monkeypatch.setitem(sys.modules, "nodus_plan_local", fake)

    r = planner.plan("Fix the failing test", allow_nemotron=False)
    assert r.source == "nodus-324m" and r.degraded is False
    assert r.names == ["bash", "edit_file"]
    assert "planned by 324M" in r.note


def test_torch_missing_is_not_reported_as_declined(monkeypatch, tmp_path):
    """Found on a fresh venv: with weights on disk but torch absent, the
    planner said "ran but declined this task". It had not run at all -
    try_plan_tool_names returns None for a load failure exactly as it does for
    a declined task, so the note claimed more than it knew."""
    import builtins
    p = tmp_path / "w.pt"
    p.write_bytes(b"x")
    monkeypatch.setenv("NODUS_PLAN_CKPT", str(p))

    real_import = builtins.__import__

    def no_torch(name, *a, **k):
        if name == "torch":
            raise ImportError("No module named 'torch'")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_torch)

    r = planner.plan("anything", allow_nemotron=False)
    assert r.degraded is True and r.source == "heuristic"
    assert "torch is not installed" in r.note
    assert "declined" not in r.note, "it never ran - do not say it declined"


def test_no_plan_does_not_claim_the_model_declined(monkeypatch, tmp_path):
    """None from the vendored helper means declined OR invalid OR failed to
    load; the note must not pick one."""
    p = tmp_path / "w.pt"
    p.write_bytes(b"x")
    monkeypatch.setenv("NODUS_PLAN_CKPT", str(p))
    import sys, types
    fake = types.ModuleType("nodus_plan_local")
    fake.try_plan_tool_names = lambda *a, **k: None          # declined
    monkeypatch.setitem(sys.modules, "nodus_plan_local", fake)

    r = planner.plan("anything", allow_nemotron=False)
    assert r.degraded is True
    assert "declined the task, or" in r.note, "both causes must be named"
    assert "NOT FOUND" not in r.note


def test_a_raising_model_degrades_instead_of_exploding(monkeypatch, tmp_path):
    p = tmp_path / "w.pt"
    p.write_bytes(b"x")
    monkeypatch.setenv("NODUS_PLAN_CKPT", str(p))
    import sys, types
    fake = types.ModuleType("nodus_plan_local")

    def boom(*a, **k):
        raise RuntimeError("CUDA OOM")
    fake.try_plan_tool_names = boom
    monkeypatch.setitem(sys.modules, "nodus_plan_local", fake)

    r = planner.plan("anything", allow_nemotron=False)
    assert r.degraded is True and r.source == "heuristic"
    assert "failed to run" in r.note and "CUDA OOM" in r.note


# -- it must reach the run ---------------------------------------------------

def test_orchestrator_emits_plan_degraded(tmp_path):
    """Overrides the config field, not just the env: config wins over env, so
    setenv alone would silently test the wrong thing on a machine that has a
    checkpoint configured."""
    from nge.orchestrator import NgeOrchestrator
    o = NgeOrchestrator(config=_cfg.load(
        fleet_mode="mock", sandbox_mode="mock", out_dir=tmp_path,
        nodus_plan_ckpt=str(tmp_path / "absent.pt")))
    o.run({"task": "run tests", "shards": 1, "target": "t"})

    plan_evt = next(e for e in o.events if e["kind"] == "plan")
    assert plan_evt["degraded"] is True
    assert [e for e in o.events if e["kind"] == "plan_degraded"]
    # the note must name *the configured* path - asserting only on `degraded`
    # would still pass if the orchestrator ignored the config and fell through
    # to the vendored default, which is also absent.
    assert str(tmp_path / "absent.pt") in plan_evt["note"]
