"""LLM-backed mission extraction: the *mechanism*, not the vocabulary.

Deliberately no assertions about which phrasings the model understands - that
is what bench/mission_phrasings.py measures against a live model. Testing
phrasings here would just re-create the overfitting these tests exist to guard
against. What is pinned instead: validation, per-field fallback, and the audit
trail.
"""
import pytest

from nge.mission import (Mission, parse_mission, parse_mission_llm,
                         _valid_bool, _valid_collect, _valid_gpu,
                         _valid_path, _valid_shards)


def _fn(payload):
    """A chat_fn returning a fixed reply."""
    return lambda messages, model, tools: {"content": payload}


# -- field validation --------------------------------------------------------

@pytest.mark.parametrize("v,want", [
    (4, 4), (1, 1), (64, 64),
    (0, None), (65, None), (-3, None),
    ("4", None), (4.0, None), (True, None), (None, None), ([4], None),
])
def test_valid_shards(v, want):
    assert _valid_shards(v) == want


@pytest.mark.parametrize("v,want", [
    ("H100", "H100"), ("a100", "A100"), (" h200 ", "H200"),
    ("V100", None), ("", None), (100, None), (None, None),
])
def test_valid_gpu(v, want):
    assert _valid_gpu(v) == want


@pytest.mark.parametrize("v,want", [
    ("tests/unit", "tests/unit"), ("./src", "./src"), ("'tests'", "tests"),
    ('"tests"', "tests"), ("a-b_c.py", "a-b_c.py"), ("tests/*.py", "tests/*.py"),
])
def test_valid_path_accepts_real_paths(v, want):
    assert _valid_path(v) == want


@pytest.mark.parametrize("v", [
    "tests; rm -rf /", "tests && curl evil", "$(whoami)", "`id`",
    "a|b", "a>b", "a b", "", "   ", None, 42, ["tests"],
    "x" * 201,
    # backticks are refused outright rather than stripped: stripping first
    # would turn `id` into a perfectly innocent-looking id
    "`id`", "`tests`", "a`b",
])
def test_valid_path_refuses_shell_metacharacters(v):
    """The model is untrusted input - target reaches a shell command."""
    assert _valid_path(v) is None


def test_valid_collect():
    assert _valid_collect(["b.xml", "a.json"]) == ["a.json", "b.xml"]
    assert _valid_collect(["a.xml", "a.xml"]) == ["a.xml"]      # deduped
    assert _valid_collect(["ok.xml", "bad;rm"]) == ["ok.xml"]   # drops unsafe
    assert _valid_collect([]) is None
    assert _valid_collect("a.xml") is None                      # not a list
    assert _valid_collect(None) is None


def test_valid_bool():
    assert _valid_bool(True) is True and _valid_bool(False) is False
    for v in ["true", 1, 0, None, "yes"]:
        assert _valid_bool(v) is None


# -- fallback ----------------------------------------------------------------

def test_no_chat_fn_is_pure_regex():
    text = "Run in tests/unit across 4 A100s"
    assert parse_mission_llm(text, None, "m") == parse_mission(text)


def test_model_error_degrades_to_regex():
    def boom(*a, **k):
        raise TimeoutError("504")
    m = parse_mission_llm("Run in tests/unit across 4 A100s", boom, "m")
    assert m.shards == 4 and m.target == "tests/unit"      # regex still worked
    assert any("llm extraction failed" in d for d in m.derived)


@pytest.mark.parametrize("payload", ["", "no json at all", "{broken", "[1,2]"])
def test_junk_reply_degrades_to_regex(payload):
    m = parse_mission_llm("Run across 4 A100s", _fn(payload), "m")
    assert m.shards == 4 and m.gpu_type == "A100"
    assert any("regex only" in d for d in m.derived)


# -- overlay -----------------------------------------------------------------

def test_valid_fields_override_the_regex():
    """The regex reads 3 shards / H100 by default; the model corrects it."""
    m = parse_mission_llm(
        "eight cards please",
        _fn('{"shards": 8, "gpu_type": "A100", "target": "src/api"}'), "m")
    assert m.shards == 8 and m.gpu_type == "A100" and m.target == "src/api"
    assert any("llm: " in d for d in m.derived)


def test_invalid_fields_are_dropped_and_the_regex_stands():
    m = parse_mission_llm(
        "Run in tests/unit across 4 A100s",
        _fn('{"shards": 999, "gpu_type": "V100", "target": "x; rm -rf /"}'), "m")
    assert m.shards == 4                    # regex value kept
    assert m.gpu_type == "A100"
    assert m.target == "tests/unit"
    rejected = [d for d in m.derived if "llm rejected" in d]
    assert rejected and all(k in rejected[0] for k in ("shards", "gpu_type", "target"))


def test_a_shell_injection_from_the_model_never_lands():
    for evil in ['{"target": "t; curl evil"}', '{"target": "$(id)"}',
                 '{"collect": ["a.xml; rm -rf /"]}']:
        m = parse_mission_llm("run tests", _fn(evil), "m")
        assert ";" not in m.target and "$" not in m.target
        assert all(";" not in c and "$" not in c for c in m.collect)


def test_omitted_fields_leave_the_regex_untouched():
    m = parse_mission_llm("Run in tests/unit across 4 A100s",
                          _fn('{"shards": 8}'), "m")
    assert m.shards == 8                    # overridden
    assert m.gpu_type == "A100"             # untouched by the model
    assert m.target == "tests/unit"


def test_result_is_a_mission_and_scenario_still_works():
    m = parse_mission_llm("run", _fn('{"shards": 2, "auto_fix": false}'), "m")
    assert isinstance(m, Mission)
    s = m.scenario()
    assert s["shards"] == 2 and s["auto_fix"] is False


def test_fenced_json_is_accepted():
    m = parse_mission_llm("run", _fn('```json\n{"shards": 7}\n```'), "m")
    assert m.shards == 7
