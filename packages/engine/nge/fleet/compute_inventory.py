"""Compute Phase 1: what this account can run, read without creating anything.

Every call here is a ``get`` or a ``list``; ``tests/test_compute_inventory.py``
scans this file and fails if a create / update / delete / start / stop ever
appears. Nothing is billed.

Why it scans every project of the tenant and not just the configured one: the
first project offered for Compute (eu-west2) listed one GPU platform, a B300 -
no L40S, no H100. The tenant has a default project per region, and the
catalogue differs per region. Picking the Phase 2 target needs all of them.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

# preferred Phase 2 targets, cheapest first (docs/COMPUTE_GPU.md, section 4)
PREFERRED_PLATFORMS = ("gpu-l40s-a", "gpu-l40s-d", "gpu-h100-sxm", "gpu-h200-sxm")
CUDA_FAMILY_HINT = "cuda"
# The family Nebius' own VM docs use, pinned; a "-latest" family moves under
# you and "-serverless" is not a standalone-VM image. Alphabetical order
# picked ubuntu22.04-cuda12 instead.
PREFERRED_IMAGES = ("ubuntu24.04-cuda13.0", "ubuntu24.04-cuda12", "ubuntu22.04-cuda12")


def pick_image(cuda_images: List[str]) -> Optional[str]:
    families = [c.split(" ")[0] for c in cuda_images if "AMD64" in c.upper()]
    for want in PREFERRED_IMAGES:
        if want in families:
            return want
    usable = [f for f in families if "latest" not in f and "serverless" not in f]
    return sorted(usable)[-1] if usable else None


def build_sdk(engine_dir: Path):
    """An authenticated SDK channel, from the Phase 0 credentials file.

    TLS roots come from certifi: on Windows the SDK otherwise insists on the
    ``certifi-win32`` package to read the system store and refuses to start.
    """
    import certifi
    import grpc
    from nebius.sdk import SDK

    roots = Path(certifi.where()).read_bytes()
    return SDK(credentials_file_name=str(engine_dir / ".nebius_sa_credentials.json"),
               tls_credentials=grpc.ssl_channel_credentials(root_certificates=roots),
               user_agent_prefix="nodus-gpu-engine/compute-inventory")


class NebiusReadApi:
    """The only five calls Phase 1 makes. Each returns plain data."""

    def __init__(self, sdk) -> None:
        import nebius.api.nebius.compute.v1 as compute
        import nebius.api.nebius.iam.v2 as iam
        import nebius.api.nebius.vpc.v1 as vpc
        self._c, self._iam, self._vpc = compute, iam, vpc
        self._projects = iam.ProjectServiceClient(sdk)
        self._platforms = compute.PlatformServiceClient(sdk)
        self._images = compute.ImageServiceClient(sdk)
        self._subnets = vpc.SubnetServiceClient(sdk)

    def get_project(self, project_id: str) -> Dict[str, str]:
        p = self._projects.get(self._iam.GetProjectRequest(id=project_id)).wait()
        return {"id": p.metadata.id, "name": p.metadata.name,
                "region": p.spec.region, "tenant": p.metadata.parent_id}

    def list_projects(self, tenant_id: str) -> List[Dict[str, str]]:
        r = self._projects.list(self._iam.ListProjectsRequest(parent_id=tenant_id)).wait()
        return [{"id": p.metadata.id, "name": p.metadata.name, "region": p.spec.region}
                for p in r.items]

    def list_platforms(self, project_id: str) -> List[Dict[str, Any]]:
        r = self._platforms.list(self._c.ListPlatformsRequest(parent_id=project_id)).wait()
        return [{"name": p.metadata.name, "human": p.spec.human_readable_name,
                 "presets": [{"name": pr.name, "gpu": pr.resources.gpu_count,
                              "vcpu": pr.resources.vcpu_count,
                              "ram_gib": pr.resources.memory_gibibytes}
                             for pr in p.spec.presets]}
                for p in r.items]

    def list_public_images(self, region: str) -> List[Dict[str, str]]:
        r = self._images.list_public(self._c.ListPublicRequest(region=region)).wait()
        return [{"family": i.spec.image_family,
                 "arch": getattr(i.spec.cpu_architecture, "name", str(i.spec.cpu_architecture))}
                for i in r.items]

    def list_subnets(self, project_id: str) -> List[Dict[str, str]]:
        r = self._subnets.list(self._vpc.ListSubnetsRequest(parent_id=project_id)).wait()
        return [{"id": s.metadata.id, "name": s.metadata.name} for s in r.items]


def _try(errors: List[str], where: str, fn, default):
    try:
        return fn()
    except Exception as exc:             # one region failing must not hide the rest
        errors.append(f"{where}: {type(exc).__name__}: {str(exc)[:200]}")
        return default


def inventory(api, project_id: str) -> Dict[str, Any]:
    errors: List[str] = []
    home = api.get_project(project_id)       # if auth fails, fail loudly here
    projects = _try(errors, "list_projects", lambda: api.list_projects(home["tenant"]),
                    [home])
    regions = []
    images_by_region: Dict[str, List[Dict[str, str]]] = {}
    for p in sorted(projects, key=lambda x: x["region"]):
        reg = p["region"]
        if reg not in images_by_region:
            images_by_region[reg] = _try(errors, f"images {reg}",
                                         lambda: api.list_public_images(reg), [])
        platforms = _try(errors, f"platforms {reg}",
                         lambda: api.list_platforms(p["id"]), [])
        regions.append({
            "region": reg, "project_id": p["id"], "project_name": p["name"],
            "gpu_platforms": [pl for pl in platforms
                              if any(pr["gpu"] for pr in pl["presets"])],
            "cpu_platforms": [pl["name"] for pl in platforms
                              if not any(pr["gpu"] for pr in pl["presets"])],
            "subnets": _try(errors, f"subnets {reg}", lambda: api.list_subnets(p["id"]), []),
            "cuda_images": sorted({f"{i['family']} ({i['arch']})"
                                   for i in images_by_region[reg]
                                   if CUDA_FAMILY_HINT in (i["family"] or "")}),
        })
    return {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "home_project": home, "regions": regions, "errors": errors}


def recommend(inv: Dict[str, Any],
              prefer: Iterable[str] = PREFERRED_PLATFORMS) -> Optional[Dict[str, Any]]:
    """First preferred platform with a 1-GPU preset, in a region that also has a
    subnet and an amd64 CUDA image - everything Phase 2 needs to boot it."""
    for name in prefer:
        for r in inv["regions"]:
            image = pick_image(r["cuda_images"])
            if not (r["subnets"] and image):
                continue
            for pl in r["gpu_platforms"]:
                if pl["name"] != name:
                    continue
                one = [pr for pr in pl["presets"] if pr["gpu"] == 1]
                if one:
                    return {"region": r["region"], "project_id": r["project_id"],
                            "platform": name, "preset": one[0]["name"],
                            "subnet_id": r["subnets"][0]["id"],
                            "image_family": image}
    return None


def format_inventory(inv: Dict[str, Any], rec: Optional[Dict[str, Any]]) -> str:
    lines = [f"Compute Phase 1 - read-only inventory ({inv['generated_at']}), "
             f"configured project in {inv['home_project']['region']}"]
    for r in inv["regions"]:
        gpus = ", ".join(
            pl["name"] + (f" [1-GPU: {next(pr['name'] for pr in pl['presets'] if pr['gpu'] == 1)}]"
                          if any(pr["gpu"] == 1 for pr in pl["presets"]) else " [no 1-GPU preset]")
            for pl in r["gpu_platforms"]) or "(no GPU platform)"
        lines.append(f"  {r['region']:<12} {gpus}  subnets={len(r['subnets'])} "
                     f"cuda_images={len(r['cuda_images'])}")
    if rec:
        lines.append(f"Phase 2 target: {rec['platform']} / {rec['preset']} in {rec['region']} "
                     f"(project {rec['project_id']}, subnet {rec['subnet_id']}, "
                     f"image family {rec['image_family']})")
    else:
        lines.append("Phase 2 target: none of the preferred platforms is bootable here")
    if inv["errors"]:
        lines.append("errors:")
        lines += [f"  - {e}" for e in inv["errors"]]
    lines.append("Listed is not reserved: capacity is only known when a VM is created.")
    return "\n".join(lines)


def save(inv: Dict[str, Any], rec: Optional[Dict[str, Any]], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"compute_inventory_{inv['generated_at'].replace(':', '').replace('-', '')}.json"
    path.write_text(json.dumps({**inv, "phase2_target": rec}, indent=2), encoding="utf-8")
    return path
