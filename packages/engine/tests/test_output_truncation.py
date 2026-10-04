"""A sandbox that cuts its output must not invent tests nor hide regressions.

Live (Compute Phase 3 hybrid run): a `-v` shard outgrew ContreeSDK's 64 KiB
stdout default; the output ended on `FAILED ...::test_connect_mc`, the head of
`test_connect_mcp_forwards_org_id_env`, and the run counted 5 unique failures
of which one was that fragment - the real one never reached the parser.
"""
from nge import config as _cfg
from nge.orchestrator import NgeOrchestrator, _complete_stdout, _parse_failures
from nge.tools import handlers

G = "packages/nodus/tests/test_nodus_grafana.py"
CUT = (f"{G}::test_connect_mcp_falls_back_to_mock_without_launcher FAILED [ 50%]\n"
       f"FAILED {G}::test_connect_mcp_falls_back_to_mock_without_launcher\n"
       f"FAILED {G}::test_connect_mc")


def test_the_fragment_a_cut_leaves_is_not_a_test():
    assert [f["test"] for f in _parse_failures({"stdout": CUT, "truncated": True})] == \
        [f"{G}::test_connect_mcp_falls_back_to_mock_without_launcher"]
    # an uncut output is parsed whole: its last line is a real line
    assert len(_parse_failures({"stdout": CUT})) == 2
    assert _complete_stdout({"stdout": "no newline at all", "truncated": True}) == ""


def _orch(tmp_path):
    return NgeOrchestrator(config=_cfg.load(
        fleet_mode="mock", sandbox_mode="mock", out_dir=tmp_path))


def test_a_cut_shard_is_named_in_the_events_and_the_report(tmp_path, monkeypatch):
    real = handlers.run_in_sandbox

    def cut_shards(command, node_id=None, files=None, **kw):
        res = real(command=command, node_id=node_id, files=files, **kw)
        if "patch_ng" not in command:
            res = dict(res, stdout=CUT, truncated=True)
        return res
    monkeypatch.setattr(handlers, "run_in_sandbox", cut_shards)
    o = _orch(tmp_path)
    rep = o.run({"task": "run tests", "shards": 1, "target": "packages/nodus/tests",
                 "auto_fix": False, "self_heal": False})
    assert [e["index"] for e in o.events if e["kind"] == "shard_output_truncated"] == [0]
    assert [f["test"] for f in rep.failures] == \
        [f"{G}::test_connect_mcp_falls_back_to_mock_without_launcher"]
    text = open(rep.artifact_path, encoding="utf-8").read()
    assert "output cut at the sandbox size limit" in text


def test_a_cut_verification_run_is_no_verdict(tmp_path, monkeypatch):
    """A clean-looking head says nothing about the regressions past the cut."""
    def spy(command, node_id=None, files=None, **kw):
        return {"sandbox_id": "x", "node_id": node_id, "exit_code": 0, "ok": True,
                "stdout": "....................\n1 passed\n...", "stderr": "",
                "duration_s": 0.0, "artifacts": {}, "truncated": True}
    monkeypatch.setattr(handlers, "run_in_sandbox", spy)
    o = _orch(tmp_path)
    o._propose_patch = lambda f, m: "--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,1 @@\n-a\n+b\n"
    handlers.reset_state(o.config)
    (fix,) = o._attempt_fixes([{"test": "t.py::test_a", "error": "boom"}],
                              "packages/nodus/tests")
    assert fix["verified"] is False and "cut at the sandbox size limit" in fix["reason"]
    (rej,) = [e for e in o.events if e["kind"] == "fix_rejected"]
    assert rej["output_truncated"] is True
