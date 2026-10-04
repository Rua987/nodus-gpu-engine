"""ConsoleWatch renders the fleet + the migration moment."""
import io

from nge.watch import ConsoleWatch, _bar


def test_bar_bounds():
    assert _bar(0, 0, 100, 10) == "░" * 10
    assert _bar(100, 0, 100, 10) == "█" * 10
    assert _bar(50, 0, 100, 10).count("█") == 5
    assert _bar(999, 0, 100, 10) == "█" * 10          # clamps


def _drive(w: ConsoleWatch):
    w.record("run_start", fleet_mode="mock", sandbox_mode="mock", jail=True)
    w.record("gpu_provision", provisioned=2,
             nodes=[{"id": "nb-h100-00"}, {"id": "nb-h100-02"}])
    w.record("shard_start", index=1, node_id="nb-h100-02")
    w.record("gpu_status", telemetry={"id": "nb-h100-02", "util_pct": 80,
             "temp_c": 91.0, "power_w": 715, "health": "throttle", "efficiency": 0.56})
    w.record("gpu_pressure", shard=1, node_id="nb-h100-02", health="throttle",
             efficiency=0.56, temp_c=91.0, power_w=715)
    w.record("gpu_provision_replacement", node_id="nb-h100-03", for_shard=1)
    w.record("gpu_remediation", shard=1, **{"from": "nb-h100-02", "to": "nb-h100-03"})
    w.record("gpu_release", released=["nb-h100-00", "nb-h100-03"])
    w.record("run_end", ok=True)


def test_watch_shows_fleet_and_migration():
    buf = io.StringIO()
    w = ConsoleWatch(stream=buf, delay=0.0, color=False)
    _drive(w)
    out = buf.getvalue()

    assert "nb-h100-02" in out and "nb-h100-03" in out
    assert "THROTTLE" in out
    assert "util" in out and "temp" in out and "%" in out
    assert "──▶" in out                       # migration arrow
    assert "migrate  shard 1" in out
    assert "<- nb-h100-02" in out             # replacement shows its origin
    assert "(freed)" in out                    # released nodes marked
    assert "run complete" in out


def test_watch_no_ansi_when_color_off():
    buf = io.StringIO()
    w = ConsoleWatch(stream=buf, delay=0.0, color=False)
    _drive(w)
    assert "\033[" not in buf.getvalue()


def test_watch_is_a_valid_telemetry_sink():
    # duck-typed: NgeOrchestrator only needs .record(kind, **fields)
    import tempfile
    from pathlib import Path
    from nge import config as _cfg
    from nge.orchestrator import NgeOrchestrator

    buf = io.StringIO()
    w = ConsoleWatch(stream=buf, delay=0.0, color=False)
    with tempfile.TemporaryDirectory() as d:
        cfg = _cfg.load(fleet_mode="mock", sandbox_mode="mock", out_dir=Path(d))
        rep = NgeOrchestrator(config=cfg, telemetry=w).run({
            "task": "run tests across the fleet and report",
            "shards": 3, "gpu_type": "H100", "target": "packages/nodus/tests",
        })
    out = buf.getvalue()
    assert rep.ok and rep.remediations
    assert "migrate  shard 2" in out
    assert "nb-h100-02" in out and "nb-h100-03" in out
    assert "fix OK" in out                     # auto-fix loop surfaced in the watch


def test_a_cpu_sandbox_is_not_drawn_as_an_idle_gpu():
    """Live film: Token Factory nodes have no GPU. Bars at 0 C marked OK read
    as a healthy H100; the row must say what the node is."""
    buf = io.StringIO()
    w = ConsoleWatch(stream=buf, color=False)
    w.record("capabilities", expect_probe="cpu-fallback", heal_enabled=False,
             host_summary="none")
    w.record("gpu_provision", provisioned=1, nodes=[{"id": "nb-cpu-00"}])
    w.record("shard_start", index=0, node_id="nb-cpu-00")
    w.record("gpu_status", telemetry={"id": "nb-cpu-00", "util_pct": 0, "temp_c": 0,
             "power_w": 0, "health": "ok", "probe_kind": "cpu-fallback"})
    rows = [l for l in buf.getvalue().splitlines() if l.startswith("  nb-cpu-00 ")]
    assert len(rows) >= 3                     # before and after the first probe
    for row in rows:
        assert "cpu sandbox" in row and "no GPU telemetry" in row
        assert "0.0C" not in row and "OK" not in row
