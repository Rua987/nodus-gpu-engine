"""On a real GPU that carries no GPU work, low efficiency is not pressure.

The shards are pytest runs in Token Factory sandboxes; the Compute GPU only
reports telemetry. The real idle L40S of Phase 2 read 27 C, 0 %, 67.8 W ->
efficiency 0.0, below MIN_EFFICIENCY: the heal loop would have migrated
shards off a perfectly healthy node. Heat and power must still count.
"""
import pytest

from nge import config as _cfg
from nge.fleet import telemetry
from nge.orchestrator import NgeOrchestrator, ShardResult
from nge.tools import handlers


def _tele(temp_c, util, power_w, probe_kind="nvidia-smi"):
    cls = "datacenter" if probe_kind == "nvidia-smi" else "synthetic"
    return {"id": "nb-h100-00", "util_pct": util, "temp_c": temp_c, "power_w": power_w,
            "mem_used_gb": 0.0, "mem_total_gb": 45.0, "probe_kind": probe_kind,
            "gpu_class": cls, "gpu_name": "NVIDIA L40S",
            "health": telemetry.health_from_metrics(temp_c, util, power_w, "datacenter"),
            "efficiency": telemetry.efficiency_score(util, power_w, "datacenter")}


@pytest.fixture
def orch(tmp_path):
    o = NgeOrchestrator(config=_cfg.load(fleet_mode="mock", sandbox_mode="mock",
                                         out_dir=tmp_path))
    handlers.reset_state(o.config)
    handlers.gpu_provision(n=2, gpu_type="H100")
    handlers.gpu_allocate(job="shard-0")
    return o


def _sr():
    return ShardResult(index=0, node_id="nb-h100-00", command="pytest x",
                       exit_code=1, duration_s=1.0)


def _kinds(o):
    return [e["kind"] for e in o.events]


def test_the_real_idle_l40s_reading_is_not_pressure(orch):
    tele = _tele(27.0, 0.0, 67.8)                 # the Phase 2 reading
    assert tele["health"] == "ok" and tele["efficiency"] == 0.0
    orch._react_to_pressure(_sr(), tele, "packages/nodus/tests", [])
    kinds = _kinds(orch)
    assert "gpu_efficiency_skipped" in kinds
    assert "gpu_pressure" not in kinds and "gpu_remediation" not in kinds


def test_declared_gpu_work_makes_low_efficiency_count_again(orch):
    orch._react_to_pressure(_sr(), _tele(27.0, 0.0, 67.8), "packages/nodus/tests", [],
                            gpu_workload=True)
    assert "gpu_pressure" in _kinds(orch)


def test_heat_on_a_real_gpu_is_pressure_regardless(orch):
    orch._react_to_pressure(_sr(), _tele(90.0, 0.0, 120.0), "packages/nodus/tests", [])
    kinds = _kinds(orch)
    assert "gpu_pressure" in kinds and "gpu_efficiency_skipped" not in kinds


def test_synthetic_mock_telemetry_is_unchanged(orch):
    orch._react_to_pressure(_sr(), _tele(60.0, 5.0, 500.0, probe_kind="synthetic"),
                            "packages/nodus/tests", [])
    assert "gpu_pressure" in _kinds(orch)


def test_scenario_flag_reaches_the_heal_decision(tmp_path, monkeypatch):
    seen = []
    real = NgeOrchestrator._react_to_pressure

    def spy(self, *a, **kw):
        seen.append(kw.get("gpu_workload"))
        return real(self, *a, **kw)
    monkeypatch.setattr(NgeOrchestrator, "_react_to_pressure", spy)
    o = NgeOrchestrator(config=_cfg.load(fleet_mode="mock", sandbox_mode="mock",
                                         out_dir=tmp_path))
    o.run({"task": "run tests", "shards": 2, "target": "packages/nodus/tests"})
    o.run({"task": "run tests", "shards": 2, "target": "packages/nodus/tests",
           "gpu_workload": True})
    assert seen[:2] == [False, False] and seen[2:] == [True, True]
