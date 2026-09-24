"""Plan gates autofix: no edit_file/write_file → triage only."""
from nge import config as _cfg
from nge import planner
from nge.orchestrator import NgeOrchestrator

TARGET = "packages/nodus/tests"


def _orch(tmp_path):
    return NgeOrchestrator(config=_cfg.load(
        fleet_mode="mock", sandbox_mode="mock", out_dir=tmp_path))


def test_plan_without_edit_tools_skips_autofix(tmp_path, monkeypatch):
    o = _orch(tmp_path)
    monkeypatch.setattr(planner, "plan", lambda *a, **k: planner.PlanResult(
        names=["bash", "brave_search"], source="stub"))
    rep = o.run({"task": "run tests and propose fixes", "shards": 3,
                 "target": TARGET})
    assert rep.fixes == []
    gated = [e for e in o.events if e["kind"] == "plan_gated_autofix"]
    assert gated and gated[0]["allowed"] is False
    skipped = [e for e in o.events if e["kind"] == "autofix_skipped"]
    assert skipped and skipped[0]["reason"] == "plan_has_no_edit_tools"
    assert rep.failures, "triage still runs"


def test_plan_with_edit_file_allows_autofix(tmp_path, monkeypatch):
    o = _orch(tmp_path)
    monkeypatch.setattr(planner, "plan", lambda *a, **k: planner.PlanResult(
        names=["bash", "edit_file"], source="stub"))
    rep = o.run({"task": "run tests and propose fixes", "shards": 3,
                 "target": TARGET})
    gated = [e for e in o.events if e["kind"] == "plan_gated_autofix"]
    assert gated and gated[0]["allowed"] is True
    assert "edit_file" in gated[0]["because"]
    assert rep.fixes, "code agent must run when the plan asks to edit"


def test_mission_off_still_wins_over_an_edit_plan(tmp_path, monkeypatch):
    o = _orch(tmp_path)
    monkeypatch.setattr(planner, "plan", lambda *a, **k: planner.PlanResult(
        names=["edit_file"], source="stub"))
    rep = o.run({"task": "t", "shards": 2, "target": TARGET, "auto_fix": False})
    assert rep.fixes == []
    assert not [e for e in o.events if e["kind"] == "plan_gated_autofix"]
    assert [e for e in o.events if e["kind"] == "autofix_skipped"
            ][0]["reason"] == "disabled by mission"


def test_plan_allows_autofix_helper():
    assert NgeOrchestrator._plan_allows_autofix(["bash", "edit_file"])
    assert NgeOrchestrator._plan_allows_autofix(["write_file"])
    assert not NgeOrchestrator._plan_allows_autofix(["bash", "brave_search"])
    assert not NgeOrchestrator._plan_allows_autofix([])
