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


def unified_diff(msg) -> Optional[str]:
    """A unified diff out of a reply, or None.

    Looks inside fenced blocks whatever their language tag (models routinely
    label a diff as ```python), then falls back to scanning the raw text for
    the first diff header.
    """
    text = content_of(msg)
    if not text.strip():
        return None

    for body in fenced_blocks(text):
        stripped = body.strip("\n")
        if stripped.startswith(_DIFF_START):
            return stripped

    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(_DIFF_START):
            return "\n".join(lines[i:]).strip("\n")
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
