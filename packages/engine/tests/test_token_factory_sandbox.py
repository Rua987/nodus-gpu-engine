"""TokenFactorySandbox drives the ConTree SDK surface correctly (fake SDK).

Covers _build_client guards + create / put_files / exec / collect / destroy
against a fake shaped like contree-sdk's ContreeSync.
"""
from datetime import timedelta

import pytest

from nge.sandbox import token_factory as tf
from nge.sandbox.base import SandboxSpec


class _Session:
    """Mimics a ConTree image/session: run(shell="<line>", files=...).wait().

    The fake used to take ``args=["/bin/sh", "-c", cmd]``, which is not the
    SDK's contract - the real call raises "Either command or shell must be
    provided". The test passed against an API that does not exist, so it could
    never have caught the bug the first live sandbox run found immediately.
    ``elapsed`` is a timedelta there too, not a float.
    """
    def __init__(self):
        self.fs = {}
        self.calls = []
        self.exit_code = 0
        self.stdout = ""
        self.stderr = ""
        self.elapsed = timedelta(seconds=0.7)   # SDK returns a timedelta
        self.closed = False

    def run(self, shell=None, command=None, args=None, files=None,
            timeout=None, **kw):
        if shell is None and command is None:
            raise ValueError("Either command or shell must be provided")
        cmd = shell if shell is not None else command
        self.calls.append({"shell": cmd, "files": dict(files or {}),
                           "timeout": timeout,
                           "truncate_output_at": kw.get("truncate_output_at")})
        if files:
            self.fs.update(files)
        if "pytest" in cmd:
            self.exit_code, self.stdout = 1, "FAILED tests/x.py::t - boom\n1 failed"
        else:
            self.exit_code, self.stdout = 0, "ok"
        return self

    def wait(self):
        return self

    def read(self, path):
        if path in self.fs:
            v = self.fs[path]
            return v if isinstance(v, bytes) else v.encode()
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
    assert sess.calls[-1]["shell"] == "git apply fix.patch && python -m pytest -q"
    # bytes, not str: the SDK reads a str value as a *local path*, which is what
    # made the first live run try to open a file named after the whole diff
    assert sess.calls[-1]["files"] == {"fix.patch": b"--- a/x\n+++ b/x\n"}
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


def test_exec_retries_transient_timeout(sbx, monkeypatch):
    monkeypatch.setenv("NGE_CONTREE_RETRIES", "3")
    monkeypatch.setenv("NGE_CONTREE_RETRY_S", "0")
    sid = sbx.create(SandboxSpec(image="python:3.12-slim"))
    sess = sbx._sessions[sid]
    n = {"i": 0}

    def flaky(*, shell=None, command=None, args=None, files=None, timeout=None, **kw):
        n["i"] += 1
        if n["i"] < 3:
            raise TimeoutError("ApiTimeoutError read")
        return _Session.run(sess, shell=shell, files=files, timeout=timeout)

    sess.run = flaky
    sbx.put_files(sid, {"a.py": "x=1\n"})
    res = sbx.exec(sid, "echo ok", timeout=30)
    assert res.exit_code == 0
    assert sbx.last_retries == 2
    assert n["i"] == 3


def test_exec_asks_for_more_than_the_sdk_default_and_reports_a_cut(sbx, monkeypatch):
    """ContreeSDK cuts stdout at 64 KiB by default; a `-v` shard outgrew it live
    and its last FAILED line was cut mid-name. Ask for more, and say when even
    that was not enough."""
    sid = sbx.create(SandboxSpec(image="python:3.12-slim"))
    sess = sbx._sessions[sid]
    res = sbx.exec(sid, "python -m pytest -v", timeout=30)
    assert sess.calls[-1]["truncate_output_at"] == tf.DEFAULT_OUTPUT_BYTES > 65535
    assert res.truncated is False                     # fake has no result flag

    class _Result:
        truncated = True
    sess.result = _Result()
    monkeypatch.setenv("NGE_CONTREE_OUTPUT_BYTES", "100")   # floor: the SDK default
    res = sbx.exec(sid, "python -m pytest -v", timeout=30)
    assert sess.calls[-1]["truncate_output_at"] == 65535
    assert res.truncated is True
