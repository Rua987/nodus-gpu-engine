"""NebiusFleet: ConTree-backed pool + telemetry probe parsing (fake client)."""
import pytest

from nge.fleet import nebius as nf
from nge.fleet.nebius import NebiusFleet, _parse_probe


def test_parse_probe_gpu_line():
    m = _parse_probe("12, 40960, 81920, 63, 410.5\n")
    assert m["util_pct"] == 12.0
    assert m["mem_used_gb"] == 40.0 and m["mem_total_gb"] == 80.0
    assert m["temp_c"] == 63.0 and m["power_w"] == 410.5
    assert m["probe_kind"] == "nvidia-smi"


def test_parse_probe_cpu_line():
    m = _parse_probe("35, 512, 3928, 0, 0")
    assert m["util_pct"] == 35.0 and m["temp_c"] == 0.0 and m["power_w"] == 0.0
    assert m["probe_kind"] == "cpu-fallback"


def test_parse_probe_garbage():
    assert _parse_probe("") is None
    assert _parse_probe("not,enough") is None
    assert _parse_probe("a, b, c, d, e") is None


class _Res:
    def __init__(self, out, code=0):
        self.stdout, self.exit_code = out, code

    def wait(self):
        return self


class _Session:
    def __init__(self, probe_out):
        self.probe_out = probe_out
        self.closed = False
        self.last_run = None

    def run(self, shell=None, command=None, args=None, files=None, timeout=None, **kw):
        self.last_run = {"shell": shell, "command": command, "args": args}
        return _Res(self.probe_out)

    def close(self):
        self.closed = True


class _Image:
    def __init__(self, probe_out):
        self._s = _Session(probe_out)

    def session(self):
        return self._s


class _Client:
    def __init__(self, probe_out="55, 40960, 81920, 70, 500"):
        self.probe_out = probe_out
        self.images = self

    def use(self, ref, **kw):
        return _Image(self.probe_out)


@pytest.fixture
def fleet(monkeypatch):
    client = _Client()
    monkeypatch.setattr(NebiusFleet, "_client_ready", lambda self: client)
    from nge import config as _cfg
    return NebiusFleet(_cfg.load(fleet_mode="nebius"))


def test_provision_allocate_release(fleet):
    nodes = fleet.provision(3, gpu_type="H100")
    assert [n.id for n in nodes] == ["nb-h100-00", "nb-h100-01", "nb-h100-02"]

    a = fleet.allocate("shard-0")
    assert a.state == "allocated" and a.job == "shard-0"

    released = fleet.release()
    assert set(released) == {"nb-h100-00", "nb-h100-01", "nb-h100-02"}
    assert fleet._nodes == {}


def test_status_parses_real_probe(fleet):
    fleet.provision(2)
    rows = fleet.status()
    assert len(rows) == 2
    r = rows[0]
    assert r.util_pct == 55.0
    assert r.mem_used_gb == 40.0 and r.mem_total_gb == 80.0
    assert r.temp_c == 70.0 and r.power_w == 500.0
    assert r.health in ("ok", "warm", "throttle")
    assert 0.0 <= r.efficiency <= 1.0
    assert r.probe_kind == "nvidia-smi"
    # Contree contract: probe must use shell=, not args=/bin/sh -c
    sess = fleet._nodes["nb-h100-00"]["session"]
    assert sess.last_run["shell"]
    assert not sess.last_run.get("args")


def test_status_cpu_fallback_tagged(monkeypatch):
    from nge import config as _cfg
    client = _Client(probe_out="cpu-fallback,35,512,3928,0,0,\n")
    monkeypatch.setattr(NebiusFleet, "_client_ready", lambda self: client)
    f = NebiusFleet(_cfg.load(fleet_mode="nebius"))
    f.provision(1)
    rows = f.status()
    assert rows[0].probe_kind == "cpu-fallback"
    assert rows[0].gpu_class == "none"
    assert rows[0].temp_c == 0.0


def test_status_handles_probe_failure(monkeypatch):
    class _BadSession:
        def run(self, **kw):
            raise RuntimeError("sandbox died")
    class _BadClient:
        images = property(lambda self: self)
        def use(self, *a, **k):
            class I:
                def session(self_inner):
                    return _BadSession()
            return I()

    monkeypatch.setattr(NebiusFleet, "_client_ready", lambda self: _BadClient())
    from nge import config as _cfg
    f = NebiusFleet(_cfg.load())
    f.provision(1)
    rows = f.status()
    assert rows[0].health == "unknown" and rows[0].util_pct == 0.0
    assert rows[0].probe_kind == "failed"


def test_release_closes_sessions(fleet):
    fleet.provision(1)
    fleet.status()                       # forces session creation
    sess = fleet._nodes["nb-h100-00"]["session"]
    fleet.release(["nb-h100-00"])
    assert sess.closed is True
