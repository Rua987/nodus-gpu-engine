"""Reasoning on/off per call class, and a budget spent on reasoning is named.

Live, Nemotron 3 Super spent the whole slot-fill ceiling (256/256) on
reasoning and returned an empty reply on every call; the run logged it as
``slotfill_empty`` and the taxonomy counted it as an argument problem.
"""
import json

import pytest

from nge import config as _cfg
from nge.backends import nebius
from nge.backends import usage as _usage
from nge.orchestrator import NgeOrchestrator


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload
        self.text = json.dumps(payload)

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _post_capturing(captured, content="ok", finish="stop", reasoning=None):
    import requests as real

    def post(url, json=None, headers=None, timeout=None):
        captured["payload"] = json
        usage = {"prompt_tokens": 10, "completion_tokens": 20}
        if reasoning is not None:
            usage["completion_tokens_details"] = {"reasoning_tokens": reasoning}
        return _Resp({"choices": [{"message": {"role": "assistant", "content": content},
                                   "finish_reason": finish}],
                      "usage": usage})
    return type("R", (), {"post": staticmethod(post),
                          "RequestException": real.RequestException})()


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "sk-x")
    _usage.reset_usage()


# -- backend ------------------------------------------------------------------

def test_no_thinking_sends_no_template_kwargs(monkeypatch, key):
    cap = {}
    monkeypatch.setattr(nebius, "requests", _post_capturing(cap))
    nebius.chat_nebius([{"role": "user", "content": "hi"}], "nebius:m")
    assert "chat_template_kwargs" not in cap["payload"]


@pytest.mark.parametrize("flag", [True, False])
def test_thinking_is_sent_as_template_switch(monkeypatch, key, flag):
    cap = {}
    monkeypatch.setattr(nebius, "requests", _post_capturing(cap))
    nebius.chat_nebius([{"role": "user", "content": "hi"}], "nebius:m",
                       thinking=flag)
    assert cap["payload"]["chat_template_kwargs"] == {"enable_thinking": flag}


def test_reasoning_tokens_reach_message_and_ledger(monkeypatch, key):
    monkeypatch.setattr(nebius, "requests",
                        _post_capturing({}, content="", finish="length",
                                        reasoning=256))
    msg = nebius.chat_nebius([{"role": "user", "content": "hi"}], "nebius:m",
                             max_tokens=256)
    assert msg["reasoning_tokens"] == 256
    assert msg["finish_reason"] == "length"
    assert _usage.snapshot()["m"]["reasoning_tokens"] == 256
    assert "reasoning=256" in _usage.format_summary()


@pytest.mark.parametrize("raw,want", [("off", False), ("0", False),
                                      ("on", True), ("1", True), ("", None),
                                      ("junk", None), ("model", None)])
def test_resolve_thinking_env(monkeypatch, raw, want):
    monkeypatch.setattr(nebius, "THINKING_DEFAULTS", {"short": None, "patch": None})
    monkeypatch.setenv("NGE_THINKING_SHORT", raw)
    assert nebius.resolve_thinking("short") is want


def test_resolve_thinking_env_beats_default(monkeypatch):
    monkeypatch.setattr(nebius, "THINKING_DEFAULTS", {"short": False, "patch": True})
    monkeypatch.delenv("NGE_THINKING_SHORT", raising=False)
    monkeypatch.setenv("NGE_THINKING_PATCH", "off")
    assert nebius.resolve_thinking("short") is False
    assert nebius.resolve_thinking("patch") is False


# -- orchestrator -------------------------------------------------------------

def _orch(tmp_path, chat_fn):
    return NgeOrchestrator(config=_cfg.load(fleet_mode="mock", sandbox_mode="mock",
                                            out_dir=tmp_path), chat_fn=chat_fn)


def test_budget_spent_slotfill_is_truncated_not_empty(tmp_path):
    def chat_fn(messages, model=None, tools=None, max_tokens=None):
        return {"content": "", "finish_reason": "length", "reasoning_tokens": 256}
    o = _orch(tmp_path, chat_fn)
    o._shard_command("run tests", ["bash"], "packages/nodus/tests", 0, 1,
                     own=["packages/nodus/tests/test_a.py"])
    kinds = [e["kind"] for e in o.events]
    assert "slotfill_truncated" in kinds and "slotfill_empty" not in kinds
    ev = next(e for e in o.events if e["kind"] == "slotfill_truncated")
    assert ev["reasoning_tokens"] == 256


def test_really_empty_slotfill_stays_empty(tmp_path):
    o = _orch(tmp_path, lambda m, model=None, tools=None, max_tokens=None:
              {"content": "", "finish_reason": "stop"})
    o._shard_command("run tests", ["bash"], "packages/nodus/tests", 0, 1)
    assert "slotfill_empty" in [e["kind"] for e in o.events]


def test_patch_truncated_says_reasoning_ate_the_budget(tmp_path):
    o = _orch(tmp_path, lambda m, model=None, tools=None, max_tokens=None:
              {"content": "", "finish_reason": "length", "reasoning_tokens": 2048})
    assert o._propose_patch({"test": "t.py::test_a", "error": "e"}, "m") is None
    ev = next(e for e in o.events if e["kind"] == "patch_truncated")
    assert ev["why"] == "reasoning used the whole budget"
    assert ev["reasoning_tokens"] == 2048


@pytest.mark.parametrize("cls,env", [("short", "NGE_THINKING_SHORT"),
                                     ("patch", "NGE_THINKING_PATCH")])
def test_call_class_setting_reaches_chat_fn(tmp_path, monkeypatch, cls, env):
    monkeypatch.setenv(env, "off")
    seen = []

    def chat_fn(messages, model=None, tools=None, max_tokens=None, thinking=None):
        seen.append((max_tokens, thinking))
        return {"content": "", "finish_reason": "stop"}

    o = _orch(tmp_path, chat_fn)
    if cls == "short":
        o._shard_command("run tests", ["bash"], "packages/nodus/tests", 0, 1)
        assert seen[0] == (nebius.SLOT_MAX_TOKENS, False)
    else:
        o.RETRY_DELAY_S = 0
        o._propose_patch({"test": "t.py::test_a", "error": "e"}, "m")
        assert seen[0] == (nebius.resolve_patch_max_tokens(), False)


def test_chat_fn_without_thinking_keeps_max_tokens(tmp_path, monkeypatch):
    """An older chat_fn must not silently lose its token ceiling."""
    monkeypatch.setenv("NGE_THINKING_SHORT", "off")
    seen = []

    def chat_fn(messages, model=None, tools=None, max_tokens=None):
        seen.append(max_tokens)
        return {"content": "", "finish_reason": "stop"}

    o = _orch(tmp_path, chat_fn)
    o._shard_command("run tests", ["bash"], "packages/nodus/tests", 0, 1)
    assert seen == [nebius.SLOT_MAX_TOKENS]


def test_plan_fallback_passes_short_class(monkeypatch):
    monkeypatch.setenv("NGE_THINKING_SHORT", "off")
    seen = []

    def fake(messages, model, tools=None, max_tokens=None, thinking=None):
        seen.append((max_tokens, thinking))
        return {"content": '["bash"]'}

    monkeypatch.setattr(nebius, "chat_nebius", fake)
    assert nebius.nemotron_plan_fallback("t", ["bash"]) == ["bash"]
    assert seen == [(nebius.SLOT_MAX_TOKENS, False)]


def test_mission_parse_passes_short_class(monkeypatch):
    from nge.mission import parse_mission_llm
    monkeypatch.setenv("NGE_THINKING_SHORT", "off")
    seen = []

    def chat_fn(messages, model, tools, max_tokens=None, thinking=None):
        seen.append((max_tokens, thinking))
        return {"content": '{"shards": 2}'}

    m = parse_mission_llm("run the suite on 2 GPUs", chat_fn, "nebius:m")
    assert seen == [(nebius.SLOT_MAX_TOKENS, False)]
    assert m.shards == 2


# -- what a reader sees ---------------------------------------------------------

def test_report_names_reasoning_as_the_budget_sink(tmp_path):
    from nge import report_html
    test = "pkg/tests/t.py::test_x"
    rep = {
        "plan": {"names": ["bash", "edit_file"], "source": "heuristic"},
        "shards": [{"index": 0, "node_id": "nb-h100-00", "exit_code": 1,
                    "duration_s": 1.0, "failures": [{}], "migrated_from": None}],
        "failures": [{"test": test, "error": "boom", "proposed_fix": "x"}],
        "routes": [], "remediations": [],
        "events": [
            {"kind": "slotfill_truncated", "shard": 0, "max_tokens": 256,
             "reasoning_tokens": 256},
            {"kind": "patch_truncated", "test": test, "max_tokens": 2048,
             "reply_chars": 0, "reasoning_tokens": 2048},
        ],
        "fixes": [{"test": test, "patch": None, "verified": False}],
    }
    doc = report_html.render(rep, tmp_path / "r.html").read_text(encoding="utf-8")
    assert "slot-fill shard 0 cut at 256 tokens (256 reasoning)" in doc
    assert "2048 spent reasoning" in doc


# -- a working slot-fill must not shrink the run --------------------------------

LIVE_X = ("pip install -q -r packages/nodus/requirements-ci.txt && "
          "PYTHONPATH=packages/nodus pytest -q -v -x {files}")


@pytest.mark.parametrize("flags", ["-x", "--exitfirst", "--maxfail=1", "-k foo",
                                   "-m slow", "--lf", "--deselect a.py::t",
                                   "--pdb"])
def test_slotfill_that_narrows_the_run_falls_back(tmp_path, flags):
    """Live: Nemotron added -x on every shard; 2 failures seen instead of 5,
    and verification then blamed patches for the 3 that -x hid."""
    own = ["packages/nodus/tests/test_a.py", "packages/nodus/tests/test_b.py"]
    cmd = f"pytest -q {flags} {' '.join(own)}"
    o = _orch(tmp_path, lambda m, model=None, tools=None, max_tokens=None:
              {"content": cmd})
    got = o._shard_command("run tests", ["bash"], "packages/nodus/tests", 0, 2,
                           own=own)
    assert got != cmd
    ev = next(e for e in o.events if e["kind"] == "slotfill_narrowed")
    assert ev["flags"]


def test_live_x_command_is_refused(tmp_path):
    own = ["packages/nodus/tests/test_a.py"]
    cmd = LIVE_X.format(files=" ".join(own))
    o = _orch(tmp_path, lambda m, model=None, tools=None, max_tokens=None:
              {"content": cmd})
    assert o._shard_command("t", ["bash"], "packages/nodus/tests", 0, 1, own=own) != cmd
    assert [e["flags"] for e in o.events if e["kind"] == "slotfill_narrowed"] == [["-x"]]


def test_reporting_options_are_still_free(tmp_path):
    own = ["packages/nodus/tests/test_a.py"]
    cmd = f"pytest -q -v --tb=short {own[0]}"
    o = _orch(tmp_path, lambda m, model=None, tools=None, max_tokens=None:
              {"content": cmd})
    assert o._shard_command("t", ["bash"], "packages/nodus/tests", 0, 1, own=own) == cmd


def test_prompt_no_longer_offers_narrowing_options(tmp_path):
    seen = []

    def chat_fn(messages, model=None, tools=None, max_tokens=None):
        seen.append(messages[-1]["content"])
        return {"content": ""}
    _orch(tmp_path, chat_fn)._shard_command("t", ["bash"], "x", 0, 1)
    assert "-x -k -m" not in seen[0] and "no -x" in seen[0]


def test_python_dash_m_is_not_pytest_dash_m(tmp_path):
    own = ["packages/nodus/tests/test_a.py"]
    o = _orch(tmp_path, lambda *a, **k: {"content": ""})
    assert o._narrowing_pytest_flags(f"python -m pytest -q {own[0]}") == set()
    assert o._narrowing_pytest_flags(f"python -m pytest -q -m slow {own[0]}") == {"-m"}
    assert o._narrowing_pytest_flags("PYTHONPATH=x .venv/bin/pytest -x a.py") == {"-x"}


def test_measured_defaults():
    """Short replies without reasoning, patches with it and room for it."""
    assert nebius.THINKING_DEFAULTS == {"short": False, "patch": True}
    assert nebius.PATCH_MAX_TOKENS == 8192


def test_model_keyword_sends_nothing_even_over_a_default(monkeypatch):
    monkeypatch.setenv("NGE_THINKING_PATCH", "model")
    assert nebius.resolve_thinking("patch") is None


# -- a known option with an unusable value is refused too ------------------------

@pytest.mark.parametrize("opt", ["--tb=", "--junitxml=", "--tb=verbose", "--tb"])
def test_option_without_a_usable_value_falls_back(tmp_path, opt):
    """Live: the model copied the prompt's placeholder `--tb=`; pytest exited 4
    on that shard and ran nothing."""
    own = ["packages/nodus/tests/test_a.py"]
    cmd = f"pytest {own[0]} -q -v {opt}"
    o = _orch(tmp_path, lambda m, model=None, tools=None, max_tokens=None:
              {"content": cmd})
    assert o._shard_command("t", ["bash"], "packages/nodus/tests", 0, 1, own=own) != cmd
    assert [e for e in o.events if e["kind"] == "slotfill_bad_flags"]


@pytest.mark.parametrize("opt", ["--tb=short", "--tb short", "--tb=no",
                                 "--junitxml=report.xml"])
def test_option_with_a_usable_value_is_kept(tmp_path, opt):
    own = ["packages/nodus/tests/test_a.py"]
    cmd = f"pytest -q {opt} {own[0]}"
    o = _orch(tmp_path, lambda m, model=None, tools=None, max_tokens=None:
              {"content": cmd})
    assert o._shard_command("t", ["bash"], "packages/nodus/tests", 0, 1, own=own) == cmd


def test_prompt_shows_values_not_placeholders(tmp_path):
    seen = []

    def chat_fn(messages, model=None, tools=None, max_tokens=None):
        seen.append(messages[-1]["content"])
        return {"content": ""}
    _orch(tmp_path, chat_fn)._shard_command("t", ["bash"], "x", 0, 1)
    assert "--tb=short" in seen[0] and "--tb= " not in seen[0]
