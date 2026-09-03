"""Capability jail for sandbox execution.

LLM-generated shell commands are checked here before they reach a sandbox.

The command is **split into segments** on ``;`` ``&&`` ``||`` ``|`` (quote-aware)
and *every* segment must pass, so a benign head can no longer smuggle a payload:
``echo ok && python -c "..."`` is rejected on its second segment. Command
substitution (``$(...)``, backticks) is refused outright - its contents cannot
be checked statically.

Order: substitution check -> deny substrings -> deny patterns -> per-segment
allow list. Unknown-but-not-denied segments are rejected in strict mode
(default) and warned-through in permissive mode.

This is defence in depth, not the security boundary: the sandbox (its own
microVM) is. The jail's job is to stop commands that are obviously outside the
shape of a test-triage task before they cost anything.

A *different concern* from ``nodus_policy`` (read/write loop discipline).
"""
from __future__ import annotations

import re
from typing import List, Tuple

MAX_COMMAND_LEN = 4096

# Hard deny - substring match, case-insensitive.
DENY_SUBSTRINGS = (
    "rm -rf", "rm -fr", ":(){", "mkfs", "dd if=", "dd of=/dev", "> /dev/sd",
    "shutdown", "reboot", "halt", "sudo ", "chown -r /", "chmod -r 777 /",
    "curl ", "wget ", "nc ", "ncat ", "telnet ", "ssh ", "scp ",
    "/etc/passwd", "/etc/shadow", "base64 -d", "eval $(", "| sh", "| bash",
    "systemctl", "iptables", "kill -9 1", "> ~/.ssh", "git push",
    "/bin/sh", "/bin/bash", "/bin/zsh", "/usr/bin/env sh",
    # credential material - reading it is never part of a test-triage task
    "~/.aws", "~/.ssh", "/.ssh/", "id_rsa", "id_ed25519", ".netrc", ".npmrc",
    "credentials", ".git-credentials", "_api_key", "authorized_keys",
)

# Hard deny - regex, for shapes a substring cannot express (interpreter escape
# hatches that would otherwise ride in under an allowed head like ``python ``).
DENY_PATTERNS = tuple(re.compile(p, re.I) for p in (
    r"\bpython3?\s+-\w*c\b",            # python -c / -Ic : arbitrary code
    r"\b(?:ba|z|k|d)?sh\s+-\w*c\b",     # sh -c / bash -c : shell escape
    r"\b(?:perl|ruby|node|deno)\s+-e\b",
    r"\brm\s+(?:-\S+\s+)*-\S*[rf]",     # rm -r / -f / -r -f, any spacing
    r"\bpython3?\s+-m\s+(?:http\.server|socketserver|smtpd|SimpleHTTPServer)\b",
    r"\bchmod\s+(?:-\S+\s+)*[0-7]*7{3}\b",
))

# Allow - a segment (after stripping a leading ``ENV=v`` prefix) must start
# with one of these heads...
ALLOW_HEADS = (
    "python -m pytest", "python3 -m pytest", "python -m ", "python3 -m ",
    "pytest",
    "pip install -r", "pip install --", "pip freeze", "pip list",
    "ruff", "flake8", "mypy", "black --check",
    "echo ", "ls ", "cat ", "head ", "tail ", "wc ",
    "git status", "git diff", "git log", "git show", "git rev-parse",
    "git apply", "git init", "git add ", "git -c ", "git checkout -- ",
    "patch -p", "patch --",
    "mkdir -p", "cp ", "mv ", "grep ", "rg ", "find . ",
)

# ...or match one of these exactly (bare, argument-less commands).
ALLOW_EXACT = (
    "ls", "pwd", "true", "false", "git status", "git diff", "git init",
    "pip freeze", "pip list",
)

_ENV_PREFIX = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)+")
_SUBSTITUTION = ("$(", "`", "<(", ">(")


def _strip_env(cmd: str) -> str:
    return _ENV_PREFIX.sub("", cmd.strip())


def split_segments(cmd: str) -> List[str]:
    """Split on ``;`` ``&&`` ``||`` ``|`` and newlines, ignoring operators that
    appear inside quotes. ``2>&1`` is not a separator (single ``&``)."""
    segs: List[str] = []
    buf: List[str] = []
    quote = None
    i = 0
    while i < len(cmd):
        c = cmd[i]
        if quote:
            buf.append(c)
            if c == "\\" and i + 1 < len(cmd):
                i += 1
                buf.append(cmd[i])
            elif c == quote:
                quote = None
            i += 1
            continue
        if c in "'\"":
            quote = c
            buf.append(c)
            i += 1
            continue
        if cmd[i:i + 2] in ("&&", "||"):
            segs.append("".join(buf))
            buf = []
            i += 2
            continue
        if c in ";\n|":
            segs.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    segs.append("".join(buf))
    return [s.strip() for s in segs if s.strip()]


def check_command(command: str, strict: bool = True) -> Tuple[bool, str]:
    """Return ``(allowed, reason)``. Every segment must pass."""
    raw = (command or "").strip()
    if not raw:
        return False, "empty command"
    if len(raw) > MAX_COMMAND_LEN:
        return False, f"command too long ({len(raw)} > {MAX_COMMAND_LEN})"

    for sub in _SUBSTITUTION:
        if sub in raw:
            return False, f"denied: command substitution {sub!r} cannot be vetted"

    low = raw.lower()
    for bad in DENY_SUBSTRINGS:
        if bad in low:
            return False, f"denied: matches {bad!r}"
    for pat in DENY_PATTERNS:
        m = pat.search(raw)
        if m:
            return False, f"denied: matches pattern {m.group(0)!r}"

    segments = split_segments(raw)
    if not segments:
        return False, "empty command"

    for seg in segments:
        body = _strip_env(seg)
        if not body:
            return False, f"empty segment in {raw!r}"
        if body in ALLOW_EXACT or body.startswith(ALLOW_HEADS):
            continue
        if strict:
            head = body.split()[0] if body.split() else body
            return False, (f"not in allow list: {head!r}"
                           + (f" (segment {seg!r})" if len(segments) > 1 else ""))
        return True, "permissive: not denied"

    n = len(segments)
    return True, "allowed" if n == 1 else f"allowed ({n} segments)"
