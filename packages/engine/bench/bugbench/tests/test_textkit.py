from textkit import slugify, truncate


def test_slug_collapses_punctuation_and_spaces():
    assert slugify("  Hello,  World! ") == "hello-world"


def test_slug_of_a_slug_is_unchanged():
    assert slugify("already-a-slug-2") == "already-a-slug-2"


def test_short_text_is_not_truncated():
    assert truncate("abc", 5) == "abc"


def test_long_text_is_cut_with_an_ellipsis():
    assert truncate("abcdef", 3) == "abc…"
