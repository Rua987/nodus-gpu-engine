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


# -- layer 7: the model also guesses the line, and sometimes the whole file --

REAL = "packages/engine/nge/policy.py"


def _real_lines(o, n=2):
    src = o._payload_files(REAL)[REAL].splitlines()
    i = next(k for k, l in enumerate(src) if "MAX_COMMAND_LEN" in l)
    return i + 1, src[i:i + n]


def test_relocate_moves_a_hunk_to_its_real_line(tmp_path):
    o = _orch(tmp_path)
    line, ctx = _real_lines(o)
    body = "\n".join(" " + c for c in ctx)
    patch = f"--- a/{REAL}\n+++ b/{REAL}\n@@ -3,2 +3,2 @@\n{body}\n+new\n"
    out = o._relocate_hunks(patch)
    hdr = [l for l in out.splitlines() if l.startswith("@@")][0]
    assert hdr.startswith(f"@@ -{line},"), f"expected line {line}, got {hdr}"
    assert [e for e in o.events if e["kind"] == "patch_relocated"]


def test_relocate_leaves_a_correct_hunk_alone(tmp_path):
    o = _orch(tmp_path)
    line, ctx = _real_lines(o, 1)
    patch = (f"--- a/{REAL}\n+++ b/{REAL}\n"
             f"@@ -{line},1 +{line},1 @@\n {ctx[0]}\n")
    assert f"@@ -{line}," in o._relocate_hunks(patch)
    assert not [e for e in o.events if e["kind"] == "patch_relocated"]


def test_invented_context_is_detected(tmp_path):
    """Live: Nemotron patched nodus_tools.py quoting lines that exist nowhere
    in it - the function it meant is at line 1200 and looks nothing like that.
    No amount of relocating can save such a patch."""
    o = _orch(tmp_path)
    patch = (f"--- a/{REAL}\n+++ b/{REAL}\n@@ -1,2 +1,2 @@\n"
             " def totally_made_up(self, x):\n-    return x - 1\n+    return x + 1\n")
    assert o._patch_context_missing(patch) == [REAL]


def test_real_context_passes(tmp_path):
    o = _orch(tmp_path)
    patch = (f"--- a/{REAL}\n+++ b/{REAL}\n@@ -1,2 +1,2 @@\n"
             " MAX_COMMAND_LEN = 4096\n-x\n+y\n")
    assert o._patch_context_missing(patch) == []


def test_a_fabricated_patch_costs_no_gpu(tmp_path, monkeypatch):
    provisioned = []
    real_prov = handlers.gpu_provision
    monkeypatch.setattr(handlers, "gpu_provision",
                        lambda **kw: provisioned.append(1) or real_prov(**kw))

    o = _orch(tmp_path)
    o._propose_patch = lambda f, m: (
        f"--- a/{REAL}\n+++ b/{REAL}\n@@ -1,2 +1,2 @@\n"
        " def never_written_here(a):\n-    return 1\n+    return 2\n")
    handlers.reset_state(o.config)
    out = o._attempt_fixes([{"test": "t.py::test_a", "error": "boom"}], TARGET)

    assert provisioned == [], "no node may be provisioned for an impossible patch"
    assert out[0]["verified"] is False
    assert "does not exist" in out[0]["reason"]
    assert [e for e in o.events if e["kind"] == "fix_context_invented"]


# -- the module under test must reach the prompt ----------------------------

def test_under_test_resolves_and_is_emitted(tmp_path):
    o = _orch(tmp_path)
    s = o._under_test({"test": "packages/nodus/tests/test_nodus_tools.py"
                               "::TestRepairLlmFilePath::test_drive_underscore_prefix"},
                      "packages/nodus")
    assert "def repair_llm_file_path" in s
    ev = [e for e in o.events if e["kind"] == "under_test"]
    assert ev and any("nodus_tools.py" in r for r in ev[0]["resolved"])


def test_under_test_is_safe_on_junk(tmp_path):
    o = _orch(tmp_path)
    for tid in ["", "no-separator", "x::nope", "../../../etc/passwd::t",
                "does/not/exist.py::t"]:
        assert o._under_test({"test": tid}, "") == ""


def test_the_module_source_reaches_the_model(tmp_path):
    seen = {}

    def chat_fn(messages, model=None, tools=None):
        seen["prompt"] = messages[-1]["content"]
        return {"content": "```diff\n--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,1 @@\n-a\n+b\n```"}

    o = _orch(tmp_path, chat_fn=chat_fn)
    o._propose_patch({"test": "t.py::test_a", "error": "boom",
                      "under_test": "mylib.py line 7, the code under test, "
                                    "exact text:\n    7| def helper(a):"},
                     "m")
    assert "def helper(a):" in seen["prompt"]
    assert "VERBATIM" in seen["prompt"], "the model must be told not to retype"


# -- a fix must not break its neighbours ------------------------------------

TF = "packages/nodus/tests/test_x.py"


def _fix_run(tmp_path, monkeypatch, stdout, failures=None):
    """Run one fix attempt whose sandbox returns `stdout`."""
    seen = {}

    def spy(command, node_id=None, files=None, **kw):
        if "fix.patch" in command:
            seen["cmd"] = command
            return {"sandbox_id": "s", "node_id": node_id, "exit_code": 1,
                    "ok": False, "stdout": stdout, "stderr": "",
                    "duration_s": 0.1, "artifacts": {}}
        return {"sandbox_id": "s", "node_id": node_id, "exit_code": 0,
                "ok": True, "stdout": "", "stderr": "", "duration_s": 0.1,
                "artifacts": {}}
    monkeypatch.setattr(handlers, "run_in_sandbox", spy)

    o = _orch(tmp_path)
    o._propose_patch = lambda f, m: "--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,1 @@\n-a\n+b\n"
    handlers.reset_state(o.config)
    fixes = o._attempt_fixes(failures or [{"test": f"{TF}::test_a", "error": "boom"}],
                             "packages/nodus/tests")
    return o, fixes, seen


def test_the_whole_suite_is_re_run_not_just_the_test(tmp_path, monkeypatch):
    """`-k <test>` only answers 'does this one pass now', and even the test's
    own file is too narrow: a patch edits a module other files import too."""
    _, _, seen = _fix_run(tmp_path, monkeypatch, "1 passed in 0.1s")
    assert TARGET in seen["cmd"], "the whole suite must be re-run"
    assert " -k " not in seen["cmd"], "not just the single test"


def test_a_failure_in_an_unexecuted_file_is_not_blamed_on_the_patch(
        tmp_path, monkeypatch):
    """A skipped or dead shard leaves no baseline for its files, so a
    pre-existing failure there must not read as damage this patch did."""
    out = ("FAILED packages/nodus/tests/test_never_ran.py::test_z - old\n"
           "1 failed")
    o = _orch(tmp_path)

    def spy(command, node_id=None, files=None, **kw):
        if "fix.patch" in command:
            return {"sandbox_id": "s", "node_id": node_id, "exit_code": 1,
                    "ok": False, "stdout": out, "stderr": "", "duration_s": 0.1,
                    "artifacts": {}}
        return {"sandbox_id": "s", "node_id": node_id, "exit_code": 0,
                "ok": True, "stdout": "", "stderr": "", "duration_s": 0.1,
                "artifacts": {}}
    monkeypatch.setattr(handlers, "run_in_sandbox", spy)
    o._propose_patch = lambda f, m: (
        "--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,1 @@\n-a\n+b\n")
    handlers.reset_state(o.config)

    fixes = o._attempt_fixes([{"test": f"{TF}::test_a", "error": "boom"}],
                             TARGET, covered={TF})
    assert fixes[0]["verified"] is True, fixes[0].get("reason")
    assert [e for e in o.events if e["kind"] == "fix_unjudged"]


def test_a_patch_that_breaks_a_neighbour_is_rejected(tmp_path, monkeypatch):
    """The target test passes, but the patch broke another one in the file.
    This used to be reported as fix OK."""
    out = f"FAILED {TF}::test_other - AssertionError\n1 failed, 5 passed"
    o, fixes, _ = _fix_run(tmp_path, monkeypatch, out)
    assert fixes[0]["verified"] is False
    assert fixes[0]["regressions"] == [f"{TF}::test_other"]
    assert "broke" in fixes[0]["reason"]
    assert [e for e in o.events if e["kind"] == "fix_regression"]


def test_a_pre_existing_failure_is_not_counted_as_a_regression(tmp_path, monkeypatch):
    """Another test in the file was already red before the patch: the fix is
    still valid, and the exit code alone could never tell the difference."""
    out = f"FAILED {TF}::test_already_red - AssertionError\n1 failed, 5 passed"
    known = [{"test": f"{TF}::test_a", "error": "boom"},
             {"test": f"{TF}::test_already_red", "error": "was red"}]
    _, fixes, _ = _fix_run(tmp_path, monkeypatch, out, failures=known)
    # _attempt_fixes orders by error length, so pick the one we mean rather
    # than assuming an index
    fix = next(x for x in fixes if x["test"] == f"{TF}::test_a")
    assert fix["verified"] is True, fix.get("reason")
    assert fix["regressions"] == []


def test_the_target_still_failing_is_rejected(tmp_path, monkeypatch):
    out = f"FAILED {TF}::test_a - still broken\n1 failed"
    _, fixes, _ = _fix_run(tmp_path, monkeypatch, out)
    assert fixes[0]["verified"] is False
    assert fixes[0]["reason"] == "target test still failing"


def test_empty_output_is_not_a_pass(tmp_path, monkeypatch):
    """No output means nothing ran - the exact shape of the git: not found bug,
    where an empty stdout was indistinguishable from a clean pass."""
    o, fixes, _ = _fix_run(tmp_path, monkeypatch, "")
    assert fixes[0]["verified"] is False
    assert fixes[0]["reason"] == "sandbox produced no output - nothing ran"
    ev = [e for e in o.events if e["kind"] == "fix_rejected"][0]
    assert ev["target_fixed"] is False, "absence of failures is not a pass"


# -- the model sometimes answers nothing at all ------------------------------

def test_an_empty_reply_is_retried_once(tmp_path):
    """Live, Nemotron returned an empty string for a prompt that had produced
    a valid diff a run earlier - two runs lost fixes to `has_patch: False`."""
    calls = []
    diff = "--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,1 @@\n-a\n+b\n"

    def chat_fn(messages, model=None, tools=None):
        calls.append(1)
        return {"content": "" if len(calls) == 1 else f"```diff\n{diff}```"}

    o = _orch(tmp_path, chat_fn=chat_fn)
    got = o._propose_patch({"test": "t.py::test_a", "error": "e"}, "m")
    assert got == diff, "the retry's patch must be used"
    assert len(calls) == 2, "exactly one retry"
    assert [e for e in o.events if e["kind"] == "patch_retry_succeeded"]


def test_two_empty_replies_give_up_and_say_so(tmp_path):
    o = _orch(tmp_path, chat_fn=lambda m, mo=None, t=None: {"content": ""})
    assert o._propose_patch({"test": "t.py::test_a", "error": "e"}, "m") is None
    empties = [e for e in o.events if e["kind"] == "patch_empty"]
    assert [e["attempt"] for e in empties] == [1, 2]
    assert empties[0]["reply_chars"] == 0


def test_a_prose_reply_is_not_called_empty(tmp_path):
    """Live, a 681-character answer with no diff in it was logged as
    `patch_empty`. Said nothing vs answered-without-a-diff are different
    problems and must not share a name."""
    prose = "I cannot fix this without seeing the caller. " * 4
    o = _orch(tmp_path, chat_fn=lambda m, mo=None, t=None: {"content": prose})
    assert o._propose_patch({"test": "t.py::test_a", "error": "e"}, "m") is None
    assert not [e for e in o.events if e["kind"] == "patch_empty"]
    un = [e for e in o.events if e["kind"] == "patch_unparsed"]
    assert len(un) == 2
    assert un[0]["reply_chars"] == len(prose)
    assert "cannot fix this" in un[0]["reply_head"], "keep a readable excerpt"
    assert un[0]["why"] == "no diff in the reply"


def test_headerless_hunks_are_named_as_such(tmp_path):
    """Hunks with no `--- a/<path>`: the reply *is* a diff, but nothing says
    which file. Distinct from a refusal, and not silently the same failure."""
    headerless = "```diff\n@@ -1,2 +1,2 @@\n keep\n-old\n+new\n```"
    o = _orch(tmp_path, chat_fn=lambda m, mo=None, t=None: {"content": headerless})
    assert o._propose_patch({"test": "t.py::test_a", "error": "e"}, "m") is None
    un = [e for e in o.events if e["kind"] == "patch_unparsed"]
    assert un and un[0]["why"] == "hunks with no file header"


def test_a_good_first_reply_is_not_retried(tmp_path):
    calls = []
    diff = "--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,1 @@\n-a\n+b\n"

    def chat_fn(messages, model=None, tools=None):
        calls.append(1)
        return {"content": f"```diff\n{diff}```"}

    o = _orch(tmp_path, chat_fn=chat_fn)
    assert o._propose_patch({"test": "t.py::test_a", "error": "e"}, "m") == diff
    assert len(calls) == 1, "no wasted call"
    assert not [e for e in o.events if e["kind"] == "patch_empty"]


def test_an_exception_is_not_retried(tmp_path):
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise TimeoutError("504")

    o = _orch(tmp_path, chat_fn=boom)
    assert o._propose_patch({"test": "t.py::test_a", "error": "e"}, "m") is None
    assert len(calls) == 1, "a failing endpoint is not hammered"
    assert [e for e in o.events if e["kind"] == "patch_error"]
