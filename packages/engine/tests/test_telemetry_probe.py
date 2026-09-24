"""Probe honesty: tagged nvidia-smi vs cpu-fallback; class thresholds."""
from nge.fleet import telemetry
from nge.fleet.nebius import _parse_probe


def test_parse_tagged_nvidia_smi():
    m = _parse_probe(
        "nvidia-smi,12,40960,81920,63,410.5,NVIDIA H100 80GB HBM3\n")
    assert m["probe_kind"] == "nvidia-smi"
    assert m["gpu_class"] == "datacenter"
    assert "H100" in m["gpu_name"]
    assert m["temp_c"] == 63.0 and m["power_w"] == 410.5


def test_parse_tagged_rtx_is_consumer():
    m = _parse_probe(
        "nvidia-smi,80,10000,24576,79,320.0,NVIDIA GeForce RTX 4090")
    assert m["probe_kind"] == "nvidia-smi"
    assert m["gpu_class"] == "consumer"


def test_parse_tagged_cpu_fallback():
    m = _parse_probe("cpu-fallback,35,512,3928,0,0,")
    assert m["probe_kind"] == "cpu-fallback"
    assert m["gpu_class"] == "none"
    assert m["temp_c"] == 0.0 and m["power_w"] == 0.0


def test_parse_legacy_lines_still_work():
    g = _parse_probe("12, 40960, 81920, 63, 410.5\n")
    assert g["probe_kind"] == "nvidia-smi" and g["temp_c"] == 63.0
    c = _parse_probe("35, 512, 3928, 0, 0")
    assert c["probe_kind"] == "cpu-fallback"


def test_has_real_gpu_metrics():
    assert telemetry.has_real_gpu_metrics({"probe_kind": "nvidia-smi"})
    assert telemetry.has_real_gpu_metrics({"probe_kind": "synthetic"})
    assert not telemetry.has_real_gpu_metrics({"probe_kind": "cpu-fallback"})
    assert not telemetry.has_real_gpu_metrics({"probe_kind": "failed"})
    assert not telemetry.has_real_gpu_metrics(None)


def test_consumer_throttles_earlier_than_datacenter():
    # 85 C: warm/ok on H100-class, throttle on RTX-class
    assert telemetry.health_from_metrics(85, 90, 300, "datacenter") in (
        "ok", "warm")
    assert telemetry.health_from_metrics(85, 90, 300, "consumer") == "throttle"
