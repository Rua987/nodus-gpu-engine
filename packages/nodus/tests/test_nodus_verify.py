#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ TEMPLE IAM - Tests nodus_verify.py
⚡ Coverage target: 100%
Copyright © 2024 Temple IAM - All Rights Reserved
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from nodus_verify import (
    MAX_VERIFY_RETRIES,
    ObservedFileFilter,
    ReadPathTracker,
    carry_previous_path_targets,
    content_challenge,
    ensure_plan_has_write,
    ensure_plan_primary_arg_lookup,
    detect_primary_arg_tool,
    primary_arg_lookup_hint,
    force_primary_arg_plan_targets,
    force_primary_arg_grep_targets,
    execution_challenge,
    extract_expected_commands,
    extract_expected_files,
    invalid_content_files,
    normalize_plan_names,
    detect_edit_intent,
    detect_read_first,
    detect_list_first,
    detect_search_first,
    detect_final_exec,
    detect_exec_first,
    detect_verify_usage,
    detect_create_file,
    fix_first_step_bash,
    fix_first_step_grep_to_glob,
    fix_superfluous_grep_before_read,
    fix_bash_before_edit,
    fix_bash_write_to_write,
    fix_trailing_bash,
    fix_write_to_edit,
    fix_web_sequence,
    fix_duplicate_read_before_exec,
    ensure_discovery_before_edit,
    sibling_unexpected_files,
    task_requests_write,
    constraint_challenge,
    constraint_invalid_files,
    verification_challenge,
    verify_commands,
    verify_files,
)


# ── invalid_content_files (validation de contenu) ─────────────────────────────

class TestInvalidContentFiles:
    def test_empty_list(self):
        assert invalid_content_files([], cwd="/tmp") == []

    def test_valid_py_not_flagged(self, tmp_path):
        (tmp_path / "ok.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        assert invalid_content_files(["ok.py"], cwd=str(tmp_path)) == []

    def test_broken_py_flagged(self, tmp_path):
        (tmp_path / "bad.py").write_text("def f(:\n    pass\n", encoding="utf-8")
        assert invalid_content_files(["bad.py"], cwd=str(tmp_path)) == ["bad.py"]

    def test_valid_json_not_flagged(self, tmp_path):
        (tmp_path / "ok.json").write_text('{"a": 1}', encoding="utf-8")
        assert invalid_content_files(["ok.json"], cwd=str(tmp_path)) == []

    def test_broken_json_flagged(self, tmp_path):
        (tmp_path / "bad.json").write_text('{"a": 1', encoding="utf-8")
        assert invalid_content_files(["bad.json"], cwd=str(tmp_path)) == ["bad.json"]

    def test_other_extension_ignored(self, tmp_path):
        (tmp_path / "x.txt").write_text("def f(:", encoding="utf-8")  # invalide en py, mais .txt
        assert invalid_content_files(["x.txt"], cwd=str(tmp_path)) == []

    def test_missing_or_empty_ignored(self, tmp_path):
        (tmp_path / "empty.py").write_text("", encoding="utf-8")
        # absent ET vide → ignorés ici (gérés par verify_files)
        assert invalid_content_files(["empty.py", "absent.py"], cwd=str(tmp_path)) == []

    def test_non_utf8_py_flagged(self, tmp_path):
        (tmp_path / "bin.py").write_bytes(b"\xff\xfe\x00bad")
        assert invalid_content_files(["bin.py"], cwd=str(tmp_path)) == ["bin.py"]

    def test_absolute_path(self, tmp_path):
        p = tmp_path / "bad.py"
        p.write_text("def (:\n", encoding="utf-8")
        assert invalid_content_files([str(p)], cwd=str(tmp_path)) == [str(p)]


class TestExtractRenderVerb:
    def test_render_verb_now_tracked(self):
        # Gap A : "render out.png" était raté (render n'était pas un verbe d'écriture).
        assert "out.png" in extract_expected_files("render out.png from the scene")

    def test_export_verb_tracked(self):
        assert "mesh.stl" in extract_expected_files("export the mesh to mesh.stl")

    def test_verb_without_filename_still_empty(self):
        # Pas de faux positif : un verbe sans nom de fichier ne crée rien.
        assert extract_expected_files("render the scene and build the logic") == []


class TestContentChallenge:
    def test_mentions_files_and_invalid(self):
        msg = content_challenge(["a.py", "b.json"])
        assert "a.py" in msg and "b.json" in msg
        assert "not valid" in msg.lower()


# ── extract_expected_files ────────────────────────────────────────────────────

class TestExtractExpectedFiles:
    def test_empty_task(self):
        assert extract_expected_files("") == []

    def test_whitespace_task(self):
        assert extract_expected_files("   ") == []

    def test_no_write_verb(self):
        # 'read config.json' has no write verb → nothing expected
        assert extract_expected_files("just read config.json") == []

    def test_write_creates_file(self):
        assert extract_expected_files("write result.txt") == ["result.txt"]

    def test_create_keyword(self):
        assert extract_expected_files("create report.md now") == ["report.md"]

    def test_only_write_line_considered(self):
        # sample.py is read (no write verb on that line), result.txt is written
        task = '1. bash grep -c "^def " sample.py\n2. write result.txt'
        assert extract_expected_files(task) == ["result.txt"]

    def test_then_splits_read_from_write(self):
        task = (
            "Read nodus_plan_slotfill.py, then write _p0_scratch/primary_arg_bash.txt "
            "with exactly the primary argument name"
        )
        assert extract_expected_files(task) == ["_p0_scratch/primary_arg_bash.txt"]

    def test_french_verb(self):
        assert extract_expected_files("crée un fichier notes.txt") == ["notes.txt"]

    def test_dedup_preserves_order(self):
        task = "write a.txt and save a.txt and create b.md"
        assert extract_expected_files(task) == ["a.txt", "b.md"]

    def test_ignores_version_numbers(self):
        # "2.0" is not a filename (extension must be alpha and whitelisted)
        assert extract_expected_files("write version 2.0 stuff") == []

    def test_ignores_unknown_extension(self):
        # .xyz not in whitelist
        assert extract_expected_files("create data.xyz") == []

    def test_write_file_tool_mention(self):
        # 'write_file:' line should still capture the target
        assert extract_expected_files("write_file: create out.json") == ["out.json"]

    def test_multiple_extensions(self):
        task = "generate report.md and save data.csv and write log.txt"
        result = extract_expected_files(task)
        assert "report.md" in result
        assert "data.csv" in result
        assert "log.txt" in result

    def test_config_extension_conf(self):
        # Durcissement red-team : .conf était hors whitelist → évasion verify
        assert extract_expected_files("create settings.conf") == ["settings.conf"]

    def test_config_extension_env(self):
        assert extract_expected_files("write config.env file") == ["config.env"]

    def test_data_extension_sql(self):
        assert extract_expected_files("generate schema.sql") == ["schema.sql"]

    def test_code_extension_go(self):
        assert extract_expected_files("create main.go") == ["main.go"]

    def test_exotic_extension_still_a_limit(self):
        # Frontière heuristique assumée : .xyz reste non détecté (LIMIT honnête)
        assert extract_expected_files("create data.xyz") == []

    def test_ignores_python_command_after_create_segment(self):
        task = (
            r"Crée event_bus.py + test_event_bus.py ; "
            r"Lance python C:\Users\admin\nodus_sandbox\mini_pytest.py"
        )
        assert extract_expected_files(task) == ["event_bus.py", "test_event_bus.py"]

    def test_keeps_windows_absolute_file_when_written(self):
        task = r"write C:\Users\admin\nodus_sandbox\report.txt"
        assert extract_expected_files(task) == [r"C:\Users\admin\nodus_sandbox\report.txt"]

    def test_modify_verb_detects_test_file(self):
        task = "ajoute des tests dans test_offline_agent_validation.py"
        assert extract_expected_files(task) == ["test_offline_agent_validation.py"]

    def test_update_verb_detects_script(self):
        task = "mets a jour scripts/check_offline.py pour 14 tests"
        assert extract_expected_files(task) == ["scripts/check_offline.py"]

    def test_write_verb_in_path_not_matched(self):
        # 'compile' (verbe d'ecriture) dans 'compiler' (composant de chemin) ne
        # doit PAS activer la detection — meme classe que 'cat' dans 'locate'.
        task = r"Ticket: start npm run typecheck, followed by look for the string migration hash, then inspect D:\repos\compiler\orchestrator.json."
        assert extract_expected_files(task) == []

    def test_write_verb_next_to_path_still_detected(self):
        # Une veritable demande d'ecriture reste detectee meme a cote d'un chemin
        # contenant un verbe ('compiler') : segment 'read' ignore, segment 'write'
        # capture uniquement la cible reellement ecrite.
        task = r"read D:\repos\compiler\orchestrator.json then write report.json"
        assert extract_expected_files(task) == ["report.json"]


# ── extract_expected_commands ─────────────────────────────────────────────────

class TestExtractExpectedCommands:
    def test_empty_task_means_no_commands(self):
        assert extract_expected_commands("") == []
        assert extract_expected_commands("   ") == []

    def test_no_exit_zero_means_no_commands(self):
        assert extract_expected_commands("run python foo.py") == []

    def test_python_command_with_exit_zero(self):
        task = "3. bash python scripts/check_offline.py ; exit 0 obligatoire"
        assert extract_expected_commands(task) == ["python scripts/check_offline.py"]

    def test_executer_script_path(self):
        task = "Executer scripts/check_offline.py et prouver exit 0"
        assert extract_expected_commands(task) == ["python scripts/check_offline.py"]

    def test_natural_pytest_intent_without_exit_zero(self):
        # Langage réel : pas de "exit 0", mais "run pytest" + fichier de test.
        task = ("Create foo.py and add pytest tests in test_foo.py, "
                "then run pytest to check they pass.")
        assert extract_expected_commands(task) == ["python -m pytest test_foo.py"]

    def test_tests_pass_phrasing(self):
        task = "Write impl.py and test_impl.py and make sure the tests pass."
        assert extract_expected_commands(task) == ["python -m pytest test_impl.py"]

    def test_test_intent_without_named_file_is_empty(self):
        # Intention de test mais aucun fichier nommé → rien à lancer.
        assert extract_expected_commands("run the tests please") == []

    def test_pytest_form_dedups_python_invocation(self):
        # "python test_x.py" ne doit pas doubler la forme pytest (branche skip).
        task = "make sure tests pass: python test_x.py"
        assert extract_expected_commands(task) == ["python -m pytest test_x.py"]

    def test_pytest_form_dedups_script_invocation(self):
        # SCRIPT_CMD_RE (verbe exec + test_*.py) ne doit pas doubler non plus.
        task = "run pytest and run test_x.py"
        assert extract_expected_commands(task) == ["python -m pytest test_x.py"]


# ── verify_commands ───────────────────────────────────────────────────────────

class TestVerifyCommands:
    def test_empty_commands(self):
        assert verify_commands([]) == []

    def test_successful_command(self, tmp_path):
        script = tmp_path / "ok.py"
        script.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        cmd = f"python {script}"
        assert verify_commands([cmd], cwd=str(tmp_path)) == []

    def test_failed_command(self, tmp_path):
        script = tmp_path / "bad.py"
        script.write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
        cmd = f"python {script}"
        assert verify_commands([cmd], cwd=str(tmp_path)) == [cmd]


# ── ReadPathTracker ───────────────────────────────────────────────────────────

class TestReadPathTracker:
    def test_blocks_duplicate_read(self, tmp_path):
        target = tmp_path / "a.py"
        target.write_text("x", encoding="utf-8")
        tracker = ReadPathTracker(str(tmp_path), enabled=True)
        args = {"file_path": str(target)}
        assert tracker.check_duplicate_read(args) is None
        tracker.note_successful_read(args)
        assert tracker.check_duplicate_read(args) == str(target)

    def test_disabled_allows_duplicate(self, tmp_path):
        target = tmp_path / "a.py"
        target.write_text("x", encoding="utf-8")
        tracker = ReadPathTracker(str(tmp_path), enabled=False)
        args = {"file_path": str(target)}
        tracker.note_successful_read(args)
        assert tracker.check_duplicate_read(args) is None


# ── execution_challenge ───────────────────────────────────────────────────────

class TestExecutionChallenge:
    def test_names_failed_command(self):
        msg = execution_challenge(["python scripts/check_offline.py"])
        assert "check_offline.py" in msg
        assert "exit 0" in msg


# ── verify_files ──────────────────────────────────────────────────────────────

class TestVerifyFiles:
    def test_empty_expected(self):
        assert verify_files([]) == []

    def test_all_present(self, tmp_path):
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        assert verify_files(["a.txt"], cwd=str(tmp_path)) == []

    def test_missing_reported(self, tmp_path):
        assert verify_files(["ghost.txt"], cwd=str(tmp_path)) == ["ghost.txt"]

    def test_mixed_present_and_missing(self, tmp_path):
        (tmp_path / "here.txt").write_text("x", encoding="utf-8")
        missing = verify_files(["here.txt", "gone.md"], cwd=str(tmp_path))
        assert missing == ["gone.md"]

    def test_absolute_path(self, tmp_path):
        f = tmp_path / "abs.txt"
        f.write_text("x", encoding="utf-8")
        # absolute path is used as-is
        assert verify_files([str(f)], cwd="/some/other/dir") == []

    def test_no_cwd_uses_current_dir(self):
        # A clearly-missing file resolved against current dir
        assert verify_files(["__definitely_missing_12345.txt"]) == [
            "__definitely_missing_12345.txt"
        ]

    def test_empty_file_treated_as_missing(self, tmp_path):
        # Durcissement red-team : un fichier VIDE ne satisfait pas la post-condition
        (tmp_path / "empty.txt").write_text("", encoding="utf-8")
        assert verify_files(["empty.txt"], cwd=str(tmp_path)) == ["empty.txt"]

    def test_nonempty_file_satisfies(self, tmp_path):
        (tmp_path / "full.txt").write_text("42", encoding="utf-8")
        assert verify_files(["full.txt"], cwd=str(tmp_path)) == []


# ── verification_challenge ────────────────────────────────────────────────────

class TestVerificationChallenge:
    def test_contains_filename(self):
        assert "result.txt" in verification_challenge(["result.txt"])

    def test_mentions_write_file(self):
        assert "write_file" in verification_challenge(["x.txt"])

    def test_exact_directive(self):
        msg = verification_challenge(["_p0_scratch/found.txt"])
        assert "EXACTLY" in msg
        assert "file_path = '_p0_scratch/found.txt'" in msg or 'file_path = "_p0_scratch/found.txt"' in msg
        assert "bash" in msg.lower()

    def test_wrong_siblings_mentioned(self):
        msg = verification_challenge(
            ["_p0_scratch/found.txt"],
            unexpected_siblings=["_p0_scratch/_find_x.py"],
        )
        assert "_find_x.py" in msg
        assert "WRONG" in msg

    def test_multiple_files(self):
        msg = verification_challenge(["a.txt", "b.md"])
        assert "a.txt" in msg
        assert "b.md" in msg

    def test_returns_string(self):
        assert isinstance(verification_challenge(["x.txt"]), str)


class TestSiblingUnexpectedFiles:
    def test_lists_wrong_neighbor(self, tmp_path):
        d = tmp_path / "out"
        d.mkdir()
        (d / "wrong.py").write_text("x", encoding="utf-8")
        got = sibling_unexpected_files(
            ["out/found.txt"],
            ["out/found.txt"],
            cwd=str(tmp_path),
        )
        assert any("wrong.py" in g for g in got)

    def test_empty_when_no_parent(self, tmp_path):
        assert sibling_unexpected_files(
            ["missing/nope.txt"], ["missing/nope.txt"], cwd=str(tmp_path)
        ) == []


# ── constants ─────────────────────────────────────────────────────────────────

class TestObservedFileFilter:
    def test_filters_after_read_file(self, tmp_path):
        target = tmp_path / "mini_pytest.py"
        target.write_text("x", encoding="utf-8")
        filt = ObservedFileFilter(str(tmp_path))
        filt.note_tool_success(
            "read_file",
            {"file_path": str(target)},
        )
        missing = filt.filter_missing(["mini_pytest.py"])
        assert missing == []

    def test_filters_truncated_windows_path(self, tmp_path):
        target = tmp_path / "mini_pytest.py"
        target.write_text("x", encoding="utf-8")
        filt = ObservedFileFilter(str(tmp_path))
        filt.note_tool_success(
            "read_file",
            {"file_path": str(target)},
        )
        truncated = str(target).split(":\\", 1)[-1]  # Users\admin\...\mini_pytest.py
        missing = filt.filter_missing([truncated])
        assert missing == []


class TestConstants:
    def test_max_verify_retries_positive(self):
        assert isinstance(MAX_VERIFY_RETRIES, int)
        assert MAX_VERIFY_RETRIES > 0


# ── Couverture des branches restantes (reprise du WIP) ────────────────────────

class TestExtractEdgeCases:
    def test_python_run_target_not_a_created_file(self):
        # Un fichier seulement EXECUTE (python b.py) dans un segment d'ecriture
        # ne doit pas etre compte comme attendu en creation.
        res = extract_expected_files("create a.txt then run python b.py")
        assert "a.txt" in res
        assert "b.py" not in res

    def test_ps1_script_becomes_powershell_command(self):
        # Branche .ps1 : exit 0 + verbe d'exec + script scripts/*.ps1
        res = extract_expected_commands("run scripts/build.ps1 and it must exit 0")
        assert "powershell -NoProfile -File scripts/build.ps1" in res


class TestEnsurePlanHasWrite:
    def test_appends_when_task_writes(self):
        assert ensure_plan_has_write(
            ["read_file", "grep"],
            "read a.py then write out.txt",
        ) == ["read_file", "grep", "write_file"]

    def test_noop_when_write_present(self):
        assert ensure_plan_has_write(["grep", "write_file"], "write out.txt") == [
            "grep", "write_file",
        ]

    def test_noop_when_no_write_intent(self):
        assert ensure_plan_has_write(["read_file"], "just read a.py") == ["read_file"]

    def test_noop_when_write_verb_only_in_path(self):
        # Regression f92/f94 du holdout v3 frais : 'compile' dans le chemin
        # D:\repos\compiler\... ne doit pas append write_file au plan.
        task = (
            r"Ticket: start npm run typecheck, followed by look for the string "
            r"migration hash, then inspect D:\repos\compiler\orchestrator.json."
        )
        assert ensure_plan_has_write(
            ["bash", "grep", "read_file"], task,
        ) == ["bash", "grep", "read_file"]

    def test_task_requests_write(self):
        assert task_requests_write("write out.txt") is True
        assert task_requests_write("just read a.py") is False

    def test_make_fresh_file_detected(self):
        assert detect_create_file(
            "Make a fresh file called deploy_notes.txt with the word pending inside.") is True
        assert task_requests_write(
            "Make a fresh file called deploy_notes.txt with the word pending inside.") is True
        assert detect_create_file("Run the unit tests with pytest") is False
        assert detect_create_file("make the new tests pass") is False


class TestPrimaryArgLookup:
    _TASK = (
        "Read nodus_plan_slotfill.py, then write out.txt with exactly "
        "the primary argument name used for the bash tool (one word, no quotes)."
    )

    def test_detect_bash(self):
        assert detect_primary_arg_tool(self._TASK) == "bash"

    def test_detect_none(self):
        assert detect_primary_arg_tool("write hello.txt") is None

    def test_ensure_inserts_grep_and_write(self):
        assert ensure_plan_primary_arg_lookup(["read_file"], self._TASK) == [
            "read_file", "grep", "write_file",
        ]

    def test_hint_mentions_primary_arg_not_answer(self):
        hint = primary_arg_lookup_hint(self._TASK)
        assert hint is not None
        assert '"bash"' in hint
        assert "KEY" in hint
        assert "VALUE" in hint
        assert "command" not in hint.lower()  # ne pas souffler la reponse
        # Ancien motif PRIMARY_ARG ne montre pas la VALUE — ne plus le recommander
        assert "pattern PRIMARY_ARG" not in hint

    def test_key_as_value_detected(self):
        from nodus_verify import is_primary_arg_key_as_value
        assert is_primary_arg_key_as_value("bash", self._TASK) is True
        assert is_primary_arg_key_as_value("command", self._TASK) is False

    def test_force_grep_overwrites_slotfill_junk(self):
        got = force_primary_arg_plan_targets(
            ["read_file", "grep", "write_file"],
            [None, "pattern", None],
            self._TASK,
        )
        assert got[1] == '"bash"'
        assert got[2] == "out.txt"

    def test_force_write_prefers_primary_name(self):
        task = (
            "Read x.py, then write _p0_scratch/primary_arg_bash.txt with exactly "
            "the primary argument name used for the bash tool (one word)."
        )
        got = force_primary_arg_plan_targets(
            ["read_file", "grep", "write_file"],
            ["x.py", "None", "wrong.txt"],
            task,
        )
        assert got == ["x.py", '"bash"', "_p0_scratch/primary_arg_bash.txt"]

    def test_alias_grep_targets(self):
        got = force_primary_arg_grep_targets(
            ["grep", "write_file"],
            ["pattern", None],
            self._TASK,
        )
        assert got[0] == '"bash"'
        assert got[1] == "out.txt"


class TestFindSymbolLookup:
    _TASK = (
        "Search the codebase for the function estimate_task_steps, then write "
        "found.txt with exactly the filename (basename only) that defines it."
    )

    def test_detect(self):
        from nodus_verify import detect_find_symbol, find_symbol_grep_pattern
        assert detect_find_symbol(self._TASK) == ("function", "estimate_task_steps")
        assert find_symbol_grep_pattern(self._TASK) == "def estimate_task_steps"

    def test_force_overwrites_scratch_path_as_pattern(self):
        from nodus_verify import force_find_symbol_plan_targets
        got = force_find_symbol_plan_targets(
            ["grep", "write_file"],
            ["_p0_scratch/found.txt", None],
            self._TASK,
        )
        assert got[0] == "def estimate_task_steps"
        assert got[1] == "found.txt"

    def test_skips_primary_arg_tasks(self):
        from nodus_verify import force_find_symbol_plan_targets
        task = (
            "Read f.py then write out.txt with the primary argument name "
            "used for the bash tool"
        )
        got = force_find_symbol_plan_targets(
            ["grep", "write_file"], ["x", None], task
        )
        assert got == ["x", None]

    def test_hint_no_filename_spoil(self):
        from nodus_verify import find_symbol_lookup_hint
        hint = find_symbol_lookup_hint(self._TASK)
        assert hint is not None
        assert "def estimate_task_steps" in hint
        assert "nodus_planner" not in hint


class TestObservedFileFilterEdges:
    def test_resolve_path_none_or_empty(self):
        f = ObservedFileFilter()
        assert f.resolve_path(None) is None
        assert f.resolve_path("") is None

    def test_resolve_path_invalid_returns_none(self):
        # Octet nul -> Path.resolve leve (3.11) / tolere (3.13). Le CONTRAT qui
        # compte : resolve_path ne leve JAMAIS et renvoie str|None (jamais crash).
        for bad in ("a\x00b", None, ""):
            out = ObservedFileFilter().resolve_path(bad)
            assert out is None or isinstance(out, str)

    def test_note_tool_success_ignores_non_file_tools(self):
        f = ObservedFileFilter()
        f.note_tool_success("bash", {"command": "ls"})
        assert f.observed == set()

    def test_empty_write_not_observed(self, tmp_path):
        f = ObservedFileFilter(str(tmp_path))
        f.note_tool_success(
            "write_file",
            {"file_path": "out.txt", "content": ""},
        )
        assert f.observed == set()
        assert f.filter_missing(["out.txt"]) == ["out.txt"]

    def test_nonempty_write_is_observed(self, tmp_path):
        f = ObservedFileFilter(str(tmp_path))
        f.note_tool_success(
            "write_file",
            {"file_path": "out.txt", "content": "command\n"},
        )
        assert f.filter_missing(["out.txt"]) == []


class TestConstraintInvalidFiles:
    def test_one_word_rejects_sentence(self, tmp_path):
        f = tmp_path / "out.txt"
        f.write_text("NODUS NANOCHAT DEPLOYMENT\n", encoding="utf-8")
        task = "write out.txt with exactly the name (one word, no quotes)"
        assert constraint_invalid_files(["out.txt"], task, cwd=str(tmp_path)) == ["out.txt"]

    def test_one_word_accepts_single_token(self, tmp_path):
        f = tmp_path / "out.txt"
        f.write_text("command\n", encoding="utf-8")
        task = "write out.txt (one word)"
        assert constraint_invalid_files(["out.txt"], task, cwd=str(tmp_path)) == []

    def test_no_constraint_without_one_word(self, tmp_path):
        f = tmp_path / "out.txt"
        f.write_text("many words here\n", encoding="utf-8")
        assert constraint_invalid_files(["out.txt"], "write out.txt", cwd=str(tmp_path)) == []

    def test_challenge_mentions_one_word(self):
        msg = constraint_challenge(["out.txt"], "write out.txt (one word)")
        assert "one word" in msg.lower()
        assert "out.txt" in msg

    def test_basename_rejects_sentence(self, tmp_path):
        from nodus_verify import is_valid_basename_py, needs_basename_constraint
        task = (
            "Search for the function estimate_task_steps, then write found.txt "
            "with exactly the filename (basename only) that defines it."
        )
        assert needs_basename_constraint(task) is True
        assert is_valid_basename_py("Found 10 steps") is False
        (tmp_path / "found.txt").write_text("Found 10 steps.\n", encoding="utf-8")
        assert constraint_invalid_files(["found.txt"], task, cwd=str(tmp_path)) == [
            "found.txt"
        ]

    def test_basename_accepts_py(self, tmp_path):
        task = (
            "Search for the function foo, then write found.txt with exactly "
            "the filename (basename only) that defines it."
        )
        (tmp_path / "found.txt").write_text("nodus_planner.py\n", encoding="utf-8")
        assert constraint_invalid_files(["found.txt"], task, cwd=str(tmp_path)) == []

    def test_basename_challenge_no_spoil(self):
        msg = constraint_challenge(
            ["found.txt"],
            "write found.txt with the filename (basename only) that defines it",
        )
        assert "basename" in msg.lower()
        assert "nodus_planner" not in msg


# ── carry_previous_path_targets (P1-A1) ───────────────────────────────────────

class TestCarryPreviousPathTargets:
    def test_read_edit_carries_target(self):
        # y04/z-series : la cible du edit_file vient du read precedent.
        assert carry_previous_path_targets(
            ["read_file", "edit_file"],
            ["server.py", None],
            "read server.py, then change the port from 8080 to 3000",
        ) == ["server.py", "server.py"]

    def test_new_file_write_not_overwritten(self):
        # Ecriture d'un fichier NEUF distinct (b.txt) : on ne colle pas a.py.
        assert carry_previous_path_targets(
            ["read_file", "write_file"],
            ["a.py", None],
            "read a.py, then write b.txt",
        ) == ["a.py", None]

    def test_glob_edit_carries_target(self):
        assert carry_previous_path_targets(
            ["glob", "edit_file"],
            ["src/*.py", None],
            "glob src files, then adjust the config in the matching file",
        ) == ["src/*.py", "src/*.py"]

    def test_existing_edit_target_not_overwritten(self):
        # Cible deja remplie : jamais ecrasee par le carry.
        assert carry_previous_path_targets(
            ["read_file", "edit_file"],
            ["a.py", "b.py"],
            "read a.py then edit b.py",
        ) == ["a.py", "b.py"]

    def test_write_then_edit_carries(self):
        # write_file est aussi producteur de chemin (relecture pour editer).
        assert carry_previous_path_targets(
            ["write_file", "edit_file"],
            ["a.py", None],
            "create a.py then edit the file",
        ) == ["a.py", "a.py"]

    def test_empty_names(self):
        assert carry_previous_path_targets([], [], "") == []

    def test_targets_shortened_padded(self):
        # targets plus court que names : padde a None puis porte.
        got = carry_previous_path_targets(
            ["read_file", "edit_file"],
            ["server.py"],
            "read server.py then change the port",
        )
        assert got == ["server.py", "server.py"]

    def test_none_target_does_not_start_carry(self):
        # Pas de cible de read → rien a porter.
        assert carry_previous_path_targets(
            ["read_file", "edit_file"],
            [None, None],
            "read the found file then edit it",
        ) == [None, None]

    def test_no_producer_edit_stays_none(self):
        assert carry_previous_path_targets(
            ["edit_file"], [None], "edit config.yaml"
        ) == [None]

    def test_idempotent(self):
        names = ["read_file", "edit_file"]
        tg = ["server.py", None]
        task = "read server.py then change the port from 8080 to 3000"
        once = carry_previous_path_targets(names, tg, task)
        assert carry_previous_path_targets(names, once, task) == once

    def test_len_preserved(self):
        names = ["read_file", "grep", "edit_file", "write_file"]
        tg = ["a.py", None, None, None]
        out = carry_previous_path_targets(names, tg, "read a.py then write b.txt")
        assert len(out) == len(names)


# ── normalize_plan_names : 19 échecs probe v2b → gold (0 €, CPU) ───────────────

class TestNormalizePlanNames:
    """Un test par échec exact_plan du probe v2b (n=100, greedy)."""

    def test_p04_bash_head_to_read(self):
        assert normalize_plan_names(["bash", "edit_file"],
            "Open server.py, then change the port from 8080 to 3000.") == ["read_file", "edit_file"]

    def test_y13_bash_head_to_read(self):
        assert normalize_plan_names(["bash", "bash"],
            "Read Makefile first, then invoke make test.") == ["read_file", "bash"]

    def test_z04_bash_head_to_glob(self):
        assert normalize_plan_names(["bash", "read_file", "bash"],
            "Enumerate the .ini configs, read logging.ini, then raise the log level to WARNING.") == ["glob", "read_file", "edit_file"]

    def test_z11_grep_to_glob(self):
        assert normalize_plan_names(["grep", "read_file", "bash"],
            "Locate the benchmark scripts, read the io-heavy one, then execute it.") == ["glob", "read_file", "bash"]

    def test_z06_trailing_bash_to_edit(self):
        assert normalize_plan_names(["bash", "read_file", "bash"],
            "Run the type checker, open the file it flags, then fix the annotation.") == ["bash", "read_file", "edit_file"]

    def test_z15_trailing_bash_to_edit(self):
        assert normalize_plan_names(["bash", "read_file", "bash"],
            "Run the linter, open the worst offender it reports, then clean up the unused imports.") == ["bash", "read_file", "edit_file"]

    def test_z02_trailing_bash_to_edit(self):
        assert normalize_plan_names(["grep", "read_file", "bash"],
            "Find where the timezone bug lives, read that module, then correct the offset.") == ["grep", "read_file", "edit_file"]

    def test_z12_trailing_bash_to_edit(self):
        assert normalize_plan_names(["grep", "read_file", "bash"],
            "Search for the misspelled label Recieved, open the template, then fix the spelling.") == ["grep", "read_file", "edit_file"]

    def test_y26_trailing_bash_to_edit(self):
        assert normalize_plan_names(["glob", "bash"],
            "Find the changelog files, then append an Unreleased section to the newest.") == ["glob", "edit_file"]

    def test_y18_trailing_bash_parasite_removed(self):
        assert normalize_plan_names(["edit_file", "bash"],
            "Look at settings.ini, then flip verbose to off.") == ["read_file", "edit_file"]

    def test_y14_trailing_bash_to_grep(self):
        assert normalize_plan_names(["write_file", "bash"],
            "Add a module orbit_tracker.py, then verify nothing else already uses that name.") == ["write_file", "grep"]

    def test_y04_discovery_before_edit(self):
        assert normalize_plan_names(["edit_file"],
            "Inspect nginx.conf first, then bump worker_connections to 2048.") == ["read_file", "edit_file"]

    def test_y22_discovery_grep_before_edit(self):
        assert normalize_plan_names(["edit_file", "bash"],
            "Locate every console.log left in production code, then delete one with an edit.") == ["grep", "edit_file"]

    def test_y10_write_to_edit(self):
        assert normalize_plan_names(["glob", "write_file"],
            "Find the .env.example files, then add a DATABASE_URL line to the first one.") == ["glob", "edit_file"]

    def test_p15_brave_to_fetch(self):
        assert normalize_plan_names(["brave_search", "read_file"],
            "Search online for duckdb vs sqlite 2026, then open one of the result URLs.") == ["brave_search", "web_fetch"]

    def test_y30_grep_to_brave(self):
        assert normalize_plan_names(["grep", "web_fetch"],
            "Search for the official tokio tutorial, then pull down that page.") == ["brave_search", "web_fetch"]

    def test_y19_truncate_write_after_fetch(self):
        assert normalize_plan_names(["brave_search", "web_fetch", "write_file"],
            "Find the URL of the pnpm migration guide online, then fetch it.") == ["brave_search", "web_fetch"]

    def test_z10_read_read_bash_to_edit(self):
        assert normalize_plan_names(["bash", "read_file", "bash"],
            "Open the cron schedule file, move the nightly job to 02:30, then reload the scheduler from the shell.") == ["read_file", "edit_file", "bash"]

    def test_z18_read_read_bash_to_edit(self):
        assert normalize_plan_names(["bash", "read_file", "bash"],
            "Read the feature toggle file, enable beta_dashboard, then restart the service via shell.") == ["read_file", "edit_file", "bash"]

    def test_x02_superfluous_grep_before_read(self):
        assert normalize_plan_names(["grep", "read_file"],
            "Print the source of D:\\studio\\melody\\composer.rb so I can review it.") == ["read_file"]

    def test_x07_bash_to_write_pipeline(self):
        task = "Make a fresh file called deploy_notes.txt with the word pending inside."
        assert normalize_plan_names(
            ensure_plan_primary_arg_lookup(["bash"], task), task) == ["write_file"]

    def test_x08_superfluous_bash_before_edit(self):
        assert normalize_plan_names(["bash", "edit_file"],
            "In docker-compose.yml, swap restart: always for restart: unless-stopped.") == ["edit_file"]


class TestNormalizePlanNamesNoRegression:
    """Cas CORRECTS risqués : normalize(gold, task) == gold (no-op)."""

    def test_s08(self):
        assert normalize_plan_names(["edit_file"],
            "In config.yaml, replace debug: true with debug: false.") == ["edit_file"]

    def test_x08(self):
        assert normalize_plan_names(["edit_file"],
            "In docker-compose.yml, swap restart: always for restart: unless-stopped.") == ["edit_file"]

    def test_x16(self):
        assert normalize_plan_names(["edit_file"],
            "Change the constant MAX_RETRIES from 3 to 5 in retry.go.") == ["edit_file"]

    def test_t06(self):
        assert normalize_plan_names(["bash", "read_file", "edit_file"],
            "Run git diff, open a changed file, then edit it to remove a debug print.") == ["bash", "read_file", "edit_file"]

    def test_p07(self):
        assert normalize_plan_names(["bash", "read_file"],
            "Run git status, then open the first modified file you care about.") == ["bash", "read_file"]

    def test_y05(self):
        assert normalize_plan_names(["brave_search", "web_fetch"],
            "Google the changelog for redis 8, then download the page you found.") == ["brave_search", "web_fetch"]

    def test_z09(self):
        assert normalize_plan_names(["grep", "write_file", "bash"],
            "Grep for functions missing docstrings, write a coverage report file, then run the docs build.") == ["grep", "write_file", "bash"]

    def test_z01(self):
        assert normalize_plan_names(["glob", "read_file", "bash"],
            "List the .spec.ts files, open checkout.spec.ts, then run the jest suite.") == ["glob", "read_file", "bash"]

    def test_p12(self):
        assert normalize_plan_names(["write_file", "glob"],
            "Create a new README.md, then verify it exists by listing *.md files.") == ["write_file", "glob"]

    def test_t07(self):
        assert normalize_plan_names(["glob", "grep", "write_file"],
            "Find all *.rs files, search for unwrap(), then write a short note.md listing the hits.") == ["glob", "grep", "write_file"]

    def test_z16(self):
        assert normalize_plan_names(["glob", "grep", "write_file"],
            "Gather the .css files, hunt for !important, then save overrides_report.txt summarizing them.") == ["glob", "grep", "write_file"]

    def test_y20(self):
        assert normalize_plan_names(["glob", "grep"],
            "Gather the .tf files, then check them for aws_s3_bucket.") == ["glob", "grep"]

    def test_y29(self):
        assert normalize_plan_names(["grep", "read_file"],
            "Search for the feature flag darkMode, then read the component that uses it.") == ["grep", "read_file"]

    def test_grep_read_search_intent_stays(self):
        # securite x02 : tache de RECHERCHE -> grep de tete LEGITIME, non retire.
        assert normalize_plan_names(["grep", "read_file"],
            "Search for the function parse_invoice, then read the file that defines it.") == ["grep", "read_file"]

    def test_bash_edit_exec_first_stays(self):
        # securite x08 : 1re clause EXEC -> bash de tete LEGITIME, non retire.
        assert normalize_plan_names(["bash", "edit_file"],
            "Run the type checker, open the file it flags, then fix the annotation.") == ["bash", "edit_file"]


class TestNormalizeIdempotent:
    """normalize(normalize(x)) == normalize(x)."""

    @pytest.mark.parametrize("names, task", [
        (["bash", "edit_file"], "Open server.py, then change the port from 8080 to 3000."),
        (["edit_file"], "Inspect nginx.conf first, then bump worker_connections to 2048."),
        (["glob", "bash"], "Find the changelog files, then append an Unreleased section to the newest."),
        (["edit_file", "bash"], "Locate every console.log left in production code, then delete one with an edit."),
        (["brave_search", "web_fetch", "write_file"], "Find the URL of the pnpm migration guide online, then fetch it."),
        (["bash", "read_file", "bash"], "Open the cron schedule file, move the job, then reload the scheduler."),
        (["glob", "grep", "write_file"], "Find all *.rs files, search for unwrap(), then write a note.md."),
    ])
    def test_idempotent(self, names, task):
        once = normalize_plan_names(list(names), task)
        assert normalize_plan_names(once, task) == once

    def test_empty_input(self):
        assert normalize_plan_names([], "any task") == []


class TestDetectPredicates:
    def test_read_first_positive(self):
        assert detect_read_first("Inspect nginx.conf first, then bump workers to 2048")
        assert detect_read_first("Read Makefile first, then invoke make test.")

    def test_read_first_negative(self):
        assert not detect_read_first("Run git status, then open the first modified file")
        # "cat" est une sous-chaine de "locate" : ne doit PAS matcher (mot entier).
        assert not detect_read_first("Locate every console.log left in production code")

    def test_list_first_positive(self):
        assert detect_list_first("Enumerate the .ini configs, read logging.ini")
        assert detect_list_first("Find every .java file, search them for synchronized")

    def test_list_first_negative(self):
        assert not detect_list_first("Find the hardcoded API key in the sources")

    def test_search_first_positive(self):
        assert detect_search_first("Locate every console.log left in production code")
        assert detect_search_first("Search for the misspelled label Recieved")

    def test_search_first_negative(self):
        assert not detect_search_first("Locate the benchmark scripts")

    def test_exec_first_positive(self):
        assert detect_exec_first("Run git status, then open the first modified file")
        assert detect_exec_first("Run make build, then check the binary.")
        assert detect_exec_first("Run the deploy script, then write the output to results.txt.")

    def test_exec_first_negative(self):
        # "make a/the ... file" = creation, PAS un exec make (lookahead).
        assert not detect_exec_first(
            "Make a fresh file called deploy_notes.txt with the word pending inside.")
        assert not detect_exec_first("Make a new file called notes.md with a TODO list.")
        assert not detect_exec_first("In docker-compose.yml, swap restart: always for restart: unless-stopped.")
        assert not detect_exec_first("Open server.py, then change the port to 3000.")

    def test_edit_intent(self):
        assert detect_edit_intent("Open server.py, then change the port to 3000")
        assert detect_edit_intent("then delete one with an edit")
        assert not detect_edit_intent("Run the unit tests with pytest")

    def test_final_exec(self):
        assert detect_final_exec("Open the cron file, then reload the scheduler from the shell")
        assert not detect_final_exec("Look at settings.ini, then flip verbose to off")

    def test_verify_usage(self):
        assert detect_verify_usage("Add orbit_tracker.py, then verify nothing else uses that name")
        assert not detect_verify_usage("Look at settings.ini, then flip verbose to off")


class TestFixFunctions:
    def test_fix_first_step_bash_read(self):
        assert fix_first_step_bash(["bash", "edit_file"],
            "Open server.py, then change the port to 3000.") == ["read_file", "edit_file"]

    def test_fix_first_step_bash_glob(self):
        assert fix_first_step_bash(["bash", "bash"],
            "Enumerate the .ini configs, then read logging.ini.") == ["glob", "bash"]

    def test_fix_first_step_bash_noop_exec_first(self):
        assert fix_first_step_bash(["bash", "read_file"],
            "Run git status, then open the first modified file you care about.") == ["bash", "read_file"]

    def test_fix_first_step_grep_to_glob(self):
        assert fix_first_step_grep_to_glob(["grep", "read_file", "bash"],
            "Locate the benchmark scripts, read the io-heavy one, then execute it.") == ["glob", "read_file", "bash"]

    def test_fix_first_step_grep_to_glob_noop_chain(self):
        assert fix_first_step_grep_to_glob(["grep", "read_file"],
            "Locate every console.log left in production code, then read the file.") == ["grep", "read_file"]

    def test_fix_trailing_bash_to_edit(self):
        assert fix_trailing_bash(["grep", "read_file", "bash"],
            "Find where the timezone bug lives, read that module, then correct the offset.") == ["grep", "read_file", "edit_file"]

    def test_fix_trailing_bash_parasite_removed(self):
        assert fix_trailing_bash(["edit_file", "bash"],
            "Look at settings.ini, then flip verbose to off.") == ["edit_file"]

    def test_fix_trailing_bash_to_grep(self):
        assert fix_trailing_bash(["write_file", "bash"],
            "Add a module orbit_tracker.py, then verify nothing else already uses that name.") == ["write_file", "grep"]

    def test_fix_trailing_bash_keep_exec(self):
        assert fix_trailing_bash(["read_file", "bash"],
            "Read Makefile first, then invoke make test.") == ["read_file", "bash"]

    def test_fix_write_to_edit_anaphora(self):
        assert fix_write_to_edit(["glob", "write_file"],
            "Find the .env.example files, then add a DATABASE_URL line to the first one.") == ["glob", "edit_file"]

    def test_fix_write_to_edit_keep_new_named(self):
        assert fix_write_to_edit(["write_file", "glob"],
            "Create a new README.md, then verify it exists by listing *.md files.") == ["write_file", "glob"]

    def test_fix_write_to_edit_keep_named_output(self):
        # z07/z16 : la tâche nomme un fichier de sortie neuf -> write_file garde.
        assert fix_write_to_edit(["glob", "grep", "write_file"],
            "Find every .java file, search them for synchronized, then write audit_locks.md with the findings.") == ["glob", "grep", "write_file"]

    def test_fix_web_sequence_brave_to_fetch(self):
        assert fix_web_sequence(["brave_search", "read_file"],
            "Search online for duckdb vs sqlite 2026, then open one of the result URLs.") == ["brave_search", "web_fetch"]

    def test_fix_web_sequence_grep_to_brave(self):
        assert fix_web_sequence(["grep", "web_fetch"],
            "Search for the official tokio tutorial, then pull down that page.") == ["brave_search", "web_fetch"]

    def test_fix_web_sequence_truncate_write(self):
        assert fix_web_sequence(["brave_search", "web_fetch", "write_file"],
            "Find the URL of the pnpm migration guide online, then fetch it.") == ["brave_search", "web_fetch"]

    def test_fix_duplicate_read_before_exec(self):
        assert fix_duplicate_read_before_exec(["read_file", "read_file", "bash"],
            "Open the cron schedule file, move the nightly job to 02:30, then reload the scheduler.") == ["read_file", "edit_file", "bash"]

    def test_ensure_discovery_before_edit_insert_read(self):
        assert ensure_discovery_before_edit(["edit_file"],
            "Inspect nginx.conf first, then bump worker_connections to 2048.", max_len=2) == ["read_file", "edit_file"]

    def test_ensure_discovery_before_edit_noop(self):
        assert ensure_discovery_before_edit(["read_file", "edit_file"],
            "Open server.py, then change the port to 3000.", max_len=2) == ["read_file", "edit_file"]

    def test_fix_superfluous_grep_before_read(self):
        assert fix_superfluous_grep_before_read(["grep", "read_file"],
            "Print the source of D:\\studio\\melody\\composer.rb so I can review it.") == ["read_file"]

    def test_fix_superfluous_grep_before_read_noop_search(self):
        assert fix_superfluous_grep_before_read(["grep", "read_file"],
            "Search for the function parse_invoice, then read the file that defines it.") == ["grep", "read_file"]

    def test_fix_bash_before_edit(self):
        assert fix_bash_before_edit(["bash", "edit_file"],
            "In docker-compose.yml, swap restart: always for restart: unless-stopped.") == ["edit_file"]

    def test_fix_bash_before_edit_noop_exec_first(self):
        assert fix_bash_before_edit(["bash", "edit_file"],
            "Run the type checker, open the file it flags, then fix the annotation.") == ["bash", "edit_file"]

    def test_fix_bash_write_to_write(self):
        assert fix_bash_write_to_write(["bash", "write_file"],
            "Make a fresh file called deploy_notes.txt with the word pending inside.") == ["write_file"]

    def test_fix_bash_write_to_write_noop_exec_first(self):
        assert fix_bash_write_to_write(["bash", "write_file"],
            "Run the deploy script, then write the output to results.txt.") == ["bash", "write_file"]
