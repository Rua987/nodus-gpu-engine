"""Static resolution of the code a failing test exercises.

The fix agent kept patching modules it had never read: for nodus_tools.py it
quoted two lines that exist nowhere in the file, because the traceback names
only the test file. This walks imports statically to find the real thing.
"""
from pathlib import Path

import pytest

from nge import symbols

REPO = Path(__file__).resolve().parents[3]
NODUS = REPO / "packages/nodus"
TEST_FILE = NODUS / "tests/test_nodus_tools.py"


def _src(tmp_path, name, body):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


# -- pieces ------------------------------------------------------------------

def test_import_map_handles_both_forms(tmp_path):
    import ast
    tree = ast.parse("import os\nfrom a.b import c, d as e\nimport x.y as z\n")
    m = symbols.import_map(tree)
    assert m["os"] == "os" and m["c"] == "a.b" and m["e"] == "a.b"
    assert m["z"] == "x.y"


def test_called_names_finds_plain_and_attribute_calls(tmp_path):
    import ast
    tree = ast.parse("def t():\n    foo(1)\n    mod.bar(2)\n    _priv()\n")
    fn = tree.body[0]
    names = symbols.called_names(fn)
    assert "foo" in names and "bar" in names
    assert "_priv" not in names, "dunder/private helpers are noise"


def test_definition_span_covers_the_body(tmp_path):
    import ast
    tree = ast.parse("def a():\n    pass\n\ndef b():\n    x = 1\n    return x\n")
    start, end = symbols.definition(tree, "b")
    assert start == 4 and end >= 6


def test_module_file_resolves_package_and_module(tmp_path):
    _src(tmp_path, "pkg/__init__.py", "")
    _src(tmp_path, "pkg/mod.py", "x = 1\n")
    assert symbols.module_file("pkg.mod", [tmp_path]).name == "mod.py"
    assert symbols.module_file("pkg", [tmp_path]).name == "__init__.py"
    assert symbols.module_file("nope", [tmp_path]) is None


# -- end to end --------------------------------------------------------------

def test_resolves_a_synthetic_case(tmp_path):
    _src(tmp_path, "mylib.py", "def helper(a):\n    return a + 1\n")
    t = _src(tmp_path, "test_it.py",
             "from mylib import helper\n\n"
             "def test_helper():\n    assert helper(1) == 2\n")
    got = symbols.sources_under_test(t, "test_helper", tmp_path, [tmp_path])
    assert len(got) == 1
    rel, line, body = got[0]
    assert rel == "mylib.py" and line == 1
    assert "def helper(a):" in body and "return a + 1" in body


def test_resolves_a_method_inside_a_class(tmp_path):
    _src(tmp_path, "mylib.py", "def helper(a):\n    return a\n")
    t = _src(tmp_path, "test_it.py",
             "from mylib import helper\n\n"
             "class TestX:\n    def test_m(self):\n        assert helper(1)\n")
    got = symbols.sources_under_test(t, "test_m", tmp_path, [tmp_path])
    assert got and got[0][0] == "mylib.py"


@pytest.mark.skipif(not TEST_FILE.is_file(), reason="vendored suite absent")
def test_resolves_the_real_case_that_was_being_invented():
    """`repair_llm_file_path` lives at line 1200 of nodus_tools.py; the model
    had been writing a five-line function of its own devising."""
    got = symbols.sources_under_test(
        TEST_FILE, "test_drive_underscore_prefix", REPO, [NODUS, REPO])
    assert got, "the symbol under test must be resolvable"
    rel, line, body = got[0]
    assert rel == "packages/nodus/nodus_tools.py"
    assert line > 1000, "the real definition is deep in the file"
    assert "def repair_llm_file_path" in body


def test_unresolvable_inputs_yield_nothing(tmp_path):
    t = _src(tmp_path, "test_it.py", "def test_a():\n    assert 1\n")
    assert symbols.sources_under_test(t, "test_a", tmp_path, [tmp_path]) == []
    assert symbols.sources_under_test(t, "nope", tmp_path, [tmp_path]) == []
    assert symbols.sources_under_test(tmp_path / "gone.py", "t", tmp_path, []) == []


def test_a_syntax_error_does_not_raise(tmp_path):
    t = _src(tmp_path, "bad.py", "def (:\n")
    assert symbols.sources_under_test(t, "t", tmp_path, [tmp_path]) == []


def test_third_party_imports_are_skipped(tmp_path):
    t = _src(tmp_path, "test_it.py",
             "import json\n\ndef test_a():\n    json.dumps({})\n")
    assert symbols.sources_under_test(t, "test_a", tmp_path, [tmp_path]) == []


def test_output_is_capped(tmp_path):
    big = "def helper(a):\n" + "".join(f"    x{i} = {i}\n" for i in range(400))
    _src(tmp_path, "mylib.py", big)
    t = _src(tmp_path, "test_it.py",
             "from mylib import helper\n\ndef test_a():\n    helper(1)\n")
    got = symbols.sources_under_test(t, "test_a", tmp_path, [tmp_path])
    assert len(got[0][2].splitlines()) <= symbols.MAX_LINES_PER_SYMBOL


def test_render_is_empty_for_nothing():
    assert symbols.render([]) == ""
    assert "code under test" in symbols.render([("a.py", 3, " 3| x")])
