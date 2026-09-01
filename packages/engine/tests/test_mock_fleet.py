"""MockFleet: deterministic lifecycle + telemetry."""
from nge.fleet.mock import MockFleet
from nge.fleet import telemetry


def test_provision_allocate_release():
    f = MockFleet()
    nodes = f.provision(3, gpu_type="H100")
    assert [n.id for n in nodes] == ["nb-h100-00", "nb-h100-01", "nb-h100-02"]

    n = f.allocate("job-a")
    assert n.state == "allocated" and n.job == "job-a"

    released = f.release()
    assert set(released) == {"nb-h100-00", "nb-h100-01", "nb-h100-02"}
    assert f.nodes() == []


def test_status_shapes_and_health():
    f = MockFleet()
    f.provision(2)
    f.allocate("busy")
    rows = f.status()
    assert len(rows) == 2
    for r in rows:
        assert 0 <= r.util_pct <= 100
        assert r.health in ("ok", "warm", "throttle")
        assert 0.0 <= r.efficiency <= 1.0
        assert r.mem_used_gb <= r.mem_total_gb


def test_status_is_deterministic():
    a = MockFleet(); a.provision(2); a.allocate("j")
    b = MockFleet(); b.provision(2); b.allocate("j")
    assert [r.as_dict() for r in a.status()] == [r.as_dict() for r in b.status()]


def test_allocate_without_ready_node_raises():
    import pytest
    f = MockFleet()
    with pytest.raises(RuntimeError):
        f.allocate("nope")


def test_telemetry_thresholds():
    assert telemetry.health_from_metrics(90, 80, 400) == "throttle"
    assert telemetry.health_from_metrics(80, 80, 400) == "warm"
    assert telemetry.health_from_metrics(50, 80, 400) == "ok"
    assert telemetry.efficiency_score(80, 700) > telemetry.efficiency_score(5, 700)
