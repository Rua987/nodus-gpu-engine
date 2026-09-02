"""TokenFactorySandbox drives the ConTree SDK surface correctly (fake SDK).

Covers _build_client guards + create / put_files / exec / collect / destroy
against a fake shaped like contree-sdk's ContreeSync.
"""
import pytest

from nge.sandbox import token_factory as tf
from nge.sandbox.base import SandboxSpec


class _Session:
    """Mimics a ConTree image/session: run(args=[...], files=...).wait()."""
    def __init__(self):
        self.fs = {}
        self.calls = []
        self.exit_code = 0
        self.stdout = ""
        self.stderr = ""
        self.elapsed = 0.7
        self.closed = False

    def run(self, args=None, files=None, timeout=None, **kw):
        self.calls.append({"args": args, "files": dict(files or {}), "timeout": timeout})
        if files:
            self.fs.update(files)
        cmd = args[-1] if args else ""
        if "pytest" in cmd:
            self.exit_code, self.stdout = 1, "FAILED tests/x.py::t - boom\n1 failed"
        else:
            self.exit_code, self.stdout = 0, "ok"
        return self

    def wait(self):
        return self

    def read(self, path):
        if path in self.fs:
            return self.fs[path].encode()
        raise FileNotFoundError(path)

    def close(self):
        self.closed = True


class _Image:
    def __init__(self):
        self.sess = _Session()

    def session(self):
        return self.sess


class _SDK:
    def __init__(self):
        self.images = self
        self.last = None

    def use(self, ref, **kw):
        self.last = _Image()
        return self.last

    def docker(self, ref, **kw):
        self.last = _Image()
        return self.last

    def get_token_info(self):
        return {"project_id": "proj-abc", "expires_in": 3600}


@pytest.fixture
def sbx(monkeypatch):
    monkeypatch.setattr(tf.TokenFactorySandbox, "_build_client", lambda self: _SDK())
    from nge import config as _cfg
    return tf.TokenFactorySandbox(_cfg.load(sandbox_mode="token_factory"))


def test_full_flow(sbx):
    sid = sbx.create(SandboxSpec(image="python:3.11-slim", node_id="nb-h100-00"))
    assert sid.endswith("@nb-h100-00")

    sbx.put_files(sid, {"fix.patch": "--- a/x\n+++ b/x\n"})
    res = sbx.exec(sid, "git apply fix.patch && python -m pytest -q", timeout=90)
    assert res.exit_code == 1 and "FAILED" in res.stdout
    assert res.duration_s == 0.7                      # uses ConTree's elapsed

    sess = sbx._sessions[sid]
    assert sess.calls[-1]["args"] == ["/bin/sh", "-c",
                                      "git apply fix.patch && python -m pytest -q"]
    assert sess.calls[-1]["files"] == {"fix.patch": "--- a/x\n+++ b/x\n"}
    assert sess.calls[-1]["timeout"] == 90

    got = sbx.collect(sid, ["fix.patch", "nope.txt"])
    assert got["fix.patch"] == "--- a/x\n+++ b/x\n"
    assert got["nope.txt"].startswith("[missing:")

    sbx.destroy(sid)
    assert sess.closed and sid not in sbx._sessions


def test_build_client_requires_key(monkeypatch):
    from nge import config as _cfg
    monkeypatch.setattr("nge.config.load_api_key", lambda *a, **k: None)
    s = tf.TokenFactorySandbox(_cfg.load())
    with pytest.raises(RuntimeError, match="no API key"):
        s._build_client()


def test_build_client_requires_project_id(monkeypatch):
    from nge import config as _cfg
    monkeypatch.setattr("nge.config.load_api_key", lambda *a, **k: "sk-test")
    monkeypatch.setattr("nge.config.load_value", lambda *a, **k: "")
    s = tf.TokenFactorySandbox(_cfg.load())
    with pytest.raises(RuntimeError, match="no project id"):
        s._build_client()


def test_build_client_constructs_contree(monkeypatch):
    from nge import config as _cfg
    monkeypatch.setattr("nge.config.load_api_key", lambda *a, **k: "sk-test")
    monkeypatch.setattr("nge.config.load_value",
                        lambda b, e: "proj-abc" if "project" in b else "")

    seen = {}

    class _FakeIAM:
        def __init__(self, token=None, project_id=None, base_url=None):
            seen.update(token=token, project_id=project_id, base_url=base_url)

    class _FakeCfg:
        def __init__(self, auth=None):
            seen["auth"] = auth

    class _FakeClient:
        def __init__(self, config=None):
            seen["config"] = config

    monkeypatch.setattr("nge.nebius_client._import_contree",
                        lambda: (_FakeClient, _FakeCfg, _FakeIAM))
    s = tf.TokenFactorySandbox(_cfg.load())
    client = s._build_client()
    assert isinstance(client, _FakeClient)
    assert seen["token"] == "sk-test" and seen["project_id"] == "proj-abc"
    assert seen["base_url"].endswith("/sandboxes/")
