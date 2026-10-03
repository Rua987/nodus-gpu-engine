"""Compute Phase 2: whatever happens, the paid VM is deleted - and when it is
not, the report says so. Fake API, fake clock, fake SSH: no VM, no network."""
import pytest

from nge.fleet import compute_probe as cp

TARGET = {"region": "eu-north1", "project_id": "project-e00x", "platform": "gpu-l40s-a",
          "preset": "1gpu-8vcpu-32gb", "subnet_id": "vpcsubnet-x",
          "image_family": "ubuntu24.04-cuda13.0"}
NVIDIA = "nvidia-smi,37, 512, 46068, 41, 72.5, NVIDIA L40S\n"
CPU = "cpu-fallback,3,800,32000,0,0,\n"


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class FakeApi:
    def __init__(self, clock, op_fails=False, states=("CREATING", "RUNNING"),
                 delete_fails=0, interrupt_on_get=False):
        self.clock, self.op_fails = clock, op_fails
        self.states = list(states)
        self.delete_fails = delete_fails
        self.interrupt_on_get = interrupt_on_get
        self.deleted, self.created = [], []

    def create(self, target, name, user_data, timeout):
        self.created.append((name, user_data))
        return "computeinstance-x", object()

    def wait_op(self, op, timeout):
        if self.op_fails:
            raise RuntimeError("operation failed: quota")

    def get(self, iid, timeout=30):
        if self.interrupt_on_get:
            raise KeyboardInterrupt
        state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return {"state": state, "public_ip": "203.0.113.7" if state == "RUNNING" else None}

    def delete(self, iid, timeout):
        if self.delete_fails:
            self.delete_fails -= 1
            raise ConnectionError("unavailable")
        self.deleted.append(iid)

    def list_labeled(self, project_id):
        return [{"id": "computeinstance-old", "name": "nge-probe-old", "state": "RUNNING"}]


def _ssh(output, rc=0):
    calls = []

    def ssh(ip, key, script, timeout):
        calls.append(ip)
        return rc, output, "" if rc == 0 else "Connection refused"
    ssh.calls = calls
    return ssh


def _run(api, clock, ssh, **kw):
    return cp.probe(api, TARGET, "key", "ssh-ed25519 AAAA test", clock=clock,
                    sleep=clock.sleep, ssh=ssh, log=lambda *_: None, **kw)


def test_a_real_gpu_reading_and_the_vm_is_deleted():
    clock = Clock()
    api = FakeApi(clock)
    r = _run(api, clock, _ssh(NVIDIA))
    assert r["ok"] is True and r["deleted"] is True
    assert r["metrics"]["probe_kind"] == "nvidia-smi"
    assert r["metrics"]["gpu_name"] == "NVIDIA L40S" and r["metrics"]["temp_c"] == 41.0
    assert api.deleted == ["computeinstance-x"]
    assert [e["kind"] for e in r["events"]] == ["create_sent", "created", "running",
                                                 "probed", "deleted"]


def test_a_cpu_reading_is_not_success():
    clock = Clock()
    r = _run(FakeApi(clock), clock, _ssh(CPU))
    assert r["ok"] is False and r["deleted"] is True
    assert r["metrics"]["probe_kind"] == "cpu-fallback"


def test_a_failed_create_still_deletes_what_it_got_an_id_for():
    clock = Clock()
    api = FakeApi(clock, op_fails=True)
    r = _run(api, clock, _ssh(NVIDIA))
    assert "quota" in r["error"] and api.deleted == ["computeinstance-x"]


def test_ssh_that_never_answers_stops_at_the_deadline_and_deletes():
    clock = Clock()
    api = FakeApi(clock)
    ssh = _ssh("", rc=255)
    r = _run(api, clock, ssh, max_minutes=5)
    assert "TimeoutError" in r["error"] and r["deleted"] is True
    assert clock.t <= 5 * 60 + 60, "deadline overrun"
    assert len(ssh.calls) > 1


def test_a_vm_that_never_runs_stops_at_the_deadline_and_deletes():
    clock = Clock()
    api = FakeApi(clock, states=("STARTING",))
    r = _run(api, clock, _ssh(NVIDIA), max_minutes=2)
    assert "not running before the deadline" in r["error"] and r["deleted"] is True


def test_ctrl_c_deletes_then_reraises():
    clock = Clock()
    api = FakeApi(clock, interrupt_on_get=True)
    with pytest.raises(KeyboardInterrupt):
        _run(api, clock, _ssh(NVIDIA))
    assert api.deleted == ["computeinstance-x"]


def test_delete_is_retried():
    clock = Clock()
    api = FakeApi(clock, delete_fails=2)
    r = _run(api, clock, _ssh(NVIDIA))
    assert r["deleted"] is True
    assert [e["kind"] for e in r["events"]].count("delete_failed") == 2


def test_an_unconfirmed_delete_is_reported_not_hidden():
    clock = Clock()
    r = _run(FakeApi(clock, delete_fails=5), clock, _ssh(NVIDIA))
    assert r["deleted"] is False and r["instance_id"] == "computeinstance-x"


def test_max_minutes_cannot_exceed_the_cap():
    clock = Clock()
    r = _run(FakeApi(clock), clock, _ssh(NVIDIA), max_minutes=600)
    assert r["max_minutes"] == cp.MAX_MINUTES


def test_cloud_init_adds_a_key_only_non_reserved_user():
    ci = cp.cloud_init("ssh-ed25519 AAAA test")
    assert ci.startswith("#cloud-config\n")
    assert "name: nge" in ci and "ssh-ed25519 AAAA test" in ci
    assert "root" not in ci and "admin" not in ci and "passwd" not in ci


def test_cleanup_deletes_the_labelled_leftovers():
    clock = Clock()
    api = FakeApi(clock)
    assert cp.cleanup(api, "project-e00x", log=lambda *_: None) == ["computeinstance-old"]
    assert api.deleted == ["computeinstance-old"]


def test_ssh_key_is_created_once(tmp_path):
    pytest.importorskip("cryptography")
    priv, pub = cp.ensure_ssh_key(tmp_path)
    assert pub.startswith("ssh-ed25519 ") and "PRIVATE" not in pub
    again = cp.ensure_ssh_key(tmp_path)
    assert again == (priv, pub)


def test_cost_estimate_is_known_or_none():
    assert cp.estimate_usd(TARGET, 30) == 0.77
    assert cp.estimate_usd({**TARGET, "platform": "gpu-b300-sxm"}, 30) is None


# -- the CLI refuses before any SDK is built --------------------------------------

@pytest.fixture
def phase2_creds(tmp_path, monkeypatch):
    pytest.importorskip("nebius")
    from nge.fleet import compute
    monkeypatch.setattr(compute, "_engine_dir", lambda: tmp_path)
    compute.generate_keypair(tmp_path, name="phase2")
    compute.write_credentials("serviceaccount-e00x", "publickey-e00x", tmp_path, name="phase2")
    from nge.fleet import compute_inventory as ci
    monkeypatch.setattr(ci, "build_sdk", lambda *a, **k: pytest.fail("SDK built"))
    return compute


@pytest.mark.parametrize("argv,env", [
    (["probe"], "1"),                                        # no --i-know-cost
    (["probe", "--i-know-cost"], None),                      # no NGE_COMPUTE_SPAWN
    (["probe", "--i-know-cost", "--max-minutes", "45"], "1"),
    (["probe", "--i-know-cost", "--max-minutes", "0"], "1"),
])
def test_probe_needs_both_opt_ins_and_a_sane_duration(phase2_creds, monkeypatch, argv, env):
    if env is None:
        monkeypatch.delenv("NGE_COMPUTE_SPAWN", raising=False)
    else:
        monkeypatch.setenv("NGE_COMPUTE_SPAWN", env)
    assert phase2_creds._main(argv) == 2
