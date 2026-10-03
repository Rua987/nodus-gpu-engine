"""Nebius AI Cloud Compute GPU fleet (real VMs with nvidia-smi).

Distinct from :class:`nge.fleet.nebius.NebiusFleet`, which uses Token Factory
**Contree microVMs** (CPU only today). This module targets Compute instances
(``gpu-h100-sxm`` / ``gpu-h200-sxm`` …) via the Nebius Python SDK (``nebius``).

Status (2026-09-05): **skeleton** — interface + credential preflight only.
Provisioning a paid GPU VM requires an explicit operator **Go** (cost).
See ``docs/ENGINE_BACKLOG.md`` M1/M2 and ``docs/COMPUTE_GPU.md``.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

from nge.fleet.base import GpuFleet, GpuNode, GpuNodeStatus
from nge.fleet import telemetry


class ComputeGpuFleet(GpuFleet):
    """Real Nebius Compute GPU nodes — not Contree sandboxes."""

    mode = "compute"

    def __init__(self, config=None) -> None:
        from nge import config as _cfg
        self.cfg = config or _cfg.load()
        self._nodes: Dict[str, dict] = {}
        self._next = 0

    def provision(self, n: int, gpu_type: str = "H100") -> List[GpuNode]:
        raise NotImplementedError(
            "ComputeGpuFleet: not wired yet. Needs Nebius Compute SDK "
            "(platform gpu-h100-sxm / gpu-h200-sxm), SA credentials, subnet, "
            "boot disk (ubuntu*-cuda*). See docs/COMPUTE_GPU.md. "
            "Until then use fleet_mode=mock (demo) or nebius (TF Contree CPU)."
        )

    def status(self, node_id: Optional[str] = None) -> List[GpuNodeStatus]:
        raise NotImplementedError("ComputeGpuFleet.status: see provision()")

    def allocate(self, job: str, node_id: Optional[str] = None) -> GpuNode:
        raise NotImplementedError("ComputeGpuFleet.allocate: see provision()")

    def release(self, node_ids: Optional[List[str]] = None) -> List[str]:
        return []


def expected_probe_kind() -> str:
    """Compute VMs with CUDA images should expose nvidia-smi."""
    return telemetry.PROBE_NVIDIA


# Token Factory projects (the id Contree sandboxes and Nemotron use) look like
# ``aiproject-...``; they are not AI Cloud projects and cannot own a VM. Compute
# therefore reads its own project id, never NEBIUS_PROJECT_ID - which the live
# path already uses for Token Factory and must keep.
_TOKEN_FACTORY_PROJECT_PREFIX = "aiproject-"
_CREDENTIALS_DEFAULT = ".nebius_sa_credentials.json"


def _engine_dir() -> Path:
    from nge import config as _cfg
    return _cfg._ENGINE_DIR


def _credentials_file_check(path: Path) -> Optional[str]:
    """Validate a service-account credentials file offline, the way the SDK
    will read it (``subject-credentials``: RS256, iss == sub, a parseable PEM
    key). Returns None when usable, else why not. No network."""
    import json
    try:
        from nebius.base.service_account.credentials_file import (
            ServiceAccountCredentials)
        data = json.loads(path.read_text(encoding="utf-8"))
        creds = ServiceAccountCredentials.from_json(data)
        creds.subject_credentials.parse_private_key()
    except ImportError:
        return "nebius SDK not installed, cannot validate"
    except KeyError as exc:
        return f"missing field {exc} (expected subject-credentials: alg, private-key, kid, iss, sub)"
    except Exception as exc:                     # never echo the key itself
        return f"{type(exc).__name__}: {str(exc)[:160]}"
    return None


def check_credentials() -> dict:
    """Phase 0 preflight: can the Compute SDK authenticate, and against which
    project? Read-only - no API call, no VM, nothing created.

    Auth, in the SDK's own order of preference: a service-account credentials
    file (``NEBIUS_SA_CREDENTIALS_FILE`` or ``packages/engine/.nebius_sa_credentials.json``),
    the ``nebius`` CLI profile (``~/.nebius/config.yaml``), then
    ``NEBIUS_IAM_TOKEN`` - the only environment variable the SDK reads.
    Project: ``NEBIUS_COMPUTE_PROJECT_ID`` or ``.nebius_compute_project_id``.
    Subnet (needed from Phase 2): ``NEBIUS_SUBNET_ID`` or ``.nebius_compute_subnet_id``.
    """
    from nge import config as _cfg

    try:
        import importlib.metadata as _md
        sdk_version = _md.version("nebius")
        import nebius  # noqa: F401
        sdk = True
    except Exception:
        sdk, sdk_version = False, None

    iam = bool(os.environ.get("NEBIUS_IAM_TOKEN", "").strip())
    raw = os.environ.get("NEBIUS_SA_CREDENTIALS_FILE", "").strip()
    cred_path = Path(raw).expanduser() if raw else _engine_dir() / _CREDENTIALS_DEFAULT
    cred_error = None
    if cred_path.is_file():
        cred_error = _credentials_file_check(cred_path)
    elif raw:
        cred_error = "file not found"
    cred_ok = cred_path.is_file() and cred_error is None
    cli_profile = (Path("~/.nebius/config.yaml").expanduser()).is_file()

    project = _cfg.load_value("nebius_compute_project_id", "NEBIUS_COMPUTE_PROJECT_ID")
    project_error = None
    if project.startswith(_TOKEN_FACTORY_PROJECT_PREFIX):
        project_error = ("a Token Factory project id (aiproject-...), not an AI "
                         "Cloud project - Compute VMs need the AI Cloud one")
    elif project and not project.startswith("project-"):
        # Nebius ids name their resource type first. The first id offered for
        # this field was a tenantuseraccount-... (the signed-in user), which
        # the aiproject- check alone would have accepted.
        kind = project.split("-", 1)[0] if "-" in project else "unknown"
        project_error = (f"a {kind} id, not a project - an AI Cloud project id "
                         "starts with project-")
    subnet = _cfg.load_value("nebius_compute_subnet_id", "NEBIUS_SUBNET_ID")

    auth = ("credentials_file" if cred_ok else "cli_profile" if cli_profile
            else "iam_token" if iam else None)
    project_ok = bool(project) and project_error is None

    missing: List[str] = []
    if not sdk:
        missing.append("pip install nebius")
    if auth is None:
        missing.append("auth: a service-account credentials file "
                       f"(packages/engine/{_CREDENTIALS_DEFAULT} or NEBIUS_SA_CREDENTIALS_FILE)"
                       + (f" - current one: {cred_error}" if cred_error else "")
                       + ", or a `nebius` CLI profile, or NEBIUS_IAM_TOKEN")
    if not project_ok:
        missing.append("AI Cloud project id in NEBIUS_COMPUTE_PROJECT_ID or "
                       "packages/engine/.nebius_compute_project_id"
                       + (f" - current one is {project_error}" if project_error else ""))
    if not subnet:
        missing.append("(Phase 2) subnet id in NEBIUS_SUBNET_ID or "
                       "packages/engine/.nebius_compute_subnet_id")

    return {
        "sdk_installed": sdk,
        "sdk_version": sdk_version,
        "auth": auth,
        "iam_token": iam,
        "credentials_file": str(cred_path) if (raw or cred_path.is_file()) else None,
        "credentials_file_ok": cred_ok,
        "credentials_file_error": cred_error,
        "cli_profile": cli_profile,
        "project_id": project_ok,
        "project_id_error": project_error,
        "subnet_id": bool(subnet),
        "ready_for_wire": sdk and auth is not None and project_ok,
        "spawn_allowed": False,  # always False until explicit Go + code path
        "missing": missing,
    }


def format_checklist(report: dict) -> str:
    mark = lambda ok: "OK " if ok else "-- "              # noqa: E731
    lines = [
        "Compute Phase 0 - credentials preflight (no API call, no VM)",
        f"  {mark(report['sdk_installed'])} nebius SDK {report['sdk_version'] or ''}".rstrip(),
        f"  {mark(report['auth'] is not None)} auth: {report['auth'] or 'none'}",
        f"  {mark(report['project_id'])} AI Cloud project id",
        f"  {mark(report['subnet_id'])} subnet id (needed from Phase 2)",
        f"  ready_for_wire={report['ready_for_wire']}  spawn_allowed={report['spawn_allowed']}",
    ]
    if report["missing"]:
        lines.append("missing:")
        lines += [f"  - {m}" for m in report["missing"]]
    return "\n".join(lines)


if __name__ == "__main__":                       # pragma: no cover
    r = check_credentials()
    print(format_checklist(r))
    raise SystemExit(0 if r["ready_for_wire"] else 1)
