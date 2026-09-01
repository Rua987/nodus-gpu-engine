#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ TEMPLE IAM - Tests rédaction de secrets (nodus_tools)
⚡ Coverage target: 100% sur redact_secrets / _redact_result / dispatch_tool hook
Copyright © 2024 Temple IAM - All Rights Reserved
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from nodus_tools import (
    ToolResult,
    _redact_result,
    dispatch_tool,
    redact_secrets,
)

_REDACTED = "[REDACTED-SECRET]"


# ── redact_secrets : secrets caviardés ───────────────────────────────────────
@pytest.mark.parametrize(
    "raw",
    [
        "OPENROUTER_API_KEY=sk-or-v1-" + "a" * 40,   # OpenRouter
        "key: sk-" + "b" * 40,                       # OpenAI-style
        "aws AKIAIOSFODNN7EXAMPLE end",              # AWS access key
        "tmp ASIAIOSFODNN7EXAMPLE end",              # AWS temp key
        "ghp_" + "c" * 36,                           # GitHub PAT classic
        "gho_" + "c" * 36,                           # GitHub oauth
        "github_pat_" + "d" * 30,                    # GitHub fine-grained
        "xoxb-" + "1234567890-abcdef",               # Slack bot token
        "AIza" + "E" * 35,                           # Google API key
        "Authorization: Bearer " + "f" * 30,         # Bearer header
        "Authorization: bearer " + "f" * 30,         # Bearer (lowercase)
        'api_key = "' + "g" * 20 + '"',              # api_key=...
        "api-key: " + "h" * 20,                      # api-key with dash
        "secret=" + "i" * 16,                        # secret=
        "TOKEN=" + "j" * 16,                         # token (case-insensitive)
        "password: " + "k" * 16,                     # password
        "access_token=" + "l" * 16,                  # access_token
    ],
)
def test_known_secrets_are_redacted(raw):
    """Tout secret au format reconnu est remplacé par le marqueur."""
    out = redact_secrets(raw)
    assert _REDACTED in out
    # La portion secrète n'apparaît plus en clair.
    assert "a" * 40 not in out
    assert "AKIAIOSFODNN7EXAMPLE" not in out or "AKIA" not in raw


def test_pem_private_key_block_is_redacted():
    """Un bloc clé privée PEM complet est caviardé."""
    pem = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEpAIBAAKCAQEA0Z3VS\nbase64lines==\n"
        "-----END RSA PRIVATE KEY-----"
    )
    out = redact_secrets("config:\n" + pem + "\ndone")
    assert _REDACTED in out
    assert "base64lines" not in out
    assert out.startswith("config:")
    assert out.endswith("done")


# ── redact_secrets : prose/code normal intact (précision) ────────────────────
@pytest.mark.parametrize(
    "raw",
    [
        "def add(a, b):\n    return a + b  # normal code",
        "The token=abc was set with id=12345",          # trop court (<12)
        "import os; path = '/usr/local/bin'",
        "user logged in at 2024-01-02T10:00:00Z",
        "secret=short",                                  # 5 chars < 12
        "Bearer cat",                                    # trop court
        "the password is unknown",                       # pas de = ou :
        "sk-only",                                        # trop court pour sk-
    ],
)
def test_normal_text_is_untouched(raw):
    """Le code/prose normal et les valeurs trop courtes restent intacts."""
    assert redact_secrets(raw) == raw


def test_empty_string_returns_empty():
    """Chaîne vide → renvoyée telle quelle (court-circuit)."""
    assert redact_secrets("") == ""


def test_context_is_preserved_around_secret():
    """Seule la portion secrète est remplacée, le contexte demeure."""
    out = redact_secrets("export OPENROUTER_API_KEY=sk-or-v1-" + "z" * 40)
    assert out == "export OPENROUTER_API_KEY=" + _REDACTED


def test_multiple_secrets_in_one_text():
    """Plusieurs secrets dans le même texte sont tous caviardés."""
    raw = "k1=sk-" + "a" * 40 + "\nk2=ghp_" + "b" * 36
    out = redact_secrets(raw)
    assert out.count(_REDACTED) == 2


# ── _redact_result : application aux deux champs ─────────────────────────────
def test_redact_result_redacts_output_and_error():
    """output ET error sont caviardés."""
    r = ToolResult(
        success=False,
        output="leak sk-" + "a" * 40,
        error="also token=" + "b" * 20,
    )
    red = _redact_result(r)
    assert _REDACTED in red.output
    assert _REDACTED in red.error
    assert red.success is False


def test_redact_result_handles_none_error():
    """Un error=None reste None (pas de crash)."""
    r = ToolResult(success=True, output="ok", error=None)
    red = _redact_result(r)
    assert red.error is None
    assert red.output == "ok"


# ── dispatch_tool : le chokepoint applique bien la rédaction ─────────────────
def test_dispatch_tool_redacts_real_file(tmp_path):
    """Un secret lu via dispatch_tool(read_file) est caviardé end-to-end."""
    f = tmp_path / "creds.txt"
    f.write_text("OPENROUTER_API_KEY=sk-or-v1-" + "q" * 40, encoding="utf-8")
    res = dispatch_tool("read_file", {"file_path": str(f)}, cwd=str(tmp_path))
    assert res.success
    assert _REDACTED in res.output
    assert "sk-or-v1" not in res.output


def test_dispatch_tool_redacts_error_path(tmp_path):
    """Même un message d'erreur contenant un secret est caviardé."""
    fake = ToolResult(success=False, output="", error="bad key sk-" + "w" * 40)
    with patch("nodus_tools._dispatch_tool", return_value=fake):
        res = dispatch_tool("read_file", {"file_path": "x"}, cwd=str(tmp_path))
    assert _REDACTED in res.error


def test_dispatch_tool_normal_output_untouched(tmp_path):
    """Une sortie normale traverse dispatch_tool sans modification."""
    f = tmp_path / "code.py"
    f.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    res = dispatch_tool("read_file", {"file_path": str(f)}, cwd=str(tmp_path))
    assert res.success
    assert "def add(a, b):" in res.output
    assert _REDACTED not in res.output
