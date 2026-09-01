#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ TEMPLE IAM - Tests nodus_policy.py
⚡ Coverage target: 100%
Copyright © 2024 Temple IAM - All Rights Reserved
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from nodus_policy import (
    ANALYSIS_TOOLS,
    CLOUD_POLICY,
    LOCAL_POLICY,
    MAX_FORCE_WRITES,
    MAX_MULTI_HIT,
    MAX_REFOCUS,
    READ_TOOLS,
    WRITE_TOOLS,
    MUTATING_TOOLS,
    duplicate_read_message,
    extract_grep_hit_files,
    force_write_message,
    multi_hit_grep_challenge,
    policy_for,
    read_paralysis_message,
    refocus_message,
    relax_read_budget,
    should_force_write,
    should_multi_hit_challenge,
    should_refocus,
    should_stop_read_paralysis,
    transition_gate_prompt,
)


# ── policy_for ────────────────────────────────────────────────────────────────

class TestPolicyFor:
    def test_ollama_is_local(self):
        assert policy_for("qwen3.5:2b").label == "local"

    def test_dolphin_is_local(self):
        assert policy_for("dolphin3:latest").label == "local"

    def test_openrouter_is_cloud(self):
        assert policy_for("openrouter/anthropic/claude-opus-4.8").label == "cloud"

    def test_claude_is_cloud(self):
        assert policy_for("claude-opus-4-8").label == "cloud"

    def test_deepseek_is_cloud(self):
        assert policy_for("deepseek-chat").label == "cloud"

    def test_local_has_no_read_budget(self):
        assert policy_for("qwen3.5:2b").read_budget == 0

    def test_cloud_has_read_budget(self):
        assert policy_for("openrouter/x").read_budget == 2

    def test_local_no_gate(self):
        assert policy_for("qwen3.5:2b").gate is False

    def test_cloud_gate(self):
        assert policy_for("openrouter/x").gate is True

    def test_read_heavy_profiles_relax_budget(self):
        # security/research = lourds en lecture → budget relâché vs cloud serré.
        tight = policy_for("openrouter/x").read_budget
        for prof in ("security", "research"):
            assert policy_for("openrouter/x", prof).read_budget > tight

    def test_coding_profiles_keep_tight_budget(self):
        tight = policy_for("openrouter/x").read_budget
        for prof in ("code", "debug", "test", None):
            assert policy_for("openrouter/x", prof).read_budget == tight

    def test_profile_case_insensitive(self):
        assert (policy_for("openrouter/x", "SECURITY").read_budget
                == policy_for("openrouter/x", "security").read_budget)

    def test_local_stays_loose_even_read_heavy(self):
        # Local n'a pas de budget (0, lâche) ; le profil ne le change pas.
        assert policy_for("qwen3.5:2b", "security").read_budget == 0


class TestRelaxReadBudget:
    def test_cloud_budget_relaxed(self):
        # tâche itérative = bash est l'action → budget relâché vs cloud serré.
        assert relax_read_budget(CLOUD_POLICY).read_budget > CLOUD_POLICY.read_budget

    def test_local_unchanged(self):
        # local (budget 0) n'est pas touché.
        assert relax_read_budget(LOCAL_POLICY).read_budget == 0

    def test_idempotent(self):
        once = relax_read_budget(CLOUD_POLICY)
        assert relax_read_budget(once).read_budget == once.read_budget


# ── presets ───────────────────────────────────────────────────────────────────

class TestPresets:
    def test_cloud_tighter_than_local(self):
        assert CLOUD_POLICY.rec_max_rounds <= LOCAL_POLICY.rec_max_rounds

    def test_read_write_tools_disjoint(self):
        assert READ_TOOLS.isdisjoint(WRITE_TOOLS)

    def test_read_tools_content(self):
        assert "read_file" in READ_TOOLS and "grep" in READ_TOOLS

    def test_analysis_tools_include_bash(self):
        assert "bash" in ANALYSIS_TOOLS
        assert READ_TOOLS.issubset(ANALYSIS_TOOLS)

    def test_write_tools_content(self):
        assert "write_file" in WRITE_TOOLS and "edit_file" in WRITE_TOOLS

    def test_max_force_positive(self):
        assert MAX_FORCE_WRITES > 0

    def test_max_refocus_positive(self):
        assert MAX_REFOCUS > 0

    def test_both_backends_have_thrash_active(self):
        # La non-livraison est un échec quel que soit le coût → thrash actif partout.
        assert CLOUD_POLICY.thrash_budget > 0 and LOCAL_POLICY.thrash_budget > 0

    def test_cloud_thrash_stricter_than_local(self):
        assert CLOUD_POLICY.thrash_budget <= LOCAL_POLICY.thrash_budget


# ── transition_gate_prompt ────────────────────────────────────────────────────

class TestTransitionGatePrompt:
    def test_mentions_decide_fast(self):
        assert "DECIDE FAST" in transition_gate_prompt()

    def test_forbids_re_reading(self):
        assert "NEVER read the same file twice" in transition_gate_prompt()


# ── should_force_write ────────────────────────────────────────────────────────

class TestShouldForceWrite:
    def test_cloud_at_budget_forces(self):
        assert should_force_write(CLOUD_POLICY.read_budget, CLOUD_POLICY, 0) is True

    def test_cloud_over_budget_forces(self):
        assert should_force_write(CLOUD_POLICY.read_budget + 3, CLOUD_POLICY, 0) is True

    def test_cloud_under_budget_no_force(self):
        assert should_force_write(CLOUD_POLICY.read_budget - 1, CLOUD_POLICY, 0) is False

    def test_local_never_forces(self):
        assert should_force_write(99, LOCAL_POLICY, 0) is False

    def test_force_cap_respected(self):
        assert should_force_write(99, CLOUD_POLICY, MAX_FORCE_WRITES) is False


# ── read paralysis ────────────────────────────────────────────────────────────

class TestReadParalysis:
    def test_stops_after_force_writes_exhausted(self):
        assert should_stop_read_paralysis(
            CLOUD_POLICY.read_budget, CLOUD_POLICY, MAX_FORCE_WRITES
        ) is True

    def test_no_stop_under_force_cap(self):
        assert should_stop_read_paralysis(
            CLOUD_POLICY.read_budget, CLOUD_POLICY, MAX_FORCE_WRITES - 1
        ) is False

    def test_local_never_stops(self):
        assert should_stop_read_paralysis(99, LOCAL_POLICY, MAX_FORCE_WRITES) is False

    def test_duplicate_read_message(self):
        assert "already read" in duplicate_read_message("foo.py").lower()

    def test_read_paralysis_message(self):
        assert "READ PARALYSIS" in read_paralysis_message()


# ── force_write_message ───────────────────────────────────────────────────────

class TestForceWriteMessage:
    def test_says_stop_reading(self):
        assert "Stop reading" in force_write_message()

    def test_names_write_tools(self):
        msg = force_write_message()
        assert "write_file" in msg and "edit_file" in msg


# ── MUTATING_TOOLS (anti-thrash, signal outcome) ──────────────────────────────

class TestMutatingTools:
    def test_includes_writes_and_bash(self):
        assert {"write_file", "edit_file", "bash"} <= MUTATING_TOOLS

    def test_excludes_pure_reads(self):
        assert MUTATING_TOOLS.isdisjoint(READ_TOOLS)


# ── should_refocus (anti-thrash, signal outcome = rounds bloqués) ──────────────

class TestShouldRefocus:
    def test_thrash_at_budget_with_missing_refocuses(self):
        assert should_refocus(CLOUD_POLICY.thrash_budget, ["doc.md"], 0, CLOUD_POLICY) is True

    def test_no_missing_no_refocus(self):
        assert should_refocus(99, [], 0, CLOUD_POLICY) is False

    def test_under_budget_no_refocus(self):
        assert should_refocus(CLOUD_POLICY.thrash_budget - 1, ["doc.md"], 0, CLOUD_POLICY) is False

    def test_refocus_cap_respected(self):
        assert should_refocus(99, ["doc.md"], MAX_REFOCUS, CLOUD_POLICY) is False

    def test_local_thrash_also_active(self):
        assert should_refocus(LOCAL_POLICY.thrash_budget, ["doc.md"], 0, LOCAL_POLICY) is True


# ── refocus_message (anti-thrash) ─────────────────────────────────────────────

class TestRefocusMessage:
    def test_names_missing_artifact(self):
        assert "doc.md" in refocus_message(["doc.md"])

    def test_calls_out_noise(self):
        assert "noise" in refocus_message(["doc.md"]).lower()

    def test_lists_several_missing(self):
        msg = refocus_message(["a.md", "b.py"])
        assert "a.md" in msg and "b.py" in msg


# ── grep multi-hit ────────────────────────────────────────────────────────────

class TestExtractGrepHitFiles:
    def test_files_with_matches(self):
        assert extract_grep_hit_files("a.py\nb.py\na.py") == ["a.py", "b.py"]

    def test_content_mode(self):
        out = "a.py:3: def f():\nb.py:1: import a\na.py:10: f()"
        assert extract_grep_hit_files(out) == ["a.py", "b.py"]

    def test_no_matches(self):
        assert extract_grep_hit_files("(no matches)") == []
        assert extract_grep_hit_files("") == []

    def test_windows_rel_paths(self):
        assert extract_grep_hit_files("pkg\\a.py\npkg\\b.py") == ["pkg\\a.py", "pkg\\b.py"]


class TestMultiHitChallenge:
    def test_should_when_two_files(self):
        assert should_multi_hit_challenge(["a.py", "b.py"], 0) is True

    def test_should_not_single(self):
        assert should_multi_hit_challenge(["a.py"], 0) is False

    def test_should_not_at_cap(self):
        assert should_multi_hit_challenge(["a.py", "b.py"], MAX_MULTI_HIT) is False

    def test_message_lists_files_and_read(self):
        msg = multi_hit_grep_challenge("estimate_task_steps", ["nodus_agent.py", "nodus_planner.py"])
        assert "MULTI-HIT" in msg
        assert "nodus_planner.py" in msg
        assert "read_file" in msg
        assert "DEFINES" in msg
        assert "estimate_task_steps" in msg
