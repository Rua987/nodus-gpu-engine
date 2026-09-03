"""Assertions for a --live run.

Every bug the first live sandboxes exposed produced a run that exited 0 and
summarised as "0 failure(s)" - indistinguishable from a clean one. These
checks look for evidence of work instead of trusting the exit code.
"""
from nge import live_check as lc


def _rep(**kw):
    base = {
        "ok": True,
        "events": [{"kind": "run_start", "sandbox_mode": "token_factory"},
                   {"kind": "gpu_release", "released": ["n0"]}],
        "shards": [{"index": 0, "exit_code": 1,
                    "stdout": "3 failed, 345 passed in 1.10s"}],
        "failures": [], "fixes": [],
    }
    base.update(kw)
    return base


def test_a_real_run_passes():
    assert lc.verify(_rep()) == []


def test_exit_127_is_caught():
    """The sandbox had no pytest: every shard tested nothing and said so as
    '0 failure(s)', exactly like a shard where everything passed."""
    p = lc.verify(_rep(shards=[{"index": 0, "exit_code": 127, "stdout": ""}]))
    assert any("127" in x and "nothing was tested" in x for x in p)


def test_exit_126_and_4_are_caught():
    for code, word in ((126, "jail"), (4, "usage")):
        p = lc.verify(_rep(shards=[{"index": 0, "exit_code": code, "stdout": ""}]))
        assert any(word in x for x in p), code


def test_a_silent_fallback_to_mock_is_caught():
    """A --live run that quietly used the mock sandbox proves nothing."""
    p = lc.verify(_rep(events=[{"kind": "run_start", "sandbox_mode": "mock"},
                               {"kind": "gpu_release"}]))
    assert any("sandbox_mode was 'mock'" in x for x in p)


def test_output_without_pytest_evidence_is_caught():
    p = lc.verify(_rep(shards=[{"index": 0, "exit_code": 1,
                                "stdout": "some unrelated noise"}]))
    assert any("no shard produced pytest output" in x for x in p)


def test_evidence_can_be_waived():
    rep = _rep(shards=[{"index": 0, "exit_code": 1, "stdout": "noise"}])
    assert lc.verify(rep, require_tests_ran=False) == []


def test_a_leaked_fleet_is_caught():
    p = lc.verify(_rep(events=[{"kind": "run_start",
                                "sandbox_mode": "token_factory"}]))
    assert any("gpu_release" in x for x in p)


def test_run_error_and_not_ok_are_caught():
    p = lc.verify(_rep(ok=False))
    assert any("did not complete" in x for x in p)
    p = lc.verify(_rep(events=[{"kind": "run_start", "sandbox_mode": "token_factory"},
                               {"kind": "run_error", "error": "RuntimeError: x"},
                               {"kind": "gpu_release"}]))
    assert any("RuntimeError: x" in x for x in p)


def test_no_shards_is_caught():
    assert any("no shards" in x for x in lc.verify(_rep(shards=[])))


def test_summary_is_one_line():
    s = lc.summary(_rep(fixes=[{"verified": True}, {"verified": False}]))
    assert "shards=1" in s and "1/2 verified" in s and "\n" not in s


def test_cli_returns_nonzero_on_problems(tmp_path):
    import json
    good, bad = tmp_path / "g.json", tmp_path / "b.json"
    good.write_text(json.dumps(_rep()), encoding="utf-8")
    bad.write_text(json.dumps(_rep(ok=False)), encoding="utf-8")
    assert lc.main([str(good)]) == 0
    assert lc.main([str(bad)]) == 1
    assert lc.main([str(tmp_path / "missing.json")]) == 2
