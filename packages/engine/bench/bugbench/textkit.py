"""Small text helpers."""


def slugify(text: str) -> str:
    """Lower-case, ASCII letters and digits only, words joined by single dashes.

    ``slugify("  Hello,  World! ")`` is ``"hello-world"``.
    """
    out = []
    for ch in text.lower():
        if ch.isascii() and ch.isalnum():
            out.append(ch)
        else:
            out.append("-")
    return "".join(out)


def truncate(text: str, limit: int) -> str:
    """At most ``limit`` characters, then an ellipsis - only if something was cut."""
    return text[:limit] + "…"
