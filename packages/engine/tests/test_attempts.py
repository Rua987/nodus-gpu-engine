"""Every fix attempt is archived - kept, rejected or never produced (nge/attempts.py)."""
import json

from nge import attempts
from nge import config as _cfg
from nge.orchestrator import NgeOrchestrator

SCENARIO = {"task": "run tests and fix failures", "shards": 3, "gpu_type": "H100",
            "target": "packages/nodus/tests"}


def _run(tmp_path, n=1):
    o = NgeOrchestrator(config=_cfg.load(fleet_mode="mock", sandbox_mode="mock",
                                         out_dir=tmp_path))
    from dataclasses import replace
    from nge import planner
    o.config = replace(o.config, nodus_plan_ckpt=str(tmp_path / planner.FORCE_HEURISTIC / "x.pt"))
    for _ in range(n):
        o.run(SCENARIO)
    return o


def test_a_run_archives_every_attempt_with_its_verdict(tmp_path):
    o = _run(tmp_path)
    rows = attempts.load(tmp_path)
    assert len(rows) == len(o.fixes) == 3
    by = {r["test"].split("::")[-1]: r for r in rows}
    assert by["test_plan_order"]["verdict"] == "verified" and by["test_plan_order"]["category"] == "fixed"
    assert by["test_roundtrip"]["verdict"] == "no_patch"          # the canned catalogue has none
    for r in rows:
        d = tmp_path / "attempts" / r["dir"]
        assert (d / "attempt.json").is_file() and (d / "failure.txt").is_file()
        assert (d / "diff.patch").is_file() == bool(r["patch_chars"])
        assert r["source"] == "canned" and r["sandbox_mode"] == "mock"
    verified = tmp_path / "attempts" / by["test_plan_order"]["dir"]
    assert (verified / "pytest.log").is_file()
    (ev,) = [e for e in o.events if e["kind"] == "attempts_archived"]
    assert ev["dir"] == "attempts" and ev["attempts"] == 3       # relative: reports stay path-free


def test_runs_accumulate_and_nothing_is_overwritten(tmp_path):
    _run(tmp_path, n=2)
    rows = attempts.load(tmp_path)
    assert len(rows) == 6
    assert len({r["dir"] for r in rows}) == 6


def test_the_archive_can_be_turned_off(tmp_path, monkeypatch):
    monkeypatch.setenv("NGE_ARCHIVE_ATTEMPTS", "0")
    o = _run(tmp_path)
    assert attempts.load(tmp_path) == [] and not (tmp_path / "attempts").exists()
    assert not [e for e in o.events if e["kind"] == "attempts_archived"]


def test_categories_name_the_obstacle():
    c = attempts.category
    assert c({"verified": True, "patch": "d"}, []) == "fixed"
    assert c({"patch": None}, [{"kind": "patch_truncated"}]) == "truncated"
    assert c({"patch": None}, [{"kind": "patch_unparsed"}]) == "unparsed"
    assert c({"patch": None}, [{"kind": "patch_empty"}]) == "empty"
    assert c({"patch": None}, []) == "no_patch"
    assert c({"patch": "d"}, [{"kind": "fix_context_invented"}]) == "context_invented"
    assert c({"patch": "d", "regressions": ["t::x"]}, []) == "regression"
    assert c({"patch": "d", "reason": "re-run output cut at the sandbox size limit - ..."}, []) == "output_cut"
    assert c({"patch": "d", "reason": "sandbox produced no output - nothing ran"}, []) == "no_output"
    assert c({"patch": "d", "reason": "target test still failing"}, []) == "target_still_failing"
    assert set(attempts.CATEGORIES) >= {"fixed", "truncated", "context_invented", "regression"}


def test_model_settings_are_kept_with_the_attempt(tmp_path):
    def chat_fn(messages, mdl=None, tools=None, max_tokens=None, thinking=None):
        return {"content": "not a diff", "finish_reason": "stop", "reasoning_tokens": 42}
    o = NgeOrchestrator(config=_cfg.load(fleet_mode="mock", sandbox_mode="mock",
                                         out_dir=tmp_path), chat_fn=chat_fn)
    o._attempt_fixes([{"test": "t.py::test_a", "error": "boom", "context": "Traceback..."}],
                     "packages/nodus/tests")
    (r,) = attempts.load(tmp_path)
    assert (r["source"], r["category"], r["calls"], r["reasoning_tokens"]) == ("model", "unparsed", 1, 42)
    assert r["max_tokens"] and "thinking" in r
    d = tmp_path / "attempts" / r["dir"]
    assert "Traceback..." in (d / "failure.txt").read_text(encoding="utf-8")
    assert json.loads((d / "attempt.json").read_text(encoding="utf-8"))["test"] == "t.py::test_a"


def test_slugs_are_safe_directory_names():
    s = attempts.slug("packages/nodus/tests/test_x.py::TestK::test_y[a/b]")
    assert "/" not in s and ":" not in s and s.endswith("test_y__a__b")


def test_a_verification_that_ran_nothing_keeps_its_exit_code_and_stderr(tmp_path, monkeypatch):
    """patch-ng refuses a mis-indented diff with exit 127 and no output; the
    loop reports "nothing ran". The archive must keep what tells the two apart."""
    from nge.tools import handlers

    def chat_fn(messages, mdl=None, tools=None, max_tokens=None, thinking=None):
        return {"content": "```diff\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n```",
                "finish_reason": "stop"}

    def sandbox(command, node_id=None, files=None, **kw):
        return {"sandbox_id": "s", "node_id": node_id, "exit_code": 127, "ok": False,
                "stdout": "", "stderr": "", "duration_s": 0.1, "artifacts": {}}
    monkeypatch.setattr(handlers, "run_in_sandbox", sandbox)
    o = NgeOrchestrator(config=_cfg.load(fleet_mode="mock", sandbox_mode="mock",
                                         out_dir=tmp_path), chat_fn=chat_fn)
    monkeypatch.setattr(o, "_patch_context_missing", lambda patch: [])
    handlers.reset_state(o.config)
    o._attempt_fixes([{"test": "t.py::test_a", "error": "boom"}], "packages/nodus/tests")
    (r,) = attempts.load(tmp_path)
    assert (r["category"], r["exit_code"]) == ("no_output", 127)
    log = (tmp_path / "attempts" / r["dir"] / "pytest.log").read_text(encoding="utf-8")
    assert log.startswith("# exit code: 127\n")
