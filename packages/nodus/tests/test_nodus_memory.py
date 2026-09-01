#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ TEMPLE IAM - Tests nodus_memory.py
⚡ Coverage target: 100%
Copyright © 2024 Temple IAM - All Rights Reserved
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from nodus_memory import (
    DEFAULT_MEMORY_FILE,
    MAX_MEMORY_ENTRIES,
    MEMORY_HEADER,
    _format_entry,
    _split_entries,
    append_memory_entry,
    format_memory_for_prompt,
    load_memory,
    resolve_memory_path,
    trim_memory,
)


# ── resolve_memory_path ───────────────────────────────────────────────────────

class TestResolveMemoryPath:
    def test_explicit_path_wins(self):
        p = resolve_memory_path(cwd="/some/dir", memory_path="/tmp/m.md")
        assert p.name == "m.md"

    def test_cwd_appends_default_file(self):
        p = resolve_memory_path(cwd="/some/dir")
        assert p.name == DEFAULT_MEMORY_FILE

    def test_no_args_uses_current_dir(self):
        p = resolve_memory_path()
        assert p.name == DEFAULT_MEMORY_FILE

    def test_returns_absolute_path(self):
        p = resolve_memory_path(cwd="relative/dir")
        assert p.is_absolute()

    def test_returns_path_object(self):
        assert isinstance(resolve_memory_path(), Path)


# ── load_memory ───────────────────────────────────────────────────────────────

class TestLoadMemory:
    def test_nonexistent_returns_empty(self):
        assert load_memory(Path("/nonexistent/xyz/file.md")) == ""

    def test_reads_existing_file(self, tmp_path):
        f = tmp_path / "mem.md"
        f.write_text("hello memory", encoding="utf-8")
        assert load_memory(f) == "hello memory"

    def test_reads_unicode(self, tmp_path):
        f = tmp_path / "mem.md"
        f.write_text("émojis 🧠 accents", encoding="utf-8")
        assert "🧠" in load_memory(f)

    def test_oserror_returns_empty(self):
        # A directory path triggers OSError on read_text
        with patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "read_text", side_effect=OSError("boom")):
            assert load_memory(Path("/x")) == ""


# ── format_memory_for_prompt ──────────────────────────────────────────────────

class TestFormatMemoryForPrompt:
    def test_empty_returns_empty(self):
        assert format_memory_for_prompt("") == ""

    def test_whitespace_returns_empty(self):
        assert format_memory_for_prompt("   \n  ") == ""

    def test_nonempty_contains_memory_keyword(self):
        result = format_memory_for_prompt("note: foo")
        assert "MEMORY" in result

    def test_nonempty_contains_content(self):
        result = format_memory_for_prompt("the answer is 42")
        assert "the answer is 42" in result

    def test_frames_memory_as_untrusted(self):
        # Durcissement red-team : la mémoire est cadrée comme NON FIABLE
        result = format_memory_for_prompt("x").lower()
        assert "untrusted" in result or "unverified" in result or "not facts" in result

    def test_says_remembered_instruction_not_a_command(self):
        result = format_memory_for_prompt("x").lower()
        assert "not a command" in result or "re-deriv" in result


# ── _format_entry ─────────────────────────────────────────────────────────────

class TestFormatEntry:
    def test_contains_task(self):
        entry = _format_entry("count functions", "13 found", timestamp="2026-01-01 00:00:00")
        assert "count functions" in entry

    def test_contains_answer(self):
        entry = _format_entry("t", "the result is X", timestamp="2026-01-01 00:00:00")
        assert "the result is X" in entry

    def test_contains_timestamp(self):
        entry = _format_entry("t", "a", timestamp="2026-01-01 12:34:56")
        assert "2026-01-01 12:34:56" in entry

    def test_starts_with_heading(self):
        entry = _format_entry("t", "a", timestamp="2026-01-01 00:00:00")
        assert entry.startswith("###")

    def test_answer_truncated(self):
        long_answer = "x" * 1000
        entry = _format_entry("t", long_answer, timestamp="2026-01-01 00:00:00")
        # MAX_ANSWER_CHARS = 500
        assert entry.count("x") <= 500

    def test_task_collapsed_to_oneline(self):
        entry = _format_entry("line1\n   line2\n\nline3", "a", timestamp="2026-01-01 00:00:00")
        # Multi-line task should be collapsed; no raw double-newline in the task line
        assert "line1 line2 line3" in entry

    def test_default_timestamp_used(self):
        # No timestamp → uses datetime.now(); just verify it produces a heading
        entry = _format_entry("t", "a")
        assert entry.startswith("###")
        assert "Task:" in entry


# ── _split_entries ────────────────────────────────────────────────────────────

class TestSplitEntries:
    def test_empty_returns_empty_list(self):
        assert _split_entries("") == []

    def test_whitespace_returns_empty_list(self):
        assert _split_entries("   \n  ") == []

    def test_single_entry(self):
        content = "### 2026-01-01\n**Task:** x\n**Result:** y"
        entries = _split_entries(content)
        assert len(entries) == 1

    def test_multiple_entries(self):
        content = (
            "### 2026-01-01\n**Task:** a\n**Result:** b"
            "\n---\n"
            "### 2026-01-02\n**Task:** c\n**Result:** d"
        )
        entries = _split_entries(content)
        assert len(entries) == 2

    def test_ignores_non_heading_blocks(self):
        content = "just some text\n---\n### 2026-01-01\n**Task:** x"
        entries = _split_entries(content)
        # Only the block starting with ### counts
        assert len(entries) == 1


# ── trim_memory ───────────────────────────────────────────────────────────────

class TestTrimMemory:
    def test_under_limit_unchanged(self):
        assert trim_memory([1, 2], max_entries=5) == [1, 2]

    def test_exact_limit_unchanged(self):
        assert trim_memory([1, 2, 3], max_entries=3) == [1, 2, 3]

    def test_over_limit_keeps_most_recent(self):
        assert trim_memory([1, 2, 3, 4, 5], max_entries=2) == [4, 5]

    def test_returns_new_list(self):
        original = [1, 2, 3]
        result = trim_memory(original, max_entries=5)
        assert result is not original

    def test_empty_list(self):
        assert trim_memory([], max_entries=5) == []

    def test_default_max_entries(self):
        # MAX_MEMORY_ENTRIES entries → unchanged
        items = list(range(MAX_MEMORY_ENTRIES))
        assert trim_memory(items) == items


# ── append_memory_entry ───────────────────────────────────────────────────────

class TestAppendMemoryEntry:
    def test_creates_file(self, tmp_path):
        p = tmp_path / "mem.md"
        ok = append_memory_entry(p, "do X", "did X", timestamp="2026-01-01 00:00:00")
        assert ok is True
        assert p.exists()

    def test_content_contains_task_and_answer(self, tmp_path):
        p = tmp_path / "mem.md"
        append_memory_entry(p, "compute sum", "sum is 10", timestamp="2026-01-01 00:00:00")
        content = load_memory(p)
        assert "compute sum" in content
        assert "sum is 10" in content

    def test_header_present(self, tmp_path):
        p = tmp_path / "mem.md"
        append_memory_entry(p, "t", "a", timestamp="2026-01-01 00:00:00")
        assert MEMORY_HEADER in load_memory(p)

    def test_appends_second_entry(self, tmp_path):
        p = tmp_path / "mem.md"
        append_memory_entry(p, "first task", "r1", timestamp="2026-01-01 00:00:00")
        append_memory_entry(p, "second task", "r2", timestamp="2026-01-02 00:00:00")
        content = load_memory(p)
        assert "first task" in content
        assert "second task" in content

    def test_header_not_duplicated(self, tmp_path):
        p = tmp_path / "mem.md"
        append_memory_entry(p, "t1", "r1", timestamp="2026-01-01 00:00:00")
        append_memory_entry(p, "t2", "r2", timestamp="2026-01-02 00:00:00")
        content = load_memory(p)
        assert content.count(MEMORY_HEADER) == 1

    def test_trims_to_max_entries(self, tmp_path):
        p = tmp_path / "mem.md"
        for i in range(MAX_MEMORY_ENTRIES + 5):
            append_memory_entry(
                p, f"task{i}", f"result{i}",
                timestamp=f"2026-01-{i + 1:02d} 00:00:00",
            )
        content = load_memory(p)
        # The first 5 tasks should have been trimmed out
        assert "task0\n" not in content and "**Task:** task0" not in content
        # The last task must be present
        assert f"task{MAX_MEMORY_ENTRIES + 4}" in content

    def test_respects_custom_max_entries(self, tmp_path):
        p = tmp_path / "mem.md"
        append_memory_entry(p, "t1", "r1", timestamp="2026-01-01 00:00:00", max_entries=2)
        append_memory_entry(p, "t2", "r2", timestamp="2026-01-02 00:00:00", max_entries=2)
        append_memory_entry(p, "t3", "r3", timestamp="2026-01-03 00:00:00", max_entries=2)
        content = load_memory(p)
        assert "**Task:** t1" not in content  # oldest trimmed
        assert "t2" in content
        assert "t3" in content

    def test_write_failure_returns_false(self, tmp_path):
        p = tmp_path / "mem.md"
        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            ok = append_memory_entry(p, "t", "a", timestamp="2026-01-01 00:00:00")
        assert ok is False

    def test_creates_parent_dirs(self, tmp_path):
        p = tmp_path / "nested" / "deep" / "mem.md"
        ok = append_memory_entry(p, "t", "a", timestamp="2026-01-01 00:00:00")
        assert ok is True
        assert p.exists()
