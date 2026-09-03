"""Shards must do different work, and the plan must decide how they are split.

Regression: every shard ran the identical `pytest <target>`. The command
carried NGE_SHARD=i/n and nothing on earth read it, so N GPUs executed the
same suite N times. The plan was equally inert - two completely different
plans produced byte-identical commands.
"""
import tempfile
from pathlib import Path

import pytest

from nge import config as _cfg
from nge.orchestrator import NgeOrchestrator

TARGET = "packages/nodus/tests"


def _orch(tmp_path, **kw):
    return NgeOrchestrator(config=_cfg.load(
        fleet_mode="mock", sandbox_mode="mock", out_dir=tmp_path), **kw)


# -- discovery ---------------------------------------------------------------

def test_discovers_test_files(tmp_path):
    files = _orch(tmp_path)._discover_test_files(TARGET)
    assert files, "expected test files under the vendored suite"
    assert all(f.startswith(TARGET) for f in files)
    assert all(Path(f).name.startswith("test_") or f.endswith("_test.py")
               for f in files)
    assert files == sorted(files), "must be deterministic"
    assert len(set(files)) == len(files), "no duplicates"


def test_discovery_refuses_path_escape(tmp_path):
    o = _orch(tmp_path)
    for evil in ["../../../etc", "../../..", "../../.nebius_api_key"]:
        assert o._discover_test_files(evil) == []


def test_discovery_of_a_missing_target_is_empty(tmp_path):
    assert _orch(tmp_path)._discover_test_files("does/not/exist") == []


# -- the split itself --------------------------------------------------------

def test_round_robin_covers_everything_exactly_once(tmp_path):
    o = _orch(tmp_path)
    files = [f"t{i}.py" for i in range(13)]
    for n in (1, 2, 3, 5, 13):
        parts = [o._shard_targets(files, i, n) for i in range(n)]
        flat = [f for p in parts for f in p]
        assert sorted(flat) == sorted(files), f"n={n} lost or duplicated a file"
        assert len(flat) == len(set(flat)), f"n={n} duplicated a file"


def test_round_robin_is_balanced(tmp_path):
    o = _orch(tmp_path)
    files = [f"t{i}.py" for i in range(13)]
    sizes = [len(o._shard_targets(files, i, 3)) for i in range(3)]
    assert max(sizes) - min(sizes) <= 1, sizes


def test_more_shards_than_files_leaves_some_empty(tmp_path):
    o = _orch(tmp_path)
    assert o._shard_targets(["a.py", "b.py"], 2, 4) == []


def test_no_files_yields_no_targets(tmp_path):
    assert _orch(tmp_path)._shard_targets([], 0, 3) == []


# -- end to end --------------------------------------------------------------

def test_shards_run_different_commands(tmp_path):
    rep = _orch(tmp_path).run({"task": "run tests", "shards": 3, "target": TARGET})
    cmds = [s.command for s in rep.shards]
    assert len(set(cmds)) == len(cmds), "shards must not repeat the same suite"


def test_every_test_file_is_covered_across_shards(tmp_path):
    o = _orch(tmp_path)
    rep = o.run({"task": "run tests", "shards": 3, "target": TARGET})
    expected = set(o._discover_test_files(TARGET))
    seen = {f for s in rep.shards for f in expected if f in s.command}
    assert seen == expected, f"missed {expected - seen}"


def test_shard_paths_are_quoted(tmp_path):
    """Paths reach a shell; a target with a space must not split the command."""
    o = _orch(tmp_path)
    cmd = o._shard_command("t", [], "some dir", 0, 1, own=["a b.py", "c.py"])
    assert "'a b.py'" in cmd or '"a b.py"' in cmd


def test_empty_shards_are_skipped_not_run(tmp_path):
    o = _orch(tmp_path)
    n = len(o._discover_test_files(TARGET)) + 2      # guarantee empties
    rep = o.run({"task": "run tests", "shards": n, "target": TARGET})
    empties = [e for e in o.events if e["kind"] == "shard_empty"]
    assert empties, "a shard with no files must be skipped, not given the suite"
    assert len(rep.shards) + len(empties) == n


# -- the plan actually decides something -------------------------------------

def test_a_glob_plan_triggers_discovery_and_says_so(tmp_path, monkeypatch):
    from nge import planner
    o = _orch(tmp_path)
    monkeypatch.setattr(planner, "plan", lambda *a, **k: planner.PlanResult(
        names=["glob", "bash"], source="stub"))
    o.run({"task": "t", "shards": 2, "target": TARGET})
    d = [e for e in o.events if e["kind"] == "plan_decision"]
    assert d and d[0]["decision"] == "discover_test_files"
    assert "glob" in d[0]["because"]


def test_a_plain_plan_records_the_split_without_a_plan_decision(tmp_path, monkeypatch):
    from nge import planner
    o = _orch(tmp_path)
    monkeypatch.setattr(planner, "plan", lambda *a, **k: planner.PlanResult(
        names=["bash"], source="stub"))
    o.run({"task": "t", "shards": 2, "target": TARGET})
    assert not [e for e in o.events if e["kind"] == "plan_decision"]
    assert [e for e in o.events if e["kind"] == "shard_split"]


# -- pytest flags the sandbox cannot honour ---------------------------------

def test_unknown_pytest_flags_are_detected(tmp_path):
    o = _orch(tmp_path)
    f = o._unknown_pytest_flags
    # core options the bare image really does support
    assert f("python -m pytest a.py -q -p no:cacheprovider") == set()
    assert f("pytest a.py -v --tb=short --junitxml=j.xml -k smoke") == set()
    assert f("pip install -q -r r.txt && pytest a.py -q") == set()
    # plugin-only and invented options
    assert f("pytest a.py --html=r.html --self-contained-html") == {
        "--html", "--self-contained-html"}
    assert f("pytest a.py --gpu -v") == {"--gpu"}
    assert f("pytest a.py -n 4") == {"-n"}            # xdist, not installed


def test_pip_flags_are_not_mistaken_for_pytest_flags(tmp_path):
    """Only the pytest segment is inspected; `pip install -q -r x` is fine."""
    assert _orch(tmp_path)._unknown_pytest_flags(
        "pip install -q -r req.txt --no-cache-dir && pytest a.py -q") == set()


def test_a_command_with_plugin_flags_falls_back(tmp_path):
    """Live regression: `--html=report.html --self-contained-html` made pytest
    exit 4 - unrecognised argument, nothing run, shard lost."""
    def chat_fn(messages, model=None, tools=None):
        import re as _re
        own = _re.findall(r"packages/nodus/tests/[\w./-]+\.py",
                          messages[-1]["content"])
        return {"role": "assistant",
                "content": f"pytest {' '.join(own)} -v --html=r.html"}

    o = _orch(tmp_path, chat_fn=chat_fn)
    rep = o.run({"task": "t", "shards": 2, "target": TARGET})
    assert [e for e in o.events if e["kind"] == "slotfill_bad_flags"]
    assert not any("--html" in s.command for s in rep.shards)
