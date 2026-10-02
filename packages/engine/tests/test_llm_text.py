"""Extraction of commands / diffs from free-form LLM output.

Regressions: an empty reply used to raise IndexError and kill the run, and a
fenced reply produced the literal command '```bash'.
"""
import pytest
from nge import llm_text as lt


# -- content_of --------------------------------------------------------------

def test_content_of_handles_every_empty_shape():
    for msg in [None, {}, {"content": None}, {"foo": "bar"}, 42, []]:
        assert lt.content_of(msg) == ""


def test_content_of_accepts_str_and_nested_message():
    assert lt.content_of("hi") == "hi"
    assert lt.content_of({"content": "hi"}) == "hi"
    assert lt.content_of({"message": {"content": "nested"}}) == "nested"


# -- first_command -----------------------------------------------------------

def test_first_command_returns_none_rather_than_raising():
    for msg in [None, {}, {"content": ""}, {"content": "   \n\n "}]:
        assert lt.first_command(msg) is None


def test_first_command_unwraps_fences():
    assert lt.first_command({"content": "```bash\npytest -q\n```"}) == "pytest -q"
    assert lt.first_command({"content": "```\npytest -x\n```"}) == "pytest -x"
    assert lt.first_command({"content": "```sh\npytest -v\n```"}) == "pytest -v"


def test_first_command_tolerates_an_unclosed_fence():
    assert lt.first_command({"content": "```bash\npytest -k a"}) == "pytest -k a"


def test_first_command_ignores_prose_around_the_block():
    msg = {"content": "Sure!\n```sh\npytest -v\n```\nHope that helps"}
    assert lt.first_command(msg) == "pytest -v"


def test_first_command_strips_a_shell_prompt():
    assert lt.first_command({"content": "$ pytest --tb=short"}) == "pytest --tb=short"
    assert lt.first_command({"content": "```\n$ pytest -q\n```"}) == "pytest -q"


def test_first_command_skips_comment_lines():
    assert lt.first_command({"content": "# run it\npytest -q"}) == "pytest -q"


def test_first_command_plain_text():
    assert lt.first_command({"content": "pytest -q\nignored"}) == "pytest -q"


# -- unified_diff ------------------------------------------------------------

DIFF = "--- a/x.py\n+++ b/x.py\n@@\n-a\n+b"
# unified_diff() normalises on the way out: a bare `@@` gets counts (and a
# placeholder position that _relocate_hunks later corrects), and the stream
# gets its trailing newline. patch-ng refuses it without either - a bare header
# is rejected as "invalid patch with no hunks".
DIFF_OUT = "--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,1 @@\n-a\n+b\n"


def test_unified_diff_none_when_absent():
    for msg in [None, {"content": ""}, {"content": "I cannot fix this."}]:
        assert lt.unified_diff(msg) is None


def test_unified_diff_from_diff_fence():
    assert lt.unified_diff({"content": f"```diff\n{DIFF}\n```"}) == DIFF_OUT


def test_unified_diff_from_a_mislabelled_fence():
    """Models routinely tag a diff as ```python - the old parser dropped it."""
    assert lt.unified_diff({"content": f"```python\n{DIFF}\n```"}) == DIFF_OUT
    assert lt.unified_diff({"content": f"```\n{DIFF}\n```"}) == DIFF_OUT


def test_unified_diff_from_bare_prose():
    msg = {"content": f"Here is the fix:\ndiff --git a/x b/x\n{DIFF}"}
    got = lt.unified_diff(msg)
    # git's envelope is dropped: patch-ng strips the a/ prefix itself when it
    # sees `diff --git`, so our fixed --strip 1 would remove one component too
    # many and report the file missing
    assert not got.startswith("diff --git")
    assert got.startswith("--- a/x.py") and "+b" in got


def test_unified_diff_ignores_a_non_diff_fence():
    assert lt.unified_diff({"content": "```python\nprint(1)\n```"}) is None


def test_fenced_blocks_returns_bodies_in_order():
    text = "```a\none\n```\nmid\n```b\ntwo\n```"
    assert lt.fenced_blocks(text) == ["one\n", "two\n"]


# -- bare @@ headers (what models actually write) ----------------------------

def test_a_bare_hunk_header_gets_counts():
    """`@@` with no numbers reads like a diff but patch-ng refuses the file
    outright: "skipping invalid patch with no hunks"."""
    d = "--- a/x.py\n+++ b/x.py\n@@\n keep\n-old\n+new\n"
    out = lt.normalize_hunks(d)
    assert out.splitlines()[2] == "@@ -1,2 +1,2 @@"


def test_a_numbered_header_keeps_its_position():
    d = "--- a/x.py\n+++ b/x.py\n@@ -35,7 +35,7 @@\n keep\n-old\n+new\n"
    assert lt.normalize_hunks(d).splitlines()[2] == "@@ -35,2 +35,2 @@"


def test_the_hunk_trailer_is_preserved():
    d = "--- a/x.py\n+++ b/x.py\n@@ -1,9 +1,9 @@ def f(self):\n a\n-b\n+c\n"
    assert lt.normalize_hunks(d).splitlines()[2] == "@@ -1,2 +1,2 @@ def f(self):"


def test_several_hunks_are_each_counted():
    d = ("--- a/x.py\n+++ b/x.py\n"
         "@@\n a\n-b\n+c\n"
         "@@ -50,9 +50,9 @@\n d\n e\n-f\n+g\n")
    hdrs = [l for l in lt.normalize_hunks(d).splitlines() if l.startswith("@@")]
    assert hdrs == ["@@ -1,2 +1,2 @@", "@@ -50,3 +50,3 @@"]


def test_normalized_output_is_accepted_by_patch_ng():
    import tempfile, pathlib
    patch_ng = pytest.importorskip("patch_ng")
    d = "--- a/x.py\n+++ b/x.py\n@@\n keep\n-old\n+new\n"
    p = pathlib.Path(tempfile.mkdtemp()) / "f.patch"
    p.write_text(lt.normalize_hunks(d), encoding="utf-8")
    assert patch_ng.fromfile(str(p)), "bare @@ must survive normalisation"


def test_git_envelope_is_dropped():
    """patch-ng strips the a/ prefix itself for a `diff --git` patch, so a
    fixed --strip 1 then removes one component too many:
        source/target file does not exist: --- b'nodus/nodus_tools.py'
    Live, this rejected a patch that was otherwise correct."""
    d = ("diff --git a/pkg/mod.py b/pkg/mod.py\n"
         "index 1234567..89abcde 100644\n"
         "--- a/pkg/mod.py\n+++ b/pkg/mod.py\n@@\n a\n-b\n+c\n")
    out = lt.normalize_hunks(d)
    assert "diff --git" not in out and "index " not in out
    assert out.startswith("--- a/pkg/mod.py")


def test_strip_depth_is_stable_for_patch_ng():
    patch_ng = pytest.importorskip("patch_ng")
    import tempfile, pathlib
    for head in ("", "diff --git a/pkg/mod.py b/pkg/mod.py\n"):
        d = head + "--- a/pkg/mod.py\n+++ b/pkg/mod.py\n@@\n a\n-b\n+c\n"
        p = pathlib.Path(tempfile.mkdtemp()) / "f.patch"
        p.write_text(lt.normalize_hunks(d), encoding="utf-8")
        parsed = patch_ng.fromfile(str(p))
        assert parsed, head
        assert parsed.items[0].source.decode() == "a/pkg/mod.py", head


# -- shapes that silently lost a patch ---------------------------------------

BODY = "@@ -1,2 +1,2 @@\n keep\n-old\n+new\n"


def test_a_fully_indented_block_is_still_a_diff():
    """Some replies indent the whole block; `---` then no longer starts the
    line and the patch was lost as "no diff"."""
    ind = ("```diff\n    --- a/x.py\n    +++ b/x.py\n"
           "    @@ -1,2 +1,2 @@\n     keep\n    -old\n    +new\n```")
    got = lt.unified_diff({"content": ind})
    assert got is not None
    assert got.startswith("--- a/x.py")
    # the diff's own column-0 markers must survive
    assert "\n keep\n" in got and "\n-old\n" in got and "\n+new\n" in got


def test_dedent_never_touches_a_ragged_block():
    """Only a prefix shared by every line is removed - per-line stripping
    would destroy the ' ' / '-' / '+' column that carries the meaning."""
    d = "--- a/x.py\n+++ b/x.py\n" + BODY
    assert lt._dedent(d) == d


def test_hunks_without_a_file_header_are_identified():
    """Recoverable? No - nothing says which file to patch, and guessing would
    apply the diff to the wrong one. Reported so the run says why."""
    assert lt.has_hunks_without_header(f"```diff\n{BODY}```")
    assert lt.has_hunks_without_header(BODY)
    assert not lt.has_hunks_without_header(f"```diff\n--- a/x.py\n+++ b/x.py\n{BODY}```")
    assert not lt.has_hunks_without_header("I cannot fix this.")
    assert not lt.has_hunks_without_header("")


# -- json_array --------------------------------------------------------------

def test_json_array_handles_the_shapes_models_use():
    assert lt.json_array({"content": '["a", "b"]'}) == ["a", "b"]
    assert lt.json_array({"content": '```json\n["a"]\n```'}) == ["a"]
    assert lt.json_array({"content": '```\n["a"]\n```'}) == ["a"]
    assert lt.json_array({"content": 'Plan:\n["a", "b"]\nDone.'}) == ["a", "b"]


def test_json_array_is_total():
    for msg in [None, {}, {"content": ""}, {"content": "no array"},
                {"content": "["}, {"content": '{"a": 1}'}, 42]:
        assert lt.json_array(msg) is None


def test_json_array_respects_strings_and_nesting():
    assert lt.json_array({"content": '["a]b", "c"]'}) == ["a]b", "c"]
    assert lt.json_array({"content": '[["x"], ["y"]]'}) == [["x"], ["y"]]


# -- headers with the `--- `/`+++ ` dropped (Nemotron, reasoning off) -------
# Both shapes verbatim from live replies, 2026-10-01: 6/6 diffs in that arm
# were lost as "no diff in the reply".

_TWO_LINE = ("```diff\na/packages/nodus/nodus_tools.py\nb/packages/nodus/nodus_tools.py\n"
             "@@\n     s = _collapse_doubled_first_segment(s)\n-    old()\n+    new()\n```")
_ONE_LINE = ("```diff\na/packages/nodus/nodus_tools.py b/packages/nodus/nodus_tools.py\n"
             "@@\n     s = _collapse_doubled_first_segment(s)\n-    old()\n+    new()\n```")


@pytest.mark.parametrize("reply", [_TWO_LINE, _ONE_LINE])
def test_bare_file_header_is_restored(reply):
    d = lt.unified_diff({"content": reply})
    assert d is not None
    assert d.startswith("--- a/packages/nodus/nodus_tools.py\n"
                        "+++ b/packages/nodus/nodus_tools.py\n@@ -1,2 +1,2 @@")
    assert "+    new()" in d


def test_bare_header_restored_for_every_file():
    reply = ("```diff\na/x.py\nb/x.py\n@@\n-a\n+b\n"
             "a/y.py\nb/y.py\n@@\n-c\n+d\n```")
    d = lt.unified_diff({"content": reply})
    assert d.count("--- a/") == 2 and "+++ b/y.py" in d


def test_a_slash_line_without_a_hunk_is_not_a_header():
    """Only rewrite when a hunk follows - prose mentioning a/b paths stays prose."""
    reply = "Compare a/x.py\nwith b/x.py\nand tell me."
    assert lt.unified_diff({"content": reply}) is None
    assert lt._restore_bare_headers("a/x.py\nb/x.py\nno hunk") == "a/x.py\nb/x.py\nno hunk"
