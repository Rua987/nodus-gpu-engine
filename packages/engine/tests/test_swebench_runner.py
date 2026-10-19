"""bench/swebench_runner.py with a fake sandbox and a fake model - no network."""
import json

from bench import swebench_runner as sr
from nge import attempts

SRC = "def name_ok(name):\n    return True\n"
TASK = {
    "instance_id": "acme__lib-1", "repo": "acme/lib",
    "problem_statement": "Blueprint names must not be empty.",
    "FAIL_TO_PASS": json.dumps(["tests/test_x.py::test_empty", "tests/test_x.py::test_dot"]),
    "PASS_TO_PASS": json.dumps(["tests/test_x.py::test_ok"]),
    "test_patch": "--- a/tests/test_x.py\n+++ b/tests/test_x.py\n@@ -1 +1,2 @@\n x\n+y\n",
}
GOOD = ("```diff\n--- a/src/lib/core.py\n+++ b/src/lib/core.py\n@@ -1,2 +1,2 @@\n"
        " def name_ok(name):\n-    return True\n+    return bool(name)\n```")


class FakeSandbox:
    def __init__(self, log, verify_out):
        self.log, self.verify_out = log, verify_out

    def put_files(self, sid, files):
        self.log.append(("files", sorted(files)))

    def exec(self, sid, cmd, timeout=0):
        self.log.append(("cmd", cmd))

        class R:
            exit_code, stderr, truncated = 0, "", False
        r = R()
        if "ls-files" in cmd:
            r.stdout = ("===NGE:test_patch exit=0===\n"
                        "FAILED tests/test_x.py::test_empty - AssertionError\n"
                        "===NGE:visible exit=1===\nsrc/lib/core.py\nsrc/lib/util.py\n"
                        "===NGE:files exit=0===\n")
        elif "cat " in cmd:
            r.stdout = SRC + "===NGE:file:src/lib/core.py exit=0===\n"
        else:
            r.stdout = self.verify_out
        return r

    def destroy(self, sid):
        pass


def _run(verify_out, patch_reply=GOOD, pick='{"files": ["src/lib/core.py", "nope.py"]}'):
    log, prompts = [], {}

    def factory(image):
        log.append(("image", image))
        return FakeSandbox(log, verify_out), "sid"

    def chat(prompt, kind):
        prompts[kind] = prompt
        return {"content": pick} if kind == "pick" else {"content": patch_reply, "finish_reason": "stop"}
    return sr.run_task(TASK, factory, chat), log, prompts


PASS_ALL = ("===NGE:test_patch exit=0===\nNGE_APPLIED:strict\n===NGE:model_patch exit=0===\n"
            "PASSED tests/test_x.py::test_empty\nPASSED tests/test_x.py::test_dot\n"
            "PASSED tests/test_x.py::test_ok\n===NGE:verify exit=0===\n")


def test_a_task_is_resolved_only_on_its_own_criterion():
    rec, log, prompts = _run(PASS_ALL)
    assert rec["resolved"] and rec["reason"] == "resolved" and rec["applied"] == "strict"
    assert (rec["visible"], rec["hidden"]) == (1, 1)
    assert rec["files_chosen"] == ["src/lib/core.py"]             # an unlisted pick is dropped
    assert ("image", "swebench/sweb.eval.x86_64.acme_1776_lib-1:latest") in log


def test_the_hidden_test_is_never_shown_to_the_model():
    rec, log, prompts = _run(PASS_ALL)
    baseline = next(c for k, c in log if k == "cmd" and "ls-files" in c)
    assert "test_empty" in baseline and "test_dot" not in baseline
    assert "test_dot" not in prompts["pick"] and "test_dot" not in prompts["patch"]
    assert "    1| def name_ok(name):" in prompts["patch"]           # numbered, exact text


def test_held_out_failure_and_regression_are_named():
    held = PASS_ALL.replace("PASSED tests/test_x.py::test_dot", "FAILED tests/test_x.py::test_dot")
    rec, _, _ = _run(held)
    assert not rec["resolved"] and rec["reason"] == "held-out tests still failing"
    broke = PASS_ALL.replace("PASSED tests/test_x.py::test_ok", "FAILED tests/test_x.py::test_ok")
    rec, _, _ = _run(broke)
    assert not rec["resolved"] and rec["reason"].startswith("broke ")


def test_a_patch_that_does_not_apply_says_so():
    rec, _, _ = _run(PASS_ALL.replace("NGE_APPLIED:strict\n", ""))
    assert rec["applied"] == "no" and rec["reason"] == "patch did not apply"


def test_no_diff_is_reported_and_no_verification_runs():
    rec, log, _ = _run(PASS_ALL, patch_reply="I would change core.py.")
    assert rec["reason"] == "no patch proposed" and "patch_unparsed" in rec["events"]
    assert not any(k == "cmd" and "model.patch" in c for k, c in log)


def test_the_attempt_is_archived_with_its_category(tmp_path):
    rec, _, _ = _run(PASS_ALL.replace("NGE_APPLIED:strict\n", ""))
    sr.archive(tmp_path, "20261018T000000Z", rec, "FAILED ...", {"source": "model"})
    (row,) = attempts.load(tmp_path)
    assert row["category"] == "did_not_apply" and row["target"] == "swebench:acme/lib"


def test_split_keeps_one_visible_and_hides_half():
    assert sr.split_f2p(["a"]) == (["a"], [])
    assert sr.split_f2p(["a", "b", "c"]) == (["a", "b"], ["c"])



# -- aligning a diff to the real file ------------------------------------------------

# the shape of src/flask/blueprints.py around the fix (8 / 12 spaces deep)
BLUEPRINT = (
    "class Blueprint:\n"
    "    def __init__(self, name, url_prefix=None, subdomain=None):\n"
    "        super().__init__()\n"
    "\n"
    "        if \".\" in name:\n"
    "            raise ValueError(\"'name' may not contain a dot '.' character.\")\n"
    "\n"
    "        self.name = name\n"
    "        self.url_prefix = url_prefix\n"
    "        self.subdomain = subdomain\n"
    "        self.deferred_functions: t.List[DeferredSetupFunction] = []\n"
)
# the diff Nemotron wrote for pallets__flask-5014 (archived 2026-10-18, reasoning off):
# the right fix, at "line 1", with its context typed 4 spaces too shallow
NEMOTRON = (
    "--- a/src/flask/blueprints.py\n"
    "+++ b/src/flask/blueprints.py\n"
    "@@ -1,7 +1,10 @@\n"
    "     if \".\" in name:\n"
    "         raise ValueError(\"'name' may not contain a dot '.' character.\")\n"
    " \n"
    "+        if not name:\n"
    "+            raise ValueError(\"'name' must not be empty.\")\n"
    "+\n"
    "         self.name = name\n"
    "         self.url_prefix = url_prefix\n"
    "         self.subdomain = subdomain\n"
    "         self.deferred_functions: t.List[DeferredSetupFunction] = []\n"
)


def test_alignment_keeps_the_added_lines_and_retypes_the_context(tmp_path):
    import patch_ng
    fixed, notes = sr.align_to_source(NEMOTRON, {"src/flask/blueprints.py": BLUEPRINT})
    # moved from "line 1" to 5, then one file line added before (3 lines of
    # context before vs 4 after - see the balancing test below)
    assert "@@ -4,8 +4,11 @@" in fixed and notes
    added = [l for l in fixed.splitlines() if l.startswith("+") and not l.startswith("+++")]
    assert added == [l for l in NEMOTRON.splitlines() if l.startswith("+") and not l.startswith("+++")]
    # as written it does not apply; aligned it does, and adds exactly the model's lines
    f = tmp_path / "src" / "flask" / "blueprints.py"
    f.parent.mkdir(parents=True)
    f.write_text(BLUEPRINT, encoding="utf-8", newline="\n")
    assert not patch_ng.fromstring(NEMOTRON.encode()).apply(strip=1, root=str(tmp_path))
    assert patch_ng.fromstring(fixed.encode()).apply(strip=1, root=str(tmp_path))
    text = f.read_text(encoding="utf-8")
    assert "        if not name:\n            raise ValueError(\"'name' must not be empty.\")\n" in text


def test_a_hunk_that_is_nowhere_in_the_file_is_left_alone():
    bogus = NEMOTRON.replace('if "." in name:', "if name.startswith('_'):")
    out, notes = sr.align_to_source(bogus, {"src/flask/blueprints.py": BLUEPRINT})
    assert out == bogus and notes == ["hunk at line 1 not found in the file"]


def test_the_archive_keeps_the_exact_bytes(tmp_path):
    rec, _, _ = _run(PASS_ALL)
    sr.archive(tmp_path, "20261018T000000Z", rec, "FAILED ...", {"source": "model"})
    (row,) = attempts.load(tmp_path)
    raw = (tmp_path / "attempts" / row["dir"] / "diff.patch").read_bytes()
    assert b"\r\n" not in raw and raw.decode() == rec["patch"]



def test_context_is_balanced_so_git_apply_does_not_anchor_to_the_end(tmp_path):
    """git apply anchors a hunk with less context after than before to the end
    of the file: the reasoning-on flask-5014 diff, ending on an added line, was
    refused at line 193 of a 621-line file."""
    import shutil
    import subprocess
    ends_on_add = (
        "--- a/src/flask/blueprints.py\n+++ b/src/flask/blueprints.py\n@@ -5,4 +5,6 @@\n"
        "         if \".\" in name:\n"
        "             raise ValueError(\"'name' may not contain a dot '.' character.\")\n"
        "-\n"
        "-        self.name = name\n"
        "+        if not name:\n"
        "+            raise ValueError(\"'name' must not be empty.\")\n"
        "+\n"
        "+        self.name = name\n")
    fixed, notes = sr.align_to_source(ends_on_add, {"src/flask/blueprints.py": BLUEPRINT})
    body = fixed.splitlines()[3:]
    lead = next(k for k, b in enumerate(body) if b[:1] != " ")
    trail = next(k for k, b in enumerate(reversed(body)) if b[:1] != " ")
    assert trail >= lead == 2 and "context balanced from the file" in notes
    if not shutil.which("git"):
        return
    f = tmp_path / "src" / "flask" / "blueprints.py"
    f.parent.mkdir(parents=True)
    f.write_text(BLUEPRINT + "".join(f"# line {k}\n" for k in range(40)), encoding="utf-8",
                 newline="\n")
    (tmp_path / "x.patch").write_text(fixed, encoding="utf-8", newline="\n")
    (tmp_path / "raw.patch").write_text(ends_on_add, encoding="utf-8", newline="\n")
    git = lambda name: subprocess.run(["git", "apply", "--check", "--recount", name],  # noqa: E731
                                      cwd=tmp_path, capture_output=True).returncode
    subprocess.run(["git", "init", "-q", "."], cwd=tmp_path, check=True)
    assert git("raw.patch") != 0 and git("x.patch") == 0



def test_a_diff_with_no_change_lines_is_named_and_not_verified(tmp_path):
    """Reasoning on, flask-5014: the fix written as context, no + or - lines."""
    context_only = ("```diff\n--- a/src/lib/core.py\n+++ b/src/lib/core.py\n@@ -1,2 +1,2 @@\n"
                    " def name_ok(name):\n     return True\n```")
    rec, log, _ = _run(PASS_ALL, patch_reply=context_only)
    assert rec["reason"] == "diff changes nothing" and not rec["resolved"]
    assert not any(k == "cmd" and "model.patch" in c for k, c in log)
    sr.archive(tmp_path, "20261018T000000Z", rec, "FAILED ...", {"source": "model"})
    (row,) = attempts.load(tmp_path)
    assert row["category"] == "no_change"


def test_a_sandbox_error_is_retried_once():
    calls = {"n": 0}

    class Flaky(FakeSandbox):
        def exec(self, sid, cmd, timeout=0):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("ContreeImageStateError")
            return super().exec(sid, cmd, timeout)
    log = []
    rec = sr.run_task(TASK, lambda image: (Flaky(log, PASS_ALL), "sid"),
                      lambda prompt, kind: {"content": '{"files": ["src/lib/core.py"]}'}
                      if kind == "pick" else {"content": GOOD, "finish_reason": "stop"},
                      retry_wait=0)
    assert rec["resolved"] and rec["events"] == ["sandbox_retry:RuntimeError"]
