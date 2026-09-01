#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ TEMPLE IAM - Tests nodus_planner.py
⚡ Coverage target: 100%
Copyright © 2024 Temple IAM - All Rights Reserved
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from nodus_planner import (
    MAX_PLAN_STEPS,
    PLANNING_WORD_THRESHOLD,
    build_plan_prompt,
    estimate_task_steps,
    format_plan_for_prompt,
    needs_planning,
    parse_plan,
)


# ── needs_planning ────────────────────────────────────────────────────────────

class TestNeedsPlanning:
    def test_empty_task(self):
        assert needs_planning("") is False

    def test_whitespace_task(self):
        assert needs_planning("   ") is False

    def test_simple_short_task(self):
        assert needs_planning("list files") is False

    def test_sequential_connector_puis(self):
        assert needs_planning("lis le fichier puis compte les lignes") is True

    def test_sequential_connector_then(self):
        assert needs_planning("read the file then count lines") is True

    def test_sequential_connector_ensuite(self):
        assert needs_planning("fais X ensuite fais Y") is True

    def test_numbered_task(self):
        assert needs_planning("1. read file\n2. write report") is True

    def test_long_task_over_threshold(self):
        # More than PLANNING_WORD_THRESHOLD words
        task = " ".join(["word"] * (PLANNING_WORD_THRESHOLD + 1))
        assert needs_planning(task) is True

    def test_task_exactly_at_threshold_no_planning(self):
        task = " ".join(["word"] * PLANNING_WORD_THRESHOLD)
        assert needs_planning(task) is False

    def test_step_keyword(self):
        assert needs_planning("do this step by step carefully") is True


# ── build_plan_prompt ─────────────────────────────────────────────────────────

class TestBuildPlanPrompt:
    def test_returns_string(self):
        assert isinstance(build_plan_prompt("do X"), str)

    def test_contains_task(self):
        assert "refactor module" in build_plan_prompt("refactor module")

    def test_mentions_plan(self):
        assert "PLAN" in build_plan_prompt("do X").upper()

    def test_task_stripped(self):
        prompt = build_plan_prompt("   spaced task   ")
        assert "spaced task" in prompt


# ── parse_plan ────────────────────────────────────────────────────────────────

class TestParsePlan:
    def test_empty_text(self):
        assert parse_plan("") == []

    def test_whitespace_text(self):
        assert parse_plan("   \n  ") == []

    def test_no_steps(self):
        assert parse_plan("just some prose with no list") == []

    def test_numbered_dot(self):
        assert parse_plan("1. read file\n2. count lines") == ["read file", "count lines"]

    def test_numbered_paren(self):
        assert parse_plan("1) first\n2) second") == ["first", "second"]

    def test_bullets_dash(self):
        assert parse_plan("- step a\n- step b") == ["step a", "step b"]

    def test_bullets_star(self):
        assert parse_plan("* alpha\n* beta") == ["alpha", "beta"]

    def test_step_keyword(self):
        assert parse_plan("Step 1: open\nStep 2: close") == ["open", "close"]

    def test_skips_blank_step_content(self):
        # A numbered marker with no content after is skipped
        result = parse_plan("1. \n2. real step")
        assert result == ["real step"]

    def test_mixed_prose_and_steps(self):
        text = "Here is the plan:\n1. do A\nsome note\n2. do B"
        assert parse_plan(text) == ["do A", "do B"]

    def test_respects_max_steps(self):
        text = "\n".join(f"{i}. step{i}" for i in range(1, 20))
        result = parse_plan(text, max_steps=3)
        assert len(result) == 3

    def test_default_max_steps(self):
        text = "\n".join(f"{i}. step{i}" for i in range(1, 30))
        result = parse_plan(text)
        assert len(result) <= MAX_PLAN_STEPS


# ── format_plan_for_prompt ────────────────────────────────────────────────────

class TestFormatPlanForPrompt:
    def test_empty_steps(self):
        assert format_plan_for_prompt([]) == ""

    def test_contains_plan_keyword(self):
        assert "PLAN" in format_plan_for_prompt(["a", "b"])

    def test_numbers_steps(self):
        result = format_plan_for_prompt(["read", "write"])
        assert "1. read" in result
        assert "2. write" in result

    def test_mentions_in_order(self):
        result = format_plan_for_prompt(["x"])
        assert "ORDER" in result or "order" in result

    def test_single_step(self):
        result = format_plan_for_prompt(["only step"])
        assert "1. only step" in result


# ── estimate_task_steps ───────────────────────────────────────────────────────

class TestEstimateTaskSteps:
    def test_no_connector(self):
        assert estimate_task_steps("list files") == 1

    def test_two_steps_then(self):
        assert estimate_task_steps("read X then edit Y") == 2

    def test_three_steps(self):
        assert estimate_task_steps(
            "Read notes/todo.txt, then in src/config.py change PORT, "
            "then write done_flag.txt with exactly done."
        ) == 3

    def test_empty(self):
        assert estimate_task_steps("") == 1
