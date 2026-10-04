"""Preflight capabilities: host tools + fleet image expectation."""
import pytest

from nge.fleet import capabilities as cap
from nge import config as _cfg


def test_image_suggests_gpu():
    assert cap.image_suggests_gpu("nvcr.io/nvidia/pytorch:24.01-py3")
    assert cap.image_suggests_gpu("nvidia/cuda:12.2.0-runtime")
    assert not cap.image_suggests_gpu("python:3.12-slim")
    assert not cap.image_suggests_gpu("")


def test_fleet_expectation_mock():
    cfg = _cfg.load(fleet_mode="mock", sandbox_mode="mock")
    e = cap.fleet_expectation(cfg)
    assert e["probe_kind"] == "synthetic"
    assert e["real_gpu_metrics"] is True


def test_fleet_expectation_nebius_slim(monkeypatch):
    monkeypatch.delenv("NGE_FLEET_HAS_GPU", raising=False)
    monkeypatch.delenv("NGE_FLEET_IMAGE", raising=False)
    cfg = _cfg.load(fleet_mode="nebius", sandbox_mode="token_factory")
    e = cap.fleet_expectation(cfg)
    assert e["real_gpu_metrics"] is False
    assert e["probe_kind"] == "cpu-fallback"
    assert "slim" in e["image"] or "python" in e["image"]


def test_fleet_expectation_cuda_image_still_no_device_without_flag(monkeypatch):
    """CUDA image name ≠ GPU passthrough on Token Factory Contree."""
    monkeypatch.delenv("NGE_FLEET_HAS_GPU", raising=False)
    monkeypatch.setenv("NGE_FLEET_IMAGE", "nvidia/cuda:12.2.0-runtime-ubuntu22.04")
    cfg = _cfg.load(fleet_mode="nebius")
    e = cap.fleet_expectation(cfg)
    assert e["real_gpu_metrics"] is False
    assert e["image_hints_gpu"] is True


def test_fleet_expectation_force_gpu(monkeypatch):
    monkeypatch.setenv("NGE_FLEET_HAS_GPU", "1")
    cfg = _cfg.load(fleet_mode="nebius")
    e = cap.fleet_expectation(cfg)
    assert e["real_gpu_metrics"] is True
    assert e["probe_kind"] == "nvidia-smi"


def test_require_real_gpu_refuses_slim(monkeypatch):
    monkeypatch.setenv("NGE_REQUIRE_REAL_GPU", "1")
    monkeypatch.delenv("NGE_FLEET_HAS_GPU", raising=False)
    cfg = _cfg.load(fleet_mode="nebius", sandbox_mode="token_factory")
    with pytest.raises(cap.RealGpuRequired):
        cap.preflight(cfg)


def test_require_real_gpu_allows_mock(monkeypatch):
    monkeypatch.setenv("NGE_REQUIRE_REAL_GPU", "1")
    cfg = _cfg.load(fleet_mode="mock", sandbox_mode="mock")
    r = cap.preflight(cfg)
    assert r["ok_for_thermal_heal"] is True


def test_orchestrator_emits_capabilities(tmp_path, monkeypatch):
    monkeypatch.delenv("NGE_REQUIRE_REAL_GPU", raising=False)
    from nge.orchestrator import NgeOrchestrator
    from nge import planner
    monkeypatch.setattr(planner, "plan", lambda *a, **k: planner.PlanResult(
        names=["bash"], source="stub"))
    o = NgeOrchestrator(config=_cfg.load(
        fleet_mode="mock", sandbox_mode="mock", out_dir=tmp_path))
    o.run({"task": "t", "shards": 1, "target": "packages/nodus/tests",
           "gpu_type": "H100", "self_heal": False, "auto_fix": False})
    caps = [e for e in o.events if e["kind"] == "capabilities"]
    assert caps and caps[0]["expect_probe"] == "synthetic"


def test_build_fleet_compute_refuses_to_spend_without_opt_in(monkeypatch):
    """No longer a skeleton (Phase 3): it creates paid VMs - but only on demand."""
    import pytest
    from nge.fleet import build_fleet
    from nge.fleet.compute import ComputeGpuFleet
    monkeypatch.delenv("NGE_COMPUTE_SPAWN", raising=False)
    f = build_fleet("compute")
    assert isinstance(f, ComputeGpuFleet)
    with pytest.raises(RuntimeError, match="NGE_COMPUTE_SPAWN"):
        f.provision(1)
    assert f.nodes() == [] and f.status() == []


def test_compute_check_credentials_no_spawn(monkeypatch):
    from nge.fleet import compute
    monkeypatch.delenv("NEBIUS_IAM_TOKEN", raising=False)
    monkeypatch.delenv("NEBIUS_SA_KEY_FILE", raising=False)
    monkeypatch.delenv("NEBIUS_SERVICE_ACCOUNT_FILE", raising=False)
    monkeypatch.delenv("YC_SERVICE_ACCOUNT_KEY_FILE", raising=False)
    monkeypatch.delenv("NEBIUS_PROJECT_ID", raising=False)
    monkeypatch.delenv("NEBIUS_FOLDER_ID", raising=False)
    monkeypatch.delenv("NEBIUS_SUBNET_ID", raising=False)
    d = compute.check_credentials()
    assert d["spawn_allowed"] is False
    assert d["ready_for_wire"] is False
    assert "sdk_installed" in d
