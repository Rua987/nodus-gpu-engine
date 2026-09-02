"""Capability jail for sandbox execution.

LLM-generated shell commands are checked here before they reach a sandbox.
Deny list first (hard stop on obviously destructive / exfiltration shapes),
then an allow list of command heads the agent is expected to need for a
coding / test-triage task. Unknown-but-not-denied commands are rejected in
strict mode (default) and warned-through in permissive mode.

This is a *different concern* from ``nodus_policy`` (which governs read/write
loop discipline per backend) - here we gate the action itself.
"""
from __future__ import annotations

import re
from typing import Tuple

# Hard deny - substring match, case-insensitive.
DENY_SUBSTRINGS = (
    "rm -rf", "rm -fr", ":(){", "mkfs", "dd if=", "dd of=/dev", "> /dev/sd",
    "shutdown", "reboot", "halt", "sudo ", "chown -r /", "chmod -r 777 /",
    "curl ", "wget ", "nc ", "ncat ", "telnet ", "ssh ", "scp ",
    "/etc/passwd", "/etc/shadow", "base64 -d", "eval $(", "| sh", "| bash",
    "systemctl", "iptables", "kill -9 1", "> ~/.ssh", "git push",
)

# Allow - the command (after stripping a leading ``ENV=v`` prefix) must start
# with one of these heads.
ALLOW_HEADS = (
    "python -m pytest", "python -m ", "python3 -m ", "pytest", "python -c",
    "python3 -c", "python ", "python3 ",
    "pip install -r", "pip install --", "pip freeze", "pip list",
    "ruff", "flake8", "mypy", "black --check",
    "echo ", "ls", "cat ", "head ", "tail ", "wc ", "pwd", "true", "false",
    "git status", "git diff", "git log", "git show", "git rev-parse",
    "git apply", "patch -p", "patch --",
    "mkdir -p", "cp ", "mv ", "grep ", "rg ", "find . ",
)

_ENV_PREFIX = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)+")


def _strip_env(cmd: str) -> str:
    return _ENV_PREFIX.sub("", cmd.strip())


def check_command(command: str, strict: bool = True) -> Tuple[bool, str]:
    """Return ``(allowed, reason)``."""
    raw = (command or "").strip()
    if not raw:
        return False, "empty command"

    low = raw.lower()
    for bad in DENY_SUBSTRINGS:
        if bad in low:
            return False, f"denied: matches {bad!r}"

    body = _strip_env(raw)
    if body.startswith(ALLOW_HEADS):
        return True, "allowed"

    if strict:
        head = body.split()[0] if body.split() else body
        return False, f"not in allow list: {head!r}"
    return True, "permissive: not denied"
