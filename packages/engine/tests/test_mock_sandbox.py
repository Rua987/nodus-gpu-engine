"""MockSandbox: deterministic exec + lifecycle."""
from nge.sandbox.mock import MockSandbox
from nge.sandbox.base import SandboxSpec


def test_lifecycle_and_pytest_shape():
    s = MockSandbox()
    sid = s.create(SandboxSpec(node_id="nb-h100-00"))
    assert sid.endswith("@nb-h100-00")

    res = s.exec(sid, "python -m pytest packages/nodus/tests -q")
    assert res.exit_code == 1
    assert "test session starts" in res.stdout
    assert "FAILED " in res.stdout

    s.destroy(sid)
    assert sid not in s._fs


def test_exec_is_deterministic_per_sandbox_and_command():
    s1 = MockSandbox(); a = s1.exec(s1.create(SandboxSpec(node_id="n0")), "python -m pytest x")
    s2 = MockSandbox(); b = s2.exec(s2.create(SandboxSpec(node_id="n0")), "python -m pytest x")
    assert a.stdout == b.stdout


def test_non_pytest_commands_ok():
    s = MockSandbox()
    sid = s.create(SandboxSpec())
    assert s.exec(sid, "echo hello").stdout == "hello"
    assert s.exec(sid, "ls -la").exit_code == 0


def test_verify_patch_command():
    s = MockSandbox()
    sid = s.create(SandboxSpec(node_id="nb-h100-04"))
    s.put_files(sid, {"fix.patch": "--- a/x\n+++ b/x\n"})

    # the live command applies with patch-ng and re-runs the whole test file,
    # naming the target through NGE_FIX_TEST instead of -k
    ok = s.exec(sid, "python -m patch_ng --strip 1 fix.patch && "
                     "NGE_FIX_TEST=test_plan_order python -m pytest pkg/t.py -q")
    assert ok.exit_code == 0 and "successfully patched" in ok.stdout
    assert "1 passed" in ok.stdout

    ko = s.exec(sid, "python -m patch_ng --strip 1 fix.patch && "
                     "NGE_FIX_TEST=test_upload_mock python -m pytest pkg/t.py -q")
    assert ko.exit_code == 1 and "still failing" in ko.stdout

    # the older -k form still parses, so a hand-written command keeps working
    legacy = s.exec(sid, "git apply fix.patch && python -m pytest pkg -q -k test_plan_order")
    assert legacy.exit_code == 0


def test_collect_returns_requested_paths():
    s = MockSandbox()
    sid = s.create(SandboxSpec())
    s.put_files(sid, {"report.md": "# hi"})
    got = s.collect(sid, ["report.md", "missing.txt"])
    assert got["report.md"] == "# hi"
    assert "missing.txt" in got
