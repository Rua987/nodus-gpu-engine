"""Extract usable artefacts from free-form LLM output.

Models wrap answers in markdown fences, prefix shell prompts, tag a diff as
```python, or return nothing at all. The orchestrator used to index
``.splitlines()[0]`` straight into the reply - an empty response raised
IndexError and killed the whole run, and a fenced reply produced the literal
command ``` ```bash ``` which the jail then rejected.

Everything here is total: it returns a value or ``None``, never raises.
"""
from __future__ import annotations

import re
from typing import List, Optional

# ```lang\n body \n```  - tolerates an unclosed fence (body runs to the end)
_FENCE_RE = re.compile(r"```[ \t]*(\w*)[ \t]*\r?\n(.*?)(?:```|\Z)", re.S)
# '#' is deliberately not a prompt here: in model output a leading '#' is a
# comment far more often than a root shell prompt.
_PROMPT_RE = re.compile(r"^(?:\$|>)\s+")
_DIFF_START = ("--- ", "diff --git ", "diff --git\t", "Index: ")


def content_of(msg) -> str:
    """The assistant text of an Ollama-style message dict, or ''."""
    if isinstance(msg, dict):
        c = msg.get("content")
        if isinstance(c, str):
            return c
        # some backends nest the text
        m = msg.get("message")
        if isinstance(m, dict) and isinstance(m.get("content"), str):
            return m["content"]
    elif isinstance(msg, str):
        return msg
    return ""


def fenced_blocks(text: str) -> List[str]:
    """Bodies of every ``` fenced block, in order."""
    return [b for _, b in _FENCE_RE.findall(text or "")]


def first_command(msg) -> Optional[str]:
    """The first runnable-looking line of a reply, or None.

    Prefers the first fenced block (that is where models put commands), falls
    back to the raw text. Strips a leading shell prompt.
    """
    text = content_of(msg)
    if not text.strip():
        return None
    blocks = fenced_blocks(text)
    body = blocks[0] if blocks and blocks[0].strip() else text
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):        # blank / comment
            continue
        return _PROMPT_RE.sub("", line)
    return None


# Both `@@ -a,b +c,d @@` and a bare `@@`. Models write the bare form often -
# it reads like a diff but patch-ng refuses the file outright ("skipping
# invalid patch with no hunks"), so the patch dies before its content matters.
# A bare header means "position unknown": it is given line 1 here and the
# orchestrator's _relocate_hunks then finds where the context really is.
_HUNK_RE = re.compile(
    r"^@@(?:\s+-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s*@@)?(.*)$")


def normalize_hunks(diff: str) -> str:
    """Recompute every ``@@ -a,b +c,d @@`` from the lines that follow it.

    Models write plausible counts without counting. A live Nemotron patch
    declared ``@@ -35,7 +35,7 @@`` above four lines, and patch-ng rejected the
    whole file with "patch stream is incomplete!" - the diff was otherwise
    correct: right file, right line, right indentation.

    Only the counts are touched; content and start lines are left alone.
    """
    if not diff:
        return diff
    # Drop git's envelope. patch-ng strips the a/ prefix itself when it sees a
    # `diff --git` line, so our fixed `--strip 1` then removes one component
    # too many and the file is reported missing:
    #     source/target file does not exist: --- b'nodus/nodus_tools.py'
    # Keeping only the ---/+++ form makes the strip depth predictable.
    lines = [l for l in diff.splitlines()
             if not l.startswith(("diff --git ", "index ", "old mode ",
                                  "new mode ", "similarity index "))]
    out, i = [], 0
    while i < len(lines):
        m = _HUNK_RE.match(lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue
        # a bare @@ carries no position; 1 is a placeholder for _relocate_hunks
        old_start = int(m.group(1)) if m.group(1) else 1
        new_start = int(m.group(2)) if m.group(2) else 1
        tail = m.group(3)
        body, j = [], i + 1
        while j < len(lines):
            ln = lines[j]
            if ln.startswith("@@") or ln.startswith(("--- ", "+++ ", "diff --git")):
                break
            if ln[:1] not in (" ", "-", "+", "\\", ""):
                break
            body.append(ln)
            j += 1
        while body and body[-1] == "":
            body.pop()
        old = sum(1 for b in body if b[:1] in (" ", "-") or b == "")
        new = sum(1 for b in body if b[:1] in (" ", "+") or b == "")
        out.append(f"@@ -{old_start},{old} +{new_start},{new} @@{tail}")
        out.extend(body)
        i = j
    return "\n".join(out) + "\n"



def _dedent(block: str) -> str:
    """Remove a uniform indent a model added to a fenced diff.

    Some replies indent the whole block by four spaces. The leading `---`
    then no longer starts the line, extraction misses it entirely, and the
    patch is lost as "no diff". A diff's own structure lives in column 0
    (' ', '-', '+'), so only a shared prefix on *every* non-empty line is
    stripped - never per-line whitespace, which would corrupt the hunks.
    """
    lines = block.splitlines()
    real = [l for l in lines if l.strip()]
    if not real:
        return block
    pad = min(len(l) - len(l.lstrip(" ")) for l in real)
    if pad == 0:
        return block
    return "\n".join(l[pad:] if l.strip() else l for l in lines)


def has_hunks_without_header(text: str) -> bool:
    """A reply carrying `@@` hunks but naming no file.

    Not recoverable here: without `--- a/<path>` there is nothing to say which
    file to patch, and guessing would apply a diff to the wrong one. Reported
    so the run says *why* nothing was extracted instead of a bare "no diff".
    """
    if not text:
        return False
    for body in fenced_blocks(text) or [text]:
        b = _dedent(body.strip("\n"))
        if b.startswith("@@") and not b.startswith(_DIFF_START):
            return True
    return False


def unified_diff(msg) -> Optional[str]:
    """A unified diff out of a reply, or None.

    Looks inside fenced blocks whatever their language tag (models routinely
    label a diff as ```python), then falls back to scanning the raw text for
    the first diff header.
    """
    text = content_of(msg)
    if not text.strip():
        return None

    # A patch stream must end with a newline. Without it patch-ng refuses the
    # whole thing with "patch stream is incomplete!" - a live Nemotron patch
    # was rejected for exactly that, before its content was even considered.
    for body in fenced_blocks(text):
        stripped = _dedent(body.strip("\n"))
        if stripped.startswith(_DIFF_START):
            return normalize_hunks(stripped)

    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(_DIFF_START):
            return normalize_hunks("\n".join(lines[i:]).strip("\n"))
    return None


def json_object(msg) -> Optional[dict]:
    """The first JSON object in a reply, or None.

    Looks inside fenced blocks first (models label JSON as ```json), then
    scans the raw text for a balanced {...}. Never raises.
    """
    import json as _json

    text = content_of(msg)
    if not text.strip():
        return None

    candidates = [b.strip() for b in fenced_blocks(text)]
    candidates.append(text)
    for cand in candidates:
        start = cand.find("{")
        if start < 0:
            continue
        depth, in_str, esc = 0, False, False
        for i in range(start, len(cand)):
            c = cand[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = _json.loads(cand[start:i + 1])
                    except ValueError:
                        break
                    return obj if isinstance(obj, dict) else None
    return None
