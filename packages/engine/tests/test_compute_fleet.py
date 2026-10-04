"""Compute Phase 3 fleet: real-VM GpuFleet, exercised with a fake Nebius API
and fake SSH - no VM, no network."""
import pytest

from nge import config as _cfg
from nge.fleet import compute_probe as cp
from nge.fleet.compute_fleet import ComputeGpuFleet

TARGET = {"region": "eu-north1", "project_id": "project-e00x", "platform": "gpu-l40s-a",
          "preset": "1gpu-8vcpu-32gb", "subnet_id": "vpcsubnet-x",
          "image_family": "ubuntu24.04-cuda13.0"}
IDLE = "nvidia-smi,0, 1, 46068, 27, 67.8, NVIDIA L40S\n"
HOT = "nvidia-smi,99, 40000, 46068, 91, 340.0, NVIDIA L40S\n"


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class FakeApi:
    def __init__(self, leftovers=(), fail_create_at=None, delete_fails=()):
        self.created, self.deleted, self.user_data = [], [], []
        self.leftovers = list(leftovers)
        self.fail_create_at = fail_create_at
        self.delete_fails = set(delete_fails)
        self.polls = {}

    def list_labeled(self, project_id):
        return self.leftovers

    def create(self, target, name, user_data, timeout):
        if self.fail_create_at is not None and len(self.created) == self.fail_create_at:
            raise RuntimeError("NOT_ENOUGH_RESOURCES")
        iid = f"computeinstance-{len(self.created)}"
        self.created.append(iid)
        self.user_data.append(user_data)
        return iid, object()

    def wait_op(self, op, timeout):
        pass

    def get(self, iid, timeout=30):
        n = self.polls[iid] = self.polls.get(iid, 0) + 1
        running = n >= 2
        return {"state": "RUNNING" if running else "STARTING",
                "public_ip": f"203.0.113.{iid[-1]}" if running else None}

    def delete(self, iid, timeout):
        if iid in self.delete_fails:
            raise ConnectionError("unavailable")
        self.deleted.append(iid)


def _ssh(readings):
    """readings: ip -> list of outputs (last one repeats); '' means not up yet."""
    def ssh(ip, key, script, timeout):
        seq = readings.setdefault(ip, [IDLE])
        out = seq.pop(0) if len(seq) > 1 else seq[0]
        return (0, out, "") if out else (255, "", "Connection refused")
    return ssh


def _fleet(api=None, ssh=None, clock=None, **kw):
    clock = clock or Clock()
    return ComputeGpuFleet(_cfg.load(fleet_mode="compute"), api=api or FakeApi(),
                           target=TARGET, ssh=ssh or _ssh({}), ssh_key="key",
                           public_key="ssh-ed25519 AAAA t", clock=clock, sleep=clock.sleep,
                           log=lambda *_: None, **kw)


@pytest.fixture(autouse=True)
def spawn_allowed(monkeypatch):
    monkeypatch.setenv("NGE_COMPUTE_SPAWN", "1")


def test_nothing_is_created_without_the_explicit_opt_in(monkeypatch):
    monkeypatch.delenv("NGE_COMPUTE_SPAWN")
    api = FakeApi()
    with pytest.raises(RuntimeError, match="NGE_COMPUTE_SPAWN"):
        _fleet(api).provision(2)
    assert api.created == []


def test_a_leftover_from_an_earlier_run_blocks_provisioning():
    api = FakeApi(leftovers=[{"id": "x", "name": "nge-probe-old", "state": "RUNNING"}])
    with pytest.raises(RuntimeError, match="cleanup"):
        _fleet(api).provision(2)
    assert api.created == []


def test_provision_brings_up_ready_labelled_self_powering_off_nodes():
    api = FakeApi()
    nodes = _fleet(api, max_minutes=12).provision(2)
    assert [n.id for n in nodes] == ["cg-l40s-a-00", "cg-l40s-a-01"]
    assert all(n.state == "ready" and n.gpu_type == "gpu-l40s-a" for n in nodes)
    assert all(f"[shutdown, -h, '+{12 + cp.POWEROFF_GRACE_MINUTES}']" in u
               for u in api.user_data)


def test_status_is_real_telemetry_with_health_from_the_gpu_class():
    # one reading is used by provision (SSH ready check), the next by status()
    f = _fleet(ssh=_ssh({"203.0.113.0": [IDLE], "203.0.113.1": [IDLE, HOT]}))
    f.provision(2)
    rows = {r.id: r for r in f.status()}
    idle, hot = rows["cg-l40s-a-00"], rows["cg-l40s-a-01"]
    assert idle.probe_kind == "nvidia-smi" and idle.gpu_class == "datacenter"
    assert idle.health == "ok" and idle.efficiency == 0.0 and idle.temp_c == 27.0
    assert hot.health == "throttle" and hot.temp_c == 91.0


def test_a_failed_probe_is_reported_not_invented():
    def ssh(ip, key, script, timeout):
        ssh.n = getattr(ssh, "n", 0) + 1
        return (0, IDLE, "") if ssh.n == 1 else (255, "", "Connection reset")
    f = _fleet(ssh=ssh)
    f.provision(1)
    (row,) = f.status()
    assert row.probe_kind == "failed" and row.health == "unknown"


def test_allocate_then_release_deletes_every_vm():
    api = FakeApi()
    f = _fleet(api)
    f.provision(2)
    assert f.allocate("shard-0").id == "cg-l40s-a-00"
    assert sorted(f.release()) == ["cg-l40s-a-00", "cg-l40s-a-01"]
    assert sorted(api.deleted) == ["computeinstance-0", "computeinstance-1"]
    assert f.status() == []


def test_release_never_raises_and_names_what_it_left():
    api = FakeApi(delete_fails={"computeinstance-1"})
    f = _fleet(api)
    f.provision(2)
    f.release()
    assert api.deleted == ["computeinstance-0"]
    assert f.undeleted == ["computeinstance-1"]


def test_a_provision_that_fails_half_way_deletes_what_it_made():
    api = FakeApi(fail_create_at=1)
    with pytest.raises(RuntimeError, match="NOT_ENOUGH_RESOURCES"):
        _fleet(api).provision(2)
    assert api.created == ["computeinstance-0"] and api.deleted == ["computeinstance-0"]


def test_a_node_that_never_answers_ssh_times_out_and_is_deleted():
    api = FakeApi()
    clock = Clock()
    f = _fleet(api, ssh=_ssh({"203.0.113.0": [""]}), clock=clock, max_minutes=3)
    with pytest.raises(TimeoutError):
        f.provision(1)
    assert api.deleted == ["computeinstance-0"]
    assert clock.t <= 3 * 60 + 60


# -- the orchestrator on a real-telemetry fleet ------------------------------------

def test_orchestrator_reads_real_gpu_telemetry_and_migrates_nothing_by_mistake(
        tmp_path, monkeypatch):
    """The Phase 3 claim, without a VM: real-shaped nvidia-smi readings reach the
    heal decision, the idle GPU is not called inefficient, every VM is deleted."""
    from nge.orchestrator import NgeOrchestrator
    from nge.tools import handlers
    api = FakeApi()
    fleet = _fleet(api)
    monkeypatch.setattr(handlers, "build_fleet", lambda mode, cfg: fleet)
    o = NgeOrchestrator(config=_cfg.load(fleet_mode="compute", sandbox_mode="mock",
                                         out_dir=tmp_path))
    rep = o.run({"task": "run tests", "shards": 2, "target": "packages/nodus/tests",
                 "auto_fix": False})
    kinds = [e["kind"] for e in o.events]
    tele = [e["telemetry"] for e in o.events if e["kind"] == "gpu_status" and e.get("telemetry")]
    assert tele and all(t["probe_kind"] == "nvidia-smi" for t in tele)
    assert "gpu_efficiency_skipped" in kinds
    assert "gpu_remediation" not in kinds and not rep.remediations
    assert sorted(api.deleted) == sorted(api.created) == ["computeinstance-0", "computeinstance-1"]


# -- the hybrid command refuses before anything is built ------------------------------

@pytest.mark.parametrize("argv,env", [
    (["hybrid"], "1"),                                              # no --i-know-cost
    (["hybrid", "--i-know-cost"], None),                            # no NGE_COMPUTE_SPAWN
    (["hybrid", "--i-know-cost", "--shards", "4"], "1"),            # > 3 paid VMs
    (["hybrid", "--i-know-cost", "--max-minutes", "45"], "1"),
])
def test_hybrid_needs_both_opt_ins_and_a_small_fleet(tmp_path, monkeypatch, argv, env):
    pytest.importorskip("nebius")
    from nge.fleet import compute
    import nge.orchestrator as orch_mod
    monkeypatch.setattr(compute, "_engine_dir", lambda: tmp_path)
    compute.generate_keypair(tmp_path, name="phase2")
    compute.write_credentials("serviceaccount-e00x", "publickey-e00x", tmp_path, name="phase2")
    monkeypatch.setattr(orch_mod, "NgeOrchestrator",
                        lambda *a, **k: pytest.fail("orchestrator built"))
    if env is None:
        monkeypatch.delenv("NGE_COMPUTE_SPAWN", raising=False)
    else:
        monkeypatch.setenv("NGE_COMPUTE_SPAWN", env)
    assert compute._main(argv) == 2
