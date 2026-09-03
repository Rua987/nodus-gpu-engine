"""Extraction of commands / diffs from free-form LLM output.

Regressions: an empty reply used to raise IndexError and kill the run, and a
fenced reply produced the literal command '```bash'.
"""
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
# A patch stream must end with a newline: patch-ng refuses one that does not
# with "patch stream is incomplete!", so unified_diff() always appends it.
DIFF_OUT = DIFF + "\n"


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
    assert got.startswith("diff --git") and "+b" in got


def test_unified_diff_ignores_a_non_diff_fence():
    assert lt.unified_diff({"content": "```python\nprint(1)\n```"}) is None


def test_fenced_blocks_returns_bodies_in_order():
    text = "```a\none\n```\nmid\n```b\ntwo\n```"
    assert lt.fenced_blocks(text) == ["one\n", "two\n"]
