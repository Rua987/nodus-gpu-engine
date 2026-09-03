"""Regressions for the three critical audit findings (Lot 1).

1. a crash between provision and release used to leak the GPU fleet (billing)
2. the capability jail vetted only the head of a chained command
3. the auto-fix sandbox never received the source tree, so `git apply` could
   not succeed against a real sandbox
"""
import pytest

from nge import config as _cfg
from nge.orchestrator import _REPO_ROOT, NgeOrchestrator
from nge.tools import handlers

SCENARIO = {"task": "run tests", "shards": 3, "gpu_type": "A100",
            "target": "packages/nodus/tests"}


def _orch(tmp_path, **kw):
    return NgeOrchestrator(config=_cfg.load(
        fleet_mode="mock", sandbox_mode="mock", out_dir=tmp_path), **kw)


# -- 1. the fleet must always be released -----------------------------------

def test_fleet_is_released_when_the_run_crashes(tmp_path):
    o = _orch(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("Nemotron 500")
    o._attempt_fixes = boom

    with pytest.raises(RuntimeError, match="Nemotron 500"):
        o.run(SCENARIO)

    released = [e for e in o.events if e["kind"] == "gpu_release"]
    assert released, "gpu_release must run even when the pipeline raises"
    assert len(released[-1]["released"]) == 3
    assert handlers.gpu_status()["nodes"] == [], "no node may survive the run"


def test_crash_emits_a_run_error_event(tmp_path):
    o = _orch(tmp_path)
    o._attempt_fixes = lambda *a, **k: (_ for _ in ()).throw(ValueError("nope"))
    with pytest.raises(ValueError):
        o.run(SCENARIO)
    errs = [e for e in o.events if e["kind"] == "run_error"]
    assert errs and "ValueError: nope" in errs[0]["error"]


def test_keyboard_interrupt_still_releases(tmp_path):
    o = _orch(tmp_path)
    o._attempt_fixes = lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        o.run(SCENARIO)
    assert [e for e in o.events if e["kind"] == "gpu_release"]
    assert handlers.gpu_status()["nodes"] == []


def test_happy_path_still_releases_exactly_once(tmp_path):
    o = _orch(tmp_path)
    rep = o.run(SCENARIO)
    assert rep.ok
    assert len([e for e in o.events if e["kind"] == "gpu_release"]) == 1
    assert handlers.gpu_status()["nodes"] == []


# -- 3. the auto-fix sandbox must receive the sources ------------------------

def test_sources_for_patch_reads_real_repo_files(tmp_path):
    o = _orch(tmp_path)
    rel = "packages/engine/nge/policy.py"
    got = o._sources_for_patch(f"--- a/{rel}\n+++ b/{rel}\n@@\n-x\n+y\n")
    assert list(got) == [rel]                       # deduped across --- / +++
    assert "check_command" in got[rel]              # real content, not a stub


def test_sources_for_patch_refuses_path_escape(tmp_path):
    o = _orch(tmp_path)
    for evil in ["../../../../etc/passwd", "../../.nebius_api_key",
                 "../../../secrets.env"]:
        assert o._sources_for_patch(f"--- a/{evil}\n+++ b/{evil}\n") == {}


def test_sources_for_patch_skips_missing_and_dev_null(tmp_path):
    o = _orch(tmp_path)
    assert o._sources_for_patch("--- a/does/not/exist.py\n+++ b/x.py\n") == {}
    assert o._sources_for_patch("--- /dev/null\n+++ b/new.py\n") == {}


def test_fix_run_ships_patch_and_sources_and_inits_a_repo(tmp_path, monkeypatch):
    seen = {}
    real = handlers.run_in_sandbox

    def spy(command, node_id=None, files=None, **kw):
        if "git apply" in command:
            seen["command"] = command
            seen["files"] = sorted(files or {})
        return real(command=command, node_id=node_id, files=files, **kw)
    monkeypatch.setattr(handlers, "run_in_sandbox", spy)

    o = _orch(tmp_path)
    o._propose_patch = lambda f, m: (
        "--- a/packages/engine/nge/policy.py\n"
        "+++ b/packages/engine/nge/policy.py\n@@\n-x\n+y\n")
    o.run(SCENARIO)

    assert "fix.patch" in seen["files"]
    assert "packages/engine/nge/policy.py" in seen["files"], \
        "the sandbox must get the file the patch touches"
    assert "git init" in seen["command"], "git apply needs a work tree"


# -- injection: the test keyword reaches a shell -----------------------------

def test_fix_command_quotes_the_test_keyword(tmp_path, monkeypatch):
    """`kw` comes from sandbox stdout via _FAILED_RE (\\S+ admits ';'), so it
    must be quoted before it is interpolated into a shell command."""
    from nge import policy
    seen = {}

    def spy(command, node_id=None, files=None, **kw):
        seen["c"] = command
        return {"sandbox_id": "x", "node_id": node_id, "exit_code": 1,
                "ok": False, "stdout": "", "stderr": "", "duration_s": 0.0,
                "artifacts": {}}
    monkeypatch.setattr(handlers, "run_in_sandbox", spy)

    o = _orch(tmp_path)
    o._propose_patch = lambda f, m: "--- a/x.py\n+++ b/x.py\n@@\n-a\n+b\n"
    handlers.reset_state(o.config)
    o._attempt_fixes([{"test": "t.py::test_a;whoami", "error": "boom"}],
                     "packages/nodus/tests")
    cmd = seen["c"]
    assert "'test_a;whoami'" in cmd, "keyword must be shell-quoted"
    # and the jail sees one quoted argument, not a second command
    assert len(policy.split_segments(cmd)) == 4      # init, add, apply, pytest
    assert policy.check_command(cmd)[0]


# -- gpu_type must follow the scenario --------------------------------------

def test_gpu_type_propagates_to_replacement_and_fix_nodes(tmp_path):
    o = _orch(tmp_path)
    o.run(SCENARIO)                                   # gpu_type A100
    ids = [e["node_id"] for e in o.events
           if e["kind"] in ("gpu_provision_replacement",)]
    ids += [f["node"] for f in o.fixes if f.get("node")]
    assert ids, "expected at least one replacement or fix node"
    assert all("a100" in i for i in ids), f"H100 leaked into {ids}"
