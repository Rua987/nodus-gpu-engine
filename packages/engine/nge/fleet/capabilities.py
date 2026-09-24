"""Preflight: what GPU tooling exists *here*, and what the fleet image implies.

``nvidia-smi`` works on GeForce **and** H100/H200 (driver CLI). ``dcgmi`` is the
optional datacenter fleet layer on top. Neither being present on the *host*
does not prove Token Factory nodes lack a GPU — that depends on the sandbox
**image**. This module makes both facts visible before a blind run.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from nge.fleet import telemetry as _tele

# Images / hints that usually ship an NVIDIA stack inside the container.
_GPU_IMAGE_HINTS = ("nvidia", "cuda", "pytorch", "tensorflow", "nvcr.io",
                    "gpu", "h100", "h200", "a100", "l40")


def _which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def _run_ok(argv: List[str], timeout: float = 5.0) -> bool:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def probe_host() -> Dict[str, Any]:
    """Tools on the machine running the engine (laptop / CI), not TF nodes."""
    smi_path = _which("nvidia-smi")
    dcgmi_path = _which("dcgmi")
    smi_ok = bool(smi_path) and _run_ok(["nvidia-smi", "-L"])
    dcgmi_ok = bool(dcgmi_path) and _run_ok(["dcgmi", "discovery", "-l"])
    # discovery -l can fail on some installs; path alone still counts as "present"
    if dcgmi_path and not dcgmi_ok:
        dcgmi_ok = True  # binary exists — treat as available tooling
    tools: List[str] = []
    if smi_ok:
        tools.append("nvidia-smi")
    elif smi_path:
        tools.append("nvidia-smi(broken)")
    if dcgmi_path:
        tools.append("dcgmi")
    return {
        "nvidia_smi": smi_ok,
        "dcgmi": bool(dcgmi_path),
        "tools": tools,
        "summary": (
            ", ".join(tools) if tools else "none (no nvidia-smi / dcgmi on PATH)"
        ),
    }


def image_suggests_gpu(image: str) -> bool:
    img = (image or "").strip().lower()
    if not img:
        return False
    return any(h in img for h in _GPU_IMAGE_HINTS)


def fleet_expectation(cfg) -> Dict[str, Any]:
    """What we *expect* node probes to return, before spending a sandbox call.

    Contree Token Factory sandboxes are CPU microVMs today (no GPU in spawn
    ``resources_limits``). A CUDA image name alone must **not** flip heal ON —
    only an explicit ``NGE_FLEET_HAS_GPU=1`` claims a real device.
    """
    mode = (getattr(cfg, "fleet_mode", None) or "mock").lower()
    if mode == "mock":
        return {
            "probe_kind": _tele.PROBE_SYNTHETIC,
            "real_gpu_metrics": True,
            "image": "(mock)",
            "reason": "MockFleet emits synthetic H100-class telemetry",
            "image_hints_gpu": False,
        }
    if mode == "compute":
        return {
            "probe_kind": _tele.PROBE_NVIDIA,
            "real_gpu_metrics": True,
            "image": "(compute-vm)",
            "reason": "Nebius Compute GPU VM path (skeleton — needs SA + Go)",
            "image_hints_gpu": True,
        }

    image = (getattr(cfg, "nebius_fleet_image", None)
             or os.environ.get("NGE_FLEET_IMAGE")
             or "python:3.12-slim")
    hints = image_suggests_gpu(image)
    force = (os.environ.get("NGE_FLEET_HAS_GPU") or "").strip().lower()
    if force in ("1", "true", "yes", "on"):
        expect_real = True
        reason = "NGE_FLEET_HAS_GPU=1 (operator asserts NVIDIA device in sandbox)"
    elif force in ("0", "false", "no", "off"):
        expect_real = False
        reason = "NGE_FLEET_HAS_GPU=0"
    else:
        # TF Contree: no GPU passthrough in API — default expect cpu-fallback
        expect_real = False
        reason = (
            f"Token Factory microVM (image={image})"
            + ("; name looks CUDA-ish but TF has no GPU device unless "
               "NGE_FLEET_HAS_GPU=1" if hints else
               "; expect cpu-fallback after probe")
        )

    return {
        "probe_kind": (_tele.PROBE_NVIDIA if expect_real else _tele.PROBE_CPU),
        "real_gpu_metrics": expect_real,
        "image": image,
        "reason": reason,
        "image_hints_gpu": hints,
    }


def require_real_gpu_env() -> bool:
    return (os.environ.get("NGE_REQUIRE_REAL_GPU") or "").strip().lower() in (
        "1", "true", "yes", "on")


class RealGpuRequired(RuntimeError):
    """Raised when NGE_REQUIRE_REAL_GPU=1 but the setup cannot provide metrics."""


def assess(cfg) -> Dict[str, Any]:
    host = probe_host()
    fleet = fleet_expectation(cfg)
    return {
        "host": host,
        "fleet": fleet,
        "ok_for_thermal_heal": bool(fleet["real_gpu_metrics"]),
        "require_real_gpu": require_real_gpu_env(),
    }


def format_banner(report: Dict[str, Any]) -> str:
    host = report["host"]
    fleet = report["fleet"]
    heal = "YES" if report["ok_for_thermal_heal"] else "NO (heal gated)"
    lines = [
        f"[capabilities] host tools: {host['summary']}",
        f"[capabilities] fleet expect probe={fleet['probe_kind']}  "
        f"image={fleet['image']}",
        f"[capabilities] reason: {fleet['reason']}",
        f"[capabilities] thermal/efficiency heal: {heal}",
    ]
    if report["require_real_gpu"]:
        lines.append("[capabilities] NGE_REQUIRE_REAL_GPU=1 "
                     "(refuse start without real GPU metrics)")
    return "\n".join(lines)


def preflight(cfg, *, emit=None) -> Dict[str, Any]:
    """Assess + optional emit; raise if require-real-gpu and fleet cannot deliver."""
    report = assess(cfg)
    if emit is not None:
        emit("capabilities", **{
            "host_tools": report["host"]["tools"],
            "host_summary": report["host"]["summary"],
            "expect_probe": report["fleet"]["probe_kind"],
            "expect_real_gpu": report["fleet"]["real_gpu_metrics"],
            "fleet_image": report["fleet"]["image"],
            "reason": report["fleet"]["reason"],
            "heal_enabled": report["ok_for_thermal_heal"],
        })
    if report["require_real_gpu"] and not report["ok_for_thermal_heal"]:
        raise RealGpuRequired(
            "NGE_REQUIRE_REAL_GPU=1 but this fleet setup is not expected to "
            f"expose nvidia-smi metrics ({report['fleet']['reason']}). "
            "Use a CUDA/NVIDIA image, set NGE_FLEET_HAS_GPU=1 if you know the "
            "image has a driver, or unset NGE_REQUIRE_REAL_GPU."
        )
    return report
