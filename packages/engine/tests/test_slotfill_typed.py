"""NGE_SLOTFILL=schema: the model picks typed options, the engine writes the command."""
import json

import pytest

from nge import config as _cfg
from nge.orchestrator import NgeOrchestrator

OWN = ["pkg/tests/test_a.py", "pkg/tests/test_b.py"]


def _orch(tmp_path, reply, seen=None):
    def chat_fn(messages, mdl=None, tools=None, max_tokens=None, thinking=None,
                response_format=None):
        if seen is not None:
            seen.append({"response_format": response_format, "prompt": messages[0]["content"]})
        return {"content": reply}
    return NgeOrchestrator(config=_cfg.load(fleet_mode="mock", sandbox_mode="mock",
                                            out_dir=tmp_path), chat_fn=chat_fn)


@pytest.fixture
def typed(monkeypatch):
    monkeypatch.setenv("NGE_SLOTFILL", "schema")


def test_the_engine_writes_the_command_from_typed_options(tmp_path, typed):
    seen = []
    o = _orch(tmp_path, json.dumps({"verbosity": "-v", "traceback": "line", "junitxml": True}),
              seen)
    cmd = o._shard_command("run tests", ["bash"], "pkg/tests", 0, 2, OWN)
    assert cmd == ("pip install -q pytest && python -m pytest pkg/tests/test_a.py "
                   "pkg/tests/test_b.py -v --tb=line --junitxml=report.xml -p no:cacheprovider")
    rf = seen[0]["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"]["properties"]["verbosity"]["enum"] == ["-q", "-v"]
    assert [e for e in o.events if e["kind"] == "slotfill_typed"]


def test_a_reply_outside_the_schema_is_reported_and_replaced(tmp_path, typed):
    o = _orch(tmp_path, json.dumps({"verbosity": "-x", "traceback": "full", "junitxml": None}))
    cmd = o._shard_command("run tests", ["bash"], "pkg/tests", 0, 2, OWN)
    assert cmd.startswith("NGE_SHARD=0/2 ") and "-x" not in cmd
    assert [e for e in o.events if e["kind"] == "slotfill_schema_violated"]


def test_a_chat_fn_without_schema_support_is_not_silently_read_as_text(tmp_path, typed):
    def old_chat_fn(messages, mdl=None, tools=None, max_tokens=None, thinking=None):
        return {"content": "pytest pkg -x"}
    o = NgeOrchestrator(config=_cfg.load(fleet_mode="mock", sandbox_mode="mock",
                                         out_dir=tmp_path), chat_fn=old_chat_fn)
    cmd = o._shard_command("run tests", ["bash"], "pkg/tests", 0, 2, OWN)
    assert cmd.startswith("NGE_SHARD=0/2 ")
    (err,) = [e for e in o.events if e["kind"] == "slotfill_error"]
    assert "response_format" in err["error"]


def test_free_text_stays_the_default(tmp_path, monkeypatch):
    monkeypatch.delenv("NGE_SLOTFILL", raising=False)
    seen = []
    o = _orch(tmp_path, "pip install -q pytest && python -m pytest pkg/tests/test_a.py "
                        "pkg/tests/test_b.py -q --tb=short", seen)
    o._shard_command("run tests", ["bash"], "pkg/tests", 0, 2, OWN)
    assert seen[0]["response_format"] is None
