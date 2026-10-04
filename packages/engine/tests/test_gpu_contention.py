"""Contention run: shards that use the GPU, on the Compute VMs, with a declared
induced load on one node. Fake Nebius API and fake SSH - no VM, no network."""
import base64
import io
import json
import tarfile
from pathlib import Path

import pytest

from nge import config as _cfg
from nge.fleet import compute_probe as cp
from nge.fleet.compute_fleet import ComputeGpuFleet
from nge.sandbox.base import SandboxSpec
from nge.sandbox.compute import ComputeSandbox

from test_compute_fleet import TARGET, Clock, FakeApi

IDLE = "nvidia-smi,0, 1, 46068, 27, 67.8, NVIDIA L40S\n"
BUSY = "nvidia-smi,100, 600, 46068, 58, 290.0, NVIDIA L40S\n"
SCENARIO = Path(__file__).resolve().parents[1] / "scenarios" / "gpu_contention.json"


class FakeVMs:
    """SSH to fake VMs: answers by what the script does, records everything."""

    def __init__(self, ready_after=1):
        self.scripts, self.induced, self.ready_after, self.ready_checks = [], set(), ready_after, 0

    def __call__(self, ip, key, script, timeout):
        self.scripts.append((ip, script))
        if "nge_burn" in script:
            self.induced.add(ip)
            return 0, "100, 290.0\n", ""
        if "__NGE_APPS__" in script:                       # status()
            if ip in self.induced:
                return 0, BUSY + "__NGE_APPS__\n4242, /tmp/nge_load/nge_burn, 400 MiB\n", ""
            return 0, IDLE + "__NGE_APPS__\n", ""
        if cp.READY_MARKER in script:                      # readiness
            self.ready_checks += 1
            return (0, IDLE, "") if self.ready_checks > self.ready_after else (7, "", "")
        if "pytest" in script:
            return 0, "2 passed in 9.10s\n", ""
        return 0, "", ""


def _fleet(vms, api=None, **kw):
    clock = Clock()
    return ComputeGpuFleet(_cfg.load(fleet_mode="compute"), api=api or FakeApi(), target=TARGET,
                           ssh=vms, ssh_key="key", public_key="ssh-ed25519 AAAA t",
                           gpu_runtime=True, clock=clock, sleep=clock.sleep,
                           log=lambda *_: None, **kw)


@pytest.fixture(autouse=True)
def spawn_allowed(monkeypatch):
    monkeypatch.setenv("NGE_COMPUTE_SPAWN", "1")


# -- the VM side ---------------------------------------------------------------

def test_a_runtime_vm_installs_a_venv_and_is_ready_only_after_it():
    api, vms = FakeApi(), FakeVMs(ready_after=2)
    _fleet(vms, api).provision(1)
    assert "python3-venv" in api.user_data[0] and cp.READY_MARKER in api.user_data[0]
    assert "package_update: true" in api.user_data[0]
    assert vms.ready_checks == 3                     # waited through two "not yet"


def test_status_lists_who_is_on_the_gpu():
    vms = FakeVMs(ready_after=0)
    f = _fleet(vms)
    (node,) = f.provision(1)
    assert f.induce_load(node.id, 120)["ok"]
    (row,) = f.status()
    assert row.util_pct == 100.0 and "nge_burn" in row.gpu_processes


def test_induced_load_is_built_on_the_vm_and_detached():
    vms = FakeVMs(ready_after=0)
    f = _fleet(vms)
    (node,) = f.provision(1)
    res = f.induce_load(node.id, 240)
    script = next(s for _, s in vms.scripts if "nge_burn" in s)
    assert "nvcc -O2 -o nge_burn gpu_burn.cu" in script
    assert "setsid nohup ./nge_burn 240" in script and "__global__ void burn" in script
    assert res["seconds"] == 240 and "nvcc" in res["how"]


def test_run_on_a_node_without_a_vm_says_so():
    assert _fleet(FakeVMs()).run_on("cg-l40s-a-09", "true", 5)[0] == 1


# -- the sandbox ---------------------------------------------------------------

def _tar_in(script):
    b64 = script.split("<<'NGE_EOF'\n", 1)[1].split("NGE_EOF", 1)[0]
    with tarfile.open(fileobj=io.BytesIO(base64.b64decode(b64)), mode="r:gz") as tar:
        return {m.name: tar.extractfile(m).read().decode() for m in tar.getmembers()}


def test_compute_sandbox_ships_files_runs_with_venv_and_cuda_and_cleans_up():
    vms = FakeVMs(ready_after=0)
    f = _fleet(vms)
    (node,) = f.provision(1)
    sbx = ComputeSandbox(f)
    sid = sbx.create(SandboxSpec(node_id=node.id))
    d = f"{cp.VENV}"
    sbx.put_files(sid, {"pkg/a.py": "x = 1\n", "pkg/tests/test_a.py": "def test(): pass\n"})
    up = vms.scripts[-1][1]
    assert _tar_in(up) == {"pkg/a.py": "x = 1\n", "pkg/tests/test_a.py": "def test(): pass\n"}
    res = sbx.exec(sid, "pip install -q pytest && pytest pkg/tests -q", timeout=90)
    run = vms.scripts[-1][1]
    assert f"export PATH={d}/bin:/usr/local/cuda/bin:$PATH" in run
    assert "timeout 90 sh -c 'pip install -q pytest && pytest pkg/tests -q'" in run
    assert res.exit_code == 0 and "2 passed" in res.stdout
    sbx.destroy(sid)
    assert vms.scripts[-1][1].startswith("rm -rf /tmp/nge_sbx/")


def test_compute_sandbox_refuses_paths_that_leave_it():
    vms = FakeVMs(ready_after=0)
    f = _fleet(vms)
    (node,) = f.provision(1)
    sbx = ComputeSandbox(f)
    sid = sbx.create(SandboxSpec(node_id=node.id))
    with pytest.raises(ValueError, match="outside"):
        sbx.put_files(sid, {"../../etc/x": "no"})


def test_compute_sandbox_needs_the_compute_fleet():
    from nge.fleet.mock import MockFleet
    with pytest.raises(RuntimeError, match="compute fleet"):
        ComputeSandbox(MockFleet())


# -- the whole run ---------------------------------------------------------------

def test_contention_run_migrates_the_shard_off_the_loaded_node(tmp_path, monkeypatch):
    from nge.orchestrator import NgeOrchestrator
    from nge.tools import handlers
    api, vms = FakeApi(), FakeVMs(ready_after=0)
    fleet = _fleet(vms, api)
    monkeypatch.setattr(handlers, "build_fleet", lambda mode, cfg: fleet)
    o = NgeOrchestrator(config=_cfg.load(fleet_mode="compute", sandbox_mode="compute",
                                         out_dir=tmp_path))
    scenario = json.loads(SCENARIO.read_text(encoding="utf-8"))
    o.run(scenario)
    ev = o.events
    (load,) = [e for e in ev if e["kind"] == "gpu_load_induced"]
    assert load["node_id"] == "cg-l40s-a-00" and load["declared"] is True
    (p,) = [e for e in ev if e["kind"] == "gpu_pressure"]
    assert p["node_id"] == "cg-l40s-a-00" and p["health"] == "busy"
    assert "nge_burn" in p["gpu_processes"]
    (rem,) = [e for e in ev if e["kind"] == "gpu_remediation"]
    assert rem["from"] == "cg-l40s-a-00" and rem["to"] == "cg-l40s-a-02"
    assert rem["duration_before_s"] is not None and rem["duration_after_s"] is not None
    skipped = [e for e in ev if e["kind"] == "gpu_efficiency_skipped"]
    assert skipped and all("after the shard finished" in e["why"] for e in skipped)
    # shards ran on the VMs, not in a Token Factory sandbox, with the CUDA source
    assert any("pytest" in s and "/opt/nge/venv/bin" in s for _, s in vms.scripts)
    # the re-run on the replacement gets the shard's files too (it re-ran
    # nothing on the first live migration: exit 4, "file not found")
    assert any(ip == "203.0.113.2" and "files.tgz" in s for ip, s in vms.scripts)
    assert rem["exit_before"] == 0 and rem["exit_after"] == 0
    shipped = [_tar_in(s) for _, s in vms.scripts if "files.tgz" in s]
    assert shipped and all("packages/engine/bench/gpubench/matmul.cu" in f for f in shipped)
    assert all("packages/engine/bench/gpubench/gpubench.py" in f for f in shipped)
    art = next(e["path"] for e in ev if e["kind"] == "artifact")
    page = Path(art).with_suffix(".html").read_text(encoding="utf-8")
    assert "induced load (declared, not organic)" in page
    assert "busy &mdash; 100.0% utilisation after our shard ended" in page
    assert "same shard" in page and "s there" in page
    assert sorted(api.deleted) == sorted(api.created)


def test_a_fleet_that_cannot_run_gpu_jobs_says_the_load_was_not_induced(tmp_path):
    from nge.orchestrator import NgeOrchestrator
    o = NgeOrchestrator(config=_cfg.load(fleet_mode="mock", sandbox_mode="mock",
                                         out_dir=tmp_path))
    o.run({"task": "run tests", "shards": 2, "target": "packages/nodus/tests",
           "auto_fix": False, "induce_gpu_load": {"node_index": 0, "seconds": 60}})
    (e,) = [x for x in o.events if x["kind"] == "gpu_load_not_induced"]
    assert "cannot run a GPU job" in e["why"]
    assert not [x for x in o.events if x["kind"] == "gpu_load_induced"]


def test_a_failed_cloud_init_stops_the_wait_and_deletes_the_vm():
    """Without this the fleet would wait to the deadline - paid minutes for a
    VM whose venv will never appear."""
    class BrokenInit(FakeVMs):
        def __call__(self, ip, key, script, timeout):
            if cp.READY_MARKER in script:
                return 8, "status: error", ""
            return super().__call__(ip, key, script, timeout)
    api = FakeApi()
    with pytest.raises(RuntimeError, match="cloud-init failed"):
        _fleet(BrokenInit(), api).provision(2)
    assert sorted(api.deleted) == sorted(api.created) == ["computeinstance-0", "computeinstance-1"]


def test_contention_needs_both_opt_ins(tmp_path, monkeypatch):
    pytest.importorskip("nebius")
    from nge.fleet import compute
    import nge.orchestrator as orch_mod
    monkeypatch.setattr(compute, "_engine_dir", lambda: tmp_path)
    compute.generate_keypair(tmp_path, name="phase2")
    compute.write_credentials("serviceaccount-e00x", "publickey-e00x", tmp_path, name="phase2")
    monkeypatch.setattr(orch_mod, "NgeOrchestrator",
                        lambda *a, **k: pytest.fail("orchestrator built"))
    monkeypatch.delenv("NGE_COMPUTE_SPAWN", raising=False)
    assert compute._main(["contention", "--i-know-cost"]) == 2
    monkeypatch.setenv("NGE_COMPUTE_SPAWN", "1")
    assert compute._main(["contention"]) == 2
    assert compute._main(["contention", "--i-know-cost", "--max-minutes", "45"]) == 2


def test_the_status_script_really_lists_gpu_processes(tmp_path):
    """Run the composed status script in a real sh with a fake nvidia-smi: the
    probe exits once it has read the GPU, so the listing after it never ran on
    the first live contention run - every fake SSH missed that."""
    import os
    import shutil
    import subprocess
    sh = shutil.which("sh")
    if not sh:
        pytest.skip("no POSIX sh")
    fake = tmp_path / "nvidia-smi"
    fake.write_text("#!/bin/sh\n"
                    'case "$*" in\n'
                    "  *compute-apps*) echo '4242, /tmp/nge_load/nge_burn, 400 MiB' ;;\n"
                    "  *) echo '100, 600, 46068, 58, 290.0, NVIDIA L40S' ;;\n"
                    "esac\n", encoding="utf-8", newline="\n")
    fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}"}

    def real_sh(ip, key, script, timeout):
        r = subprocess.run([sh, "-s"], input=script.encode(), capture_output=True,
                           env=env, timeout=timeout)
        return r.returncode, r.stdout.decode(), r.stderr.decode()

    f = _fleet(real_sh)
    f.gpu_runtime = False                       # no cloud-init marker on this host
    (node,) = f.provision(1)
    (row,) = f.status()
    assert row.util_pct == 100.0 and row.gpu_name == "NVIDIA L40S"
    assert row.gpu_processes == "4242, /tmp/nge_load/nge_burn, 400 MiB"
