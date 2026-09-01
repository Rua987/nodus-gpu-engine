"""TokenFactorySandbox drives the ConTree surface correctly (fake SDK).

Covers create / put_files / exec / collect / destroy. Only ``_build_client``
(auth wiring) is unimplemented for real; here it's replaced by a fake.
"""
import pytest

from nge.sandbox import token_factory as tf
from nge.sandbox.base import SandboxSpec


class _Result:
    def __init__(self, stdout="", stderr="", exit_code=0):
        self.stdout, self.stderr, self.exit_code = stdout, stderr, exit_code

    def wait(self):
        return self


class _Image:
    def __init__(self):
        self.calls = []
        self.files = {}
        self.destroyed = False

    def run(self, shell, stdin=None, timeout=None):
        self.calls.append({"shell": shell, "stdin": stdin, "timeout": timeout})
        if "cat > " in shell and stdin is not None:
            path = shell.split("cat > ", 1)[1].strip().strip('"')
            self.files[path] = stdin
            return _Result(exit_code=0)
        if shell.startswith("cat "):
            path = shell[4:].strip().strip("'\"")
            if path in self.files:
                return _Result(stdout=self.files[path], exit_code=0)
            return _Result(stderr="No such file", exit_code=1)
        if "pytest" in shell:
            return _Result(stdout="FAILED tests/x.py::t - boom\n1 failed", exit_code=1)
        return _Result(stdout="ok", exit_code=0)

    def destroy(self):
        self.destroyed = True


class _SDK:
    def __init__(self):
        self.images = self
        self.last = None

    def use(self, image):
        self.last = _Image()
        return self.last


@pytest.fixture
def sbx(monkeypatch):
    monkeypatch.setattr(tf, "_import_contree", lambda: (object, None))
    monkeypatch.setattr(tf.TokenFactorySandbox, "_build_client", lambda self: _SDK())
    from nge import config as _cfg
    s = tf.TokenFactorySandbox(_cfg.load(sandbox_mode="token_factory"))
    return s


def test_full_flow(sbx):
    sid = sbx.create(SandboxSpec(image="python:3.11-slim", node_id="nb-h100-00"))
    assert sid.endswith("@nb-h100-00")

    sbx.put_files(sid, {"work/run.sh": "echo hi"})
    img = sbx._images[sid]
    assert img.files["work/run.sh"] == "echo hi"

    res = sbx.exec(sid, "python -m pytest -q", timeout=60)
    assert res.exit_code == 1 and "FAILED" in res.stdout
    assert img.calls[-1]["timeout"] == 60

    got = sbx.collect(sid, ["work/run.sh", "nope.txt"])
    assert got["work/run.sh"] == "echo hi"
    assert got["nope.txt"].startswith("[missing:")

    sbx.destroy(sid)
    assert img.destroyed and sid not in sbx._images


def test_build_client_is_the_only_gap(monkeypatch):
    from nge import config as _cfg
    monkeypatch.setenv("TOKEN_FACTORY_API_KEY", "tf-key")
    s = tf.TokenFactorySandbox(_cfg.load())
    with pytest.raises(NotImplementedError, match="_build_client"):
        s._build_client()


def test_build_client_requires_key(monkeypatch):
    from nge import config as _cfg
    monkeypatch.delenv("TOKEN_FACTORY_API_KEY", raising=False)
    s = tf.TokenFactorySandbox(_cfg.load())
    with pytest.raises(RuntimeError, match="Token Factory not configured"):
        s._build_client()
