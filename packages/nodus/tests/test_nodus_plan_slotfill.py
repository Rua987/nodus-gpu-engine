#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ TEMPLE IAM - Tests nodus_plan_slotfill.py
⚡ Coverage target: 100%
Copyright © 2024 Temple IAM - All Rights Reserved

Couvre deux hardening : (1) le prompt martèle que la cle JSON est TOUJOURS
"target" (hermes renvoyait {"file_path": ...} — cle = nom d'argument) ;
(2) parse_slotfill normalise la CHAINE "null"/"none"/"n/a" vers None (le
modele qwen renvoyait "null" quote, qui traversait pour bash non-guarde).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from nodus_plan_slotfill import (
    _SLOT_PROMPT,
    _sanitize_target,
    build_slotfill_prompt,
    fill_plan_targets,
    format_plan_with_targets,
    parse_slotfill,
)

TASK = (
    "Read script.txt, then save a new file shoot_day_brief.md with the shoot-day brief, "
    "then upload it to Google Cloud Storage, then verify."
)


class TestParseSlotfill:
    """parse_slotfill: JSON -> str | None."""

    def test_json_null_returns_none(self):
        assert parse_slotfill('{"target": null}') is None

    def test_empty_string_returns_none(self):
        assert parse_slotfill('{"target": ""}') is None

    def test_whitespace_string_returns_none(self):
        assert parse_slotfill('{"target": "   "}') is None

    def test_literal_string_null_returns_none(self):
        # hardening 2 : le modele renvoyait la CHAINE "null" (pas JSON null)
        assert parse_slotfill('{"target": "null"}') is None

    def test_literal_string_none_case_insensitive(self):
        assert parse_slotfill('{"target": "None"}') is None

    def test_literal_string_na_returns_none(self):
        assert parse_slotfill('{"target": "n/a"}') is None

    def test_literal_uppercase_null_returns_none(self):
        assert parse_slotfill('{"target": "NULL"}') is None

    def test_real_target_returned(self):
        assert parse_slotfill('{"target": "shoot_day_brief.md"}') == "shoot_day_brief.md"

    def test_wrong_key_rejected(self):
        # hermes renvoyait {"file_path": "script.txt"} — cle = nom d'argument
        assert parse_slotfill('{"file_path": "script.txt"}') is None

    def test_fenced_json_accepted(self):
        assert parse_slotfill('```json\n{"target": "a.txt"}\n```') == "a.txt"

    def test_prose_rejected(self):
        assert parse_slotfill("The file is a.txt") is None

    def test_empty_or_none_input(self):
        assert parse_slotfill(None) is None
        assert parse_slotfill("") is None
        assert parse_slotfill("   ") is None


class TestBuildSlotfillPrompt:
    """build_slotfill_prompt: le prompt ne doit plus fuiter le nom d'argument."""

    def test_prompt_key_is_always_target(self):
        prompt = build_slotfill_prompt(TASK, "read_file", 1, 3, [])
        assert 'ALWAYS "target"' in prompt
        assert "never `file_path`" in prompt

    def test_template_contains_always_target_directive(self):
        # garde-fou de regression sur le template lui-meme
        assert 'ALWAYS "target"' in _SLOT_PROMPT
        assert '"target": null' in _SLOT_PROMPT

    def test_prompt_shows_previous_steps(self):
        prompt = build_slotfill_prompt(
            TASK, "write_file", 2, 3, [("read_file", "script.txt")]
        )
        assert '1. read_file target="script.txt"' in prompt
        assert "Step: 2/3" in prompt


class TestFillPlanTargetsChain:
    """fill_plan_targets: chaine complete parse -> sanitize avec _chat fake."""

    @staticmethod
    def _chat(content):
        def chat(messages, model, **kwargs):
            return {"content": content}
        return chat

    def test_string_null_returns_none_for_bash(self):
        # hardening 2 : bash (non path-guarde) ne doit plus recevoir "null"
        targets = fill_plan_targets(
            TASK, ["bash"], self._chat('{"target": "null"}'), "fake:model"
        )
        assert targets == [None]

    def test_string_null_returns_none_for_read_file(self):
        targets = fill_plan_targets(
            TASK, ["read_file"], self._chat('{"target": "null"}'), "fake:model"
        )
        assert targets == [None]

    def test_wrong_key_rejected_in_chain(self):
        targets = fill_plan_targets(
            TASK, ["read_file"], self._chat('{"file_path": "script.txt"}'), "fake:model"
        )
        assert targets == [None]

    def test_genuine_write_target_survives(self):
        targets = fill_plan_targets(
            TASK, ["write_file"],
            self._chat('{"target": "shoot_day_brief.md"}'), "fake:model",
        )
        assert targets == ["shoot_day_brief.md"]


class TestSanitizeTarget:
    """_sanitize_target: garde-fous deterministes isoles."""

    def test_keeps_genuine_write_target(self):
        assert _sanitize_target(
            "write_file", "shoot_day_brief.md", TASK, []
        ) == "shoot_day_brief.md"

    def test_kills_write_target_outside_expected_files(self):
        # qwen a copie "script.txt" pour write_file : hors fichiers attendus
        assert _sanitize_target("write_file", "script.txt", TASK, []) is None

    def test_kills_non_path_for_read(self):
        assert _sanitize_target("read_file", "done", TASK, []) is None

    def test_bash_keeps_unknown_value(self):
        # bash n'est pas path-guarde : seule la garde parse (hardening 2)
        # protege contre "null" ; ici une valeur quelconque passe.
        assert _sanitize_target("bash", "ls -la", TASK, []) == "ls -la"


class TestFormatPlanWithTargets:
    """format_plan_with_targets: le bloc SUGGESTED TOOL SEQUENCE."""

    def test_aligns_targets_and_none(self):
        block = format_plan_with_targets(
            ["read_file", "write_file", "bash"],
            [None, "shoot_day_brief.md", None],
        )
        assert "SUGGESTED TOOL SEQUENCE" in block
        assert "set `file_path` to exactly: 'shoot_day_brief.md'" in block
        assert "`file_path` comes from a previous tool result" in block

    def test_mismatched_targets_len_falls_back_to_none(self):
        block = format_plan_with_targets(["read_file"], [None, "x.md"])
        assert "comes from a previous tool result" in block
        assert "exactly:" not in block

    def test_empty_names_returns_empty(self):
        assert format_plan_with_targets([]) == ""
