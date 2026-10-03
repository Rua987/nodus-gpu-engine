"""Compute Phase 1 inventory: aggregation, target choice, and read-only by
construction. A fake API stands in for Nebius - no network."""
import ast
import json
from pathlib import Path

import pytest

from nge.fleet import compute_inventory as ci

ENGINE = Path(__file__).resolve().parents[1]


def _pl(name, *presets):
    return {"name": name, "human": name,
            "presets": [{"name": n, "gpu": g, "vcpu": 8, "ram_gib": 32} for n, g in presets]}


class FakeApi:
    def __init__(self, broken_region=None, no_subnet=(), images=None):
        self.calls = []
        self.broken = broken_region
        self.no_subnet = set(no_subnet)
        self.images = images or {}
        self.projects = [
            {"id": "project-e04x", "name": "p-eu-west2", "region": "eu-west2"},
            {"id": "project-e00x", "name": "p-eu-north1", "region": "eu-north1"},
            {"id": "project-u00x", "name": "p-us-central1", "region": "us-central1"},
        ]
        self.platforms = {
            "project-e04x": [_pl("gpu-b300-sxm", ("1gpu-24vcpu-346gb", 1))],
            "project-e00x": [_pl("gpu-h100-sxm", ("1gpu-16vcpu-200gb", 1), ("8gpu", 8)),
                             _pl("gpu-l40s-a", ("1gpu-8vcpu-32gb", 1)),
                             _pl("gpu-gb300", ("4gpu", 4)),
                             _pl("cpu-d3", ("2vcpu-8gb", 0))],
            "project-u00x": [_pl("gpu-h200-sxm", ("1gpu-16vcpu-200gb", 1))],
        }

    def get_project(self, pid):
        self.calls.append(("get_project", pid))
        return {"id": pid, "name": "p-eu-west2", "region": "eu-west2", "tenant": "tenant-e00x"}

    def list_projects(self, tenant):
        self.calls.append(("list_projects", tenant))
        return self.projects

    def list_platforms(self, pid):
        self.calls.append(("list_platforms", pid))
        if self.broken and pid == self.broken:
            raise PermissionError("denied")
        return self.platforms[pid]

    def list_public_images(self, region):
        self.calls.append(("list_public_images", region))
        return self.images.get(region, [
            {"family": "ubuntu24.04-cuda13-latest", "arch": "AMD64"},
            {"family": "ubuntu24.04-cuda13.0", "arch": "AMD64"},
            {"family": "ubuntu24.04-cuda13.0-arm64", "arch": "ARM64"},
            {"family": "ubuntu24.04-driverless", "arch": "AMD64"}])

    def list_subnets(self, pid):
        self.calls.append(("list_subnets", pid))
        region = next(p["region"] for p in self.projects if p["id"] == pid)
        return [] if region in self.no_subnet else [{"id": f"vpcsubnet-{pid[-4:]}", "name": "s"}]


def test_every_region_of_the_tenant_is_read():
    api = FakeApi()
    inv = ci.inventory(api, "project-e04x")
    assert [r["region"] for r in inv["regions"]] == ["eu-north1", "eu-west2", "us-central1"]
    north = inv["regions"][0]
    assert [p["name"] for p in north["gpu_platforms"]] == ["gpu-h100-sxm", "gpu-l40s-a", "gpu-gb300"]
    assert north["cpu_platforms"] == ["cpu-d3"]
    assert "ubuntu24.04-driverless (AMD64)" not in north["cuda_images"]
    assert inv["errors"] == []


def test_one_failing_region_is_reported_not_fatal():
    inv = ci.inventory(FakeApi(broken_region="project-u00x"), "project-e04x")
    assert len(inv["regions"]) == 3
    assert any("platforms us-central1" in e and "PermissionError" in e for e in inv["errors"])


def test_auth_failure_on_the_configured_project_is_loud():
    class Denied(FakeApi):
        def get_project(self, pid):
            raise PermissionError("unauthenticated")
    with pytest.raises(PermissionError):
        ci.inventory(Denied(), "project-e04x")


def test_recommend_takes_the_cheapest_bootable_target():
    rec = ci.recommend(ci.inventory(FakeApi(), "project-e04x"))
    assert rec == {"region": "eu-north1", "project_id": "project-e00x",
                   "platform": "gpu-l40s-a", "preset": "1gpu-8vcpu-32gb",
                   "subnet_id": "vpcsubnet-e00x", "image_family": "ubuntu24.04-cuda13.0"}


def test_recommend_skips_a_region_it_could_not_boot_in():
    inv = ci.inventory(FakeApi(no_subnet={"eu-north1"}), "project-e04x")
    rec = ci.recommend(inv)
    assert rec["region"] == "us-central1" and rec["platform"] == "gpu-h200-sxm"


def test_recommend_none_when_nothing_preferred_is_bootable():
    inv = ci.inventory(FakeApi(no_subnet={"eu-north1", "us-central1"}), "project-e04x")
    assert ci.recommend(inv) is None


@pytest.mark.parametrize("images,want", [
    (["ubuntu22.04-cuda12 (AMD64)", "ubuntu24.04-cuda13.0 (AMD64)"], "ubuntu24.04-cuda13.0"),
    (["ubuntu24.04-cuda13-latest (AMD64)", "ubuntu24.04-cuda13.0-serverless (AMD64)"], None),
    (["ubuntu24.04-cuda13.0-arm64 (ARM64)"], None),
    (["ubuntu26.04-cuda14.1 (AMD64)"], "ubuntu26.04-cuda14.1"),
])
def test_image_choice_is_pinned_amd64_and_documented(images, want):
    assert ci.pick_image(images) == want


def test_format_and_save(tmp_path):
    inv = ci.inventory(FakeApi(), "project-e04x")
    rec = ci.recommend(inv)
    text = ci.format_inventory(inv, rec)
    assert "gpu-l40s-a / 1gpu-8vcpu-32gb in eu-north1" in text
    assert "Listed is not reserved" in text
    saved = json.loads(ci.save(inv, rec, tmp_path).read_text(encoding="utf-8"))
    assert saved["phase2_target"]["platform"] == "gpu-l40s-a"


def test_inventory_module_never_mutates_anything():
    """Phase 1 is read-only by construction, not by promise."""
    src = (ENGINE / "nge" / "fleet" / "compute_inventory.py").read_text(encoding="utf-8")
    called = {n.func.attr for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    forbidden = {"create", "update", "delete", "start", "stop", "patch", "set"}
    assert not called & forbidden, called & forbidden
    rpc = {a for a in called if a in {"get", "list", "list_public"}}
    assert rpc == {"get", "list", "list_public"}


def test_inventory_command_needs_phase0_first(monkeypatch, capsys):
    from nge.fleet import compute
    monkeypatch.setattr(compute, "check_credentials",
                        lambda: {"ready_for_wire": False, "sdk_installed": True,
                                 "sdk_version": "x", "auth": None, "project_id": False,
                                 "subnet_id": False, "spawn_allowed": False,
                                 "missing": ["auth"]})
    monkeypatch.setattr(ci, "build_sdk", lambda *a: pytest.fail("no SDK before Phase 0"))
    assert compute._main(["inventory"]) == 1
    assert "ready_for_wire=False" in capsys.readouterr().out
