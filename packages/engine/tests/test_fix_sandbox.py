"""The auto-fix verification sandbox.

Regression: it never verified anything. Its command began with `git init`, and
python:3.12-slim ships neither git nor patch, so every attempt died on
`git: not found` (exit 127) and was reported as "patch rejected". `0/N
verified` said nothing about the patches - they were never applied.

It also got none of the environment the shards got: no pytest, no PYTHONPATH,
no dependencies, and only the files the diff touched instead of the tree.
"""
from nge import config as _cfg
from nge.orchestrator import NgeOrchestrator
from nge.tools import handlers

TARGET = "packages/nodus/tests"


def _orch(tmp_path, **kw):
    return NgeOrchestrator(config=_cfg.load(
        fleet_mode="mock", sandbox_mode="mock", out_dir=tmp_path), **kw)


def test_fix_command_uses_an_applier_the_image_actually_has(tmp_path, monkeypatch):
    seen = {}

    def spy(command, node_id=None, files=None, **kw):
        if "fix.patch" in command:
            seen["cmd"], seen["files"] = command, dict(files or {})
        return {"sandbox_id": "s", "node_id": node_id, "exit_code": 0,
                "ok": True, "stdout": "1 passed", "stderr": "",
                "duration_s": 0.1, "artifacts": {}}
    monkeypatch.setattr(handlers, "run_in_sandbox", spy)

    o = _orch(tmp_path)
    o._propose_patch = lambda f, m: "--- a/x.py\n+++ b/x.py\n@@\n-a\n+b\n"
    handlers.reset_state(o.config)
    o._attempt_fixes([{"test": "t.py::test_a", "error": "boom"}], TARGET,
                     source_root="packages/nodus",
                     requirements="packages/nodus/requirements-ci.txt",
                     payload={"packages/nodus/x.py": "a\n"})

    cmd = seen["cmd"]
    assert "git" not in cmd, "the image has no git"
    assert "patch_ng" in cmd, "needs an applier that pip can install"
    assert "pip install" in cmd and "patch-ng" in cmd
    assert "requirements-ci.txt" in cmd, "same deps as a shard"
    assert "PYTHONPATH=" in cmd, "same import path as a shard"


def test_fix_sandbox_receives_the_whole_payload(tmp_path, monkeypatch):
    seen = {}

    def spy(command, node_id=None, files=None, **kw):
        if "fix.patch" in command:
            seen["files"] = dict(files or {})
        return {"sandbox_id": "s", "node_id": node_id, "exit_code": 1,
                "ok": False, "stdout": "", "stderr": "", "duration_s": 0.1,
                "artifacts": {}}
    monkeypatch.setattr(handlers, "run_in_sandbox", spy)

    o = _orch(tmp_path)
    o._propose_patch = lambda f, m: "--- a/x.py\n+++ b/x.py\n@@\n-a\n+b\n"
    handlers.reset_state(o.config)
    payload = {"packages/nodus/mod.py": "x\n", "packages/nodus/other.py": "y\n"}
    o._attempt_fixes([{"test": "t.py::test_a", "error": "boom"}], TARGET,
                     payload=payload)

    assert "fix.patch" in seen["files"]
    for k in payload:
        assert k in seen["files"], f"{k} must reach the fix sandbox"


# -- the code agent must see why the test failed -----------------------------

STDOUT = """=================== FAILURES ===================
_________________ TestRepair.test_alpha _________________
packages/nodus/tests/test_x.py:178: in test_alpha
    assert got == expected
E   AssertionError: assert 'C:/x' == '_p0/x'
_________________ TestRepair.test_beta _________________
beta traceback here
=========== short test summary info ==========="""


def test_failure_context_extracts_the_right_block(tmp_path):
    c = _orch(tmp_path)._failure_context(STDOUT, "t.py::TestRepair::test_alpha")
    assert "AssertionError" in c and "test_x.py:178" in c
    assert "beta traceback" not in c, "must stop at the next failure block"


def test_failure_context_is_empty_when_absent(tmp_path):
    o = _orch(tmp_path)
    assert o._failure_context(STDOUT, "t.py::test_nope") == ""
    assert o._failure_context("", "t.py::test_alpha") == ""


def test_context_reaches_the_model(tmp_path):
    """`Error: (no message; see shard output)` was all the agent ever got."""
    seen = {}

    def chat_fn(messages, model=None, tools=None):
        seen["prompt"] = messages[-1]["content"]
        return {"content": "```diff\n--- a/x.py\n+++ b/x.py\n@@\n-a\n+b\n```"}

    o = _orch(tmp_path, chat_fn=chat_fn)
    o._propose_patch({"test": "t.py::TestRepair::test_alpha",
                      "error": "(no message; see shard output)",
                      "context": "E   AssertionError: assert 'C:/x' == '_p0/x'"},
                     "m")
    assert "AssertionError" in seen["prompt"]
    assert "repo-relative" in seen["prompt"], "the diff paths must be constrained"


def test_shard_result_keeps_stdout_for_triage(tmp_path):
    rep = _orch(tmp_path).run({"task": "t", "shards": 2, "target": TARGET})
    assert any(s.stdout for s in rep.shards), "triage needs the shard output"
