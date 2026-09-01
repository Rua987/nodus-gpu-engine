#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ TEMPLE IAM - Tests d'ENDURANCE (persistance sur tâche longue)
⚡ Garantie anti-régression : l'agent ne baille JAMAIS en cours de route
🔥 Déterministe — modèle scripté qui tente d'abandonner, outils & verify réels

Copyright © 2024 Temple IAM - All Rights Reserved

La persistance est une propriété de la BOUCLE. On la teste sans modèle réel :
_chat est mocké pour simuler un modèle qui essaie d'abandonner (narration,
fausse conclusion), avec dispatch réel + vérification réelle sur disque.
Si quelqu'un casse un garde (continuation / verify / anti-shortcut), ces
tests échouent immédiatement.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from nodus_agent import run_agent


# ── Helpers ────────────────────────────────────────────────────────────────────

def _msg(content="", tool_calls=None):
    m = {"role": "assistant", "content": content}
    if tool_calls is not None:
        m["tool_calls"] = tool_calls
    return m


def _wf(path, content):
    """tool_call write_file."""
    return [{"id": "c", "function": {"name": "write_file",
            "arguments": {"file_path": path, "content": content}}}]


def _scripted_chat(messages_sequence):
    """Construit un fake _chat qui débite la séquence puis répond 'done'."""
    it = iter(messages_sequence)

    def fake(messages, model, tools=None, text_tools=False):
        try:
            return next(it)
        except StopIteration:
            return _msg(content="done")
    return fake


# ── La grande épreuve d'endurance ──────────────────────────────────────────────

class TestEndurancePersistence:
    """Un modèle paresseux tente d'abandonner 3x sur une tâche de 5 fichiers."""

    def _run_long_task(self, tmp_path):
        task = ("Create 5 files: part1.txt, part2.txt, part3.txt, part4.txt, "
                "part5.txt — each file must contain its own number.")
        scripted = [
            _msg(tool_calls=_wf("part1.txt", "1")),
            _msg(content="Next, I'll create the remaining files."),   # narration
            _msg(tool_calls=_wf("part2.txt", "2")),
            _msg(content="All files created. The task is complete."),  # fausse conclusion
            _msg(tool_calls=_wf("part3.txt", "3")),
            _msg(content="First, I'll finish the last two."),          # narration
            _msg(tool_calls=_wf("part4.txt", "4")),
            _msg(tool_calls=_wf("part5.txt", "5")),
            _msg(content="All 5 files have been created successfully."),  # vraie fin
        ]
        with patch("nodus_agent._chat", side_effect=_scripted_chat(scripted)):
            return run_agent(task, cwd=str(tmp_path), verify=True, max_rounds=30)

    def test_all_files_created(self, tmp_path):
        self._run_long_task(tmp_path)
        for i in range(1, 6):
            assert (tmp_path / f"part{i}.txt").exists(), f"part{i}.txt manquant"

    def test_file_contents_correct(self, tmp_path):
        self._run_long_task(tmp_path)
        for i in range(1, 6):
            assert (tmp_path / f"part{i}.txt").read_text(encoding="utf-8").strip() == str(i)

    def test_stopped_done_at_true_end(self, tmp_path):
        result = self._run_long_task(tmp_path)
        assert result.stopped_reason == "done"
        assert result.answer == "All 5 files have been created successfully."

    def test_exactly_five_tool_calls(self, tmp_path):
        result = self._run_long_task(tmp_path)
        assert result.tool_calls == 5

    def test_rounds_exceed_tool_calls(self, tmp_path):
        # rounds > tool_calls prouve que des abandons ont été rattrapés
        result = self._run_long_task(tmp_path)
        assert result.rounds > result.tool_calls


# ── Gardes isolés (régression fine) ────────────────────────────────────────────

class TestEnduranceGuards:
    def test_narration_does_not_end_run(self, tmp_path):
        """Une narration seule ne termine pas le run : l'agent continue."""
        scripted = [
            _msg(content="Next, I'll write the file."),   # narration → relance
            _msg(tool_calls=_wf("out.txt", "x")),          # puis agit vraiment
            _msg(content="Created out.txt."),              # vraie fin
        ]
        with patch("nodus_agent._chat", side_effect=_scripted_chat(scripted)):
            r = run_agent("Create out.txt with x", cwd=str(tmp_path), verify=True, max_rounds=20)
        assert (tmp_path / "out.txt").exists()
        assert r.stopped_reason == "done"

    def test_false_completion_blocked_by_verify(self, tmp_path):
        """Prétendre 'fini' sans le fichier ne passe pas : verify relance."""
        scripted = [
            _msg(content="The file goal.txt is ready, task complete."),  # mensonge
            _msg(tool_calls=_wf("goal.txt", "real")),                    # forcé d'agir
            _msg(content="Done for real."),
        ]
        with patch("nodus_agent._chat", side_effect=_scripted_chat(scripted)):
            r = run_agent("Create goal.txt", cwd=str(tmp_path), verify=True, max_rounds=20)
        assert (tmp_path / "goal.txt").exists()
        assert (tmp_path / "goal.txt").read_text(encoding="utf-8") == "real"
        assert r.stopped_reason == "done"

    def test_genuine_completion_not_over_challenged(self, tmp_path):
        """Une vraie fin (fichier présent, pas de narration) est acceptée vite."""
        scripted = [
            _msg(tool_calls=_wf("ok.txt", "1")),
            _msg(content="I have created ok.txt as requested."),
        ]
        with patch("nodus_agent._chat", side_effect=_scripted_chat(scripted)):
            r = run_agent("Create ok.txt", cwd=str(tmp_path), verify=True, max_rounds=20)
        assert r.stopped_reason == "done"
        assert r.tool_calls == 1
        # 2 rounds suffisent : action + conclusion (pas de relance superflue)
        assert r.rounds == 2
