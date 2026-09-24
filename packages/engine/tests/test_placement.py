"""Placement: don't migrate a shard onto another hot / full GPU."""
from nge.fleet import placement as P


def _node(nid, *, temp, mem_used, mem_total=80.0, util=40.0, health="ok",
          state="ready", efficiency=0.8):
    return {
        "id": nid, "state": state, "temp_c": temp, "util_pct": util,
        "mem_used_gb": mem_used, "mem_total_gb": mem_total,
        "health": health, "efficiency": efficiency, "power_w": 400.0,
    }


def test_picks_coolest_with_free_mem():
    cands = [
        _node("hot", temp=92, mem_used=10, health="throttle"),
        _node("warm", temp=80, mem_used=10, health="warm"),
        _node("ok-busy", temp=70, mem_used=70, util=50),
        _node("ok-roomy", temp=65, mem_used=20, util=30),
    ]
    d = P.pick_replacement(cands)
    assert d.node_id == "ok-roomy"
    assert d.score > 0
    assert any("hot:" in r for r in d.refused)
    assert any("warm:" in r for r in d.refused)


def test_refuses_all_throttle():
    cands = [
        _node("a", temp=90, mem_used=10, health="throttle"),
        _node("b", temp=91, mem_used=10, health="throttle"),
    ]
    d = P.pick_replacement(cands)
    assert d.node_id is None
    assert "no eligible" in d.reason


def test_mem_floor_and_exclude():
    cands = [
        _node("tiny", temp=50, mem_used=75, mem_total=80),  # 5 GB free
        _node("big", temp=55, mem_used=10, mem_total=80),
    ]
    d = P.pick_replacement(cands, needs=P.WorkloadNeeds(min_mem_free_gb=8),
                           exclude_ids=["big"])
    assert d.node_id is None
    assert any("tiny:" in r and "mem_free" in r for r in d.refused)


def test_allow_warm_when_asked():
    cands = [_node("w", temp=79, mem_used=10, health="warm")]
    no = P.pick_replacement(cands, needs=P.WorkloadNeeds(allow_warm=False,
                                                         max_temp_c=80))
    assert no.node_id is None
    yes = P.pick_replacement(cands, needs=P.WorkloadNeeds(allow_warm=True,
                                                          max_temp_c=80))
    assert yes.node_id == "w"


def test_orchestrator_emits_placement(tmp_path, monkeypatch):
    from nge import config as _cfg
    from nge import planner
    from nge.orchestrator import NgeOrchestrator

    monkeypatch.setattr(planner, "plan", lambda *a, **k: planner.PlanResult(
        names=["bash"], source="stub"))
    o = NgeOrchestrator(config=_cfg.load(
        fleet_mode="mock", sandbox_mode="mock", out_dir=tmp_path))
    o.run({"task": "t", "shards": 3, "target": "packages/nodus/tests",
           "gpu_type": "H100", "self_heal": True, "auto_fix": False})
    kinds = [e["kind"] for e in o.events]
    assert "gpu_placement" in kinds
    assert "gpu_remediation" in kinds
    placed = [e for e in o.events
              if e["kind"] == "gpu_placement" and e.get("chosen")]
    assert placed, "expected a successful placement after provision"
    assert placed[0]["chosen"].startswith("nb-h100-")
