"""Which ContreeSDK errors the Token Factory sandbox retries - no network."""
from nge.sandbox.token_factory import _transient_contree


class ApiStatusCodeError(Exception):
    """Same name and message shape as contree_sdk's."""


def test_a_500_from_the_files_endpoint_is_retried():
    # the scheduled CI live run of 2026-10-20 (#107) died on exactly this
    exc = ApiStatusCodeError(
        "ApiStatusCodeError(request=RequestInfo(url='https://api.tokenfactory.nebius.com/"
        "sandboxes/v1/files/87838f9d', method='GET'), response=ResponseInfo(headers={}), "
        "status=500, error='Internal Server Error')")
    assert _transient_contree(exc)


def test_gateway_and_rate_limit_statuses_are_retried():
    for code in ("429", "502", "503", "504"):
        assert _transient_contree(RuntimeError(f"status={code}"))
    assert _transient_contree(TimeoutError("read timed out"))


def test_a_client_error_or_a_number_containing_500_is_not():
    assert not _transient_contree(RuntimeError("status=404, error='Not Found'"))
    assert not _transient_contree(RuntimeError("status=401, error='Unauthorized'"))
    assert not _transient_contree(RuntimeError("file is 15000 bytes, limit 4096"))
    assert not _transient_contree(ValueError("Either command or shell must be given"))


# -- a retry starts from a fresh session ----------------------------------------

class _Done:
    exit_code, stdout, stderr, elapsed = 0, "1 passed", "", None


class _Session:
    def __init__(self, log, fail):
        self.log, self.fail, self.broken = log, fail, False

    def run(self, **kw):
        self.log.append(("run", id(self), kw["files"]))
        if self.broken:
            raise RuntimeError('Image state "None" cannot have state EXECUTING')
        if self.fail:
            self.broken = True              # what a half-done run leaves behind
            raise ApiStatusCodeError("status=500, error='Internal Server Error'")
        return self

    def wait(self):
        return _Done()


class _Image:
    def __init__(self, log):
        self.log, self.made = log, 0

    def session(self):
        self.made += 1
        return _Session(self.log, fail=self.made == 1)


def test_a_retried_run_uses_a_new_session_and_the_same_files(monkeypatch):
    from types import SimpleNamespace
    from nge.sandbox.token_factory import TokenFactorySandbox
    monkeypatch.setenv("NGE_CONTREE_RETRY_S", "0")
    log = []
    sbx = TokenFactorySandbox(SimpleNamespace(token_factory_base_url="x"))
    img = _Image(log)
    sbx._images["s"], sbx._sessions["s"] = img, img.session()
    sbx.put_files("s", {"a.py": "x = 1\n"})
    res = sbx.exec("s", "pytest -q")
    assert res.exit_code == 0 and sbx.last_retries == 1
    (first, second) = log
    assert first[1] != second[1], "the retry must not reuse the broken session"
    assert first[2] == second[2] == {"a.py": b"x = 1\n"}, "the files go with the retry"
