#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ TEMPLE IAM - Tests nodus_tools.py
⚡ Coverage target: 100%
Copyright © 2024 Temple IAM - All Rights Reserved
"""

import socket
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from nodus_tools import (
    BRAVE_API_KEY,
    DEFAULT_TIMEOUT,
    MAX_FETCH_CHARS,
    MAX_GLOB_RESULTS,
    MAX_GREP_RESULTS,
    MAX_OUTPUT_CHARS,
    MAX_SEARCH_RESULTS,
    MAX_TIMEOUT,
    ToolResult,
    _anchor,
    _confine,
    _find_actual_string,
    _find_similar,
    _is_blocked_url,
    _is_destructive,
    _normalize_command,
    _normalize_quotes,
    _protected_reference_error,
    _rewrite_windows_powershell,
    _resolve_file_path,
    _unix_hint,
    dispatch_tool,
    repair_llm_file_path,
    coerce_path_to_expected,
    tool_bash,
    tool_brave_search,
    tool_edit_file,
    tool_glob,
    tool_grep,
    tool_read_file,
    tool_web_fetch,
    tool_write_file,
    TOOL_SCHEMAS,
)


# ── _anchor (cwd des tâches) ──────────────────────────────────────────────────

class TestAnchor:
    def test_relative_anchored_to_cwd(self):
        result = _anchor("result.txt", "/task/dir")
        assert result == str(Path("/task/dir") / "result.txt")

    def test_absolute_unchanged(self, tmp_path):
        # Un chemin absolu (vrai, dépendant de l'OS) n'est jamais ré-ancré
        abs_path = str(tmp_path / "result.txt")
        assert _anchor(abs_path, "/task/dir") == abs_path

    def test_no_cwd_unchanged(self):
        assert _anchor("result.txt", None) == "result.txt"

    def test_empty_path_unchanged(self):
        assert _anchor("", "/task/dir") == ""

    def test_nested_relative(self):
        result = _anchor("sub/result.txt", "/task")
        assert result == str(Path("/task") / "sub/result.txt")


# ── _confine (anti-évasion du sandbox) ────────────────────────────────────────

class TestConfine:
    def test_relative_stays_inside(self, tmp_path):
        fp, err = _confine("result.txt", str(tmp_path))
        assert err is None
        assert Path(fp) == (tmp_path / "result.txt").resolve()

    def test_nested_relative_inside(self, tmp_path):
        fp, err = _confine("sub/deep/result.txt", str(tmp_path))
        assert err is None
        assert str(tmp_path.resolve()) in fp

    def test_parent_traversal_refused(self, tmp_path):
        fp, err = _confine("../escape.txt", str(tmp_path))
        assert err is not None
        assert "escapes" in err.lower()

    def test_absolute_outside_refused(self, tmp_path):
        outside = str(tmp_path.parent / "outside.txt")
        fp, err = _confine(outside, str(tmp_path))
        assert err is not None

    def test_absolute_inside_allowed(self, tmp_path):
        inside = str(tmp_path / "ok.txt")
        fp, err = _confine(inside, str(tmp_path))
        assert err is None

    def test_no_cwd_no_confinement(self):
        fp, err = _confine("/anywhere/file.txt", None)
        assert err is None
        assert fp == "/anywhere/file.txt"

    def test_empty_path_passthrough(self, tmp_path):
        fp, err = _confine("", str(tmp_path))
        assert err is None
        assert fp == ""

    def test_cwd_itself_allowed(self, tmp_path):
        # cible == base (cas limite : le dossier lui-même)
        fp, err = _confine(str(tmp_path), str(tmp_path))
        assert err is None

    def test_invalid_path_reported(self, tmp_path):
        with patch.object(Path, "resolve", side_effect=OSError("bad")):
            fp, err = _confine("x.txt", str(tmp_path))
        assert err is not None
        assert "invalid path" in err.lower()

    def test_repairs_drive_garble_then_confines(self, tmp_path):
        scratch = tmp_path / "_p0_scratch"
        scratch.mkdir()
        garbled = "_" + str((scratch / "_found.txt").resolve())
        fp, err = _confine(garbled, str(tmp_path))
        assert err is None
        assert Path(fp).name == "found.txt"
        assert Path(fp).parent.name == "_p0_scratch"


# ── repair_llm_file_path (anti-garble LLM) ─────────────────────────────────────

class TestRepairLlmFilePath:
    def test_drive_underscore_prefix(self):
        got = repair_llm_file_path(r"_C:\proj\_p0_scratch\_found.txt")
        assert got == r"C:\proj\_p0_scratch\found.txt"

    def test_fused_drive_and_doubled_dir(self):
        got = repair_llm_file_path("_Cp0_scratch/_p0_scratch/x.txt")
        assert Path(got) == Path("_p0_scratch/x.txt")

    def test_absolute_doubled_scratch_dir(self, tmp_path):
        nested = tmp_path / "_p0_scratch" / "_p0_scratch" / "found.txt"
        got = repair_llm_file_path(str(nested))
        assert Path(got) == (tmp_path / "_p0_scratch" / "found.txt")

    def test_healthy_relative_unchanged(self):
        assert repair_llm_file_path("_p0_scratch/found.txt") == "_p0_scratch/found.txt"

    def test_spurious_basename_underscore(self):
        assert repair_llm_file_path("_p0_scratch/_found.txt").replace("\\", "/").endswith(
            "_p0_scratch/found.txt"
        )

    def test_dunder_init_preserved(self):
        assert repair_llm_file_path("__init__.py") == "__init__.py"

    def test_unix_abs_garble(self):
        assert repair_llm_file_path("_/tmp/out.txt") == "/tmp/out.txt"

    def test_missing_colon_cusers(self):
        got = repair_llm_file_path(r"_CUsers\admin\proj\_p0_scratch\_x.txt")
        assert got.lower().replace("/", "\\").startswith(r"c:\users\admin\proj")
        assert got.replace("\\", "/").endswith("_p0_scratch/x.txt")

    def test_coerce_basename_to_expected(self):
        got = coerce_path_to_expected(
            r"_CUsers\admin\proj\_p0_scratch\_primary_arg_bash.txt",
            ["_p0_scratch/primary_arg_bash.txt"],
        )
        assert got == "_p0_scratch/primary_arg_bash.txt"

    def test_coerce_noop_when_ambiguous(self):
        got = coerce_path_to_expected(
            "a.txt",
            ["dir1/a.txt", "dir2/a.txt"],
        )
        assert got == "a.txt"

    def test_empty_passthrough(self):
        assert repair_llm_file_path("") == ""
        assert repair_llm_file_path(None) is None

    def test_dispatch_write_accepts_garbled_drive(self, tmp_path):
        scratch = tmp_path / "_p0_scratch"
        scratch.mkdir()
        garbled = "_" + str((scratch / "_found.txt").resolve())
        r = dispatch_tool(
            "write_file",
            {"file_path": garbled, "content": "nodus_planner.py\n"},
            cwd=str(tmp_path),
        )
        assert r.success, r.error
        assert (scratch / "found.txt").read_text(encoding="utf-8").startswith("nodus_planner")

    def test_dispatch_refuses_empty_write(self, tmp_path):
        r = dispatch_tool(
            "write_file",
            {"file_path": "empty.txt", "content": "   "},
            cwd=str(tmp_path),
        )
        assert not r.success
        assert "empty" in (r.error or "").lower()
        assert not (tmp_path / "empty.txt").exists()


# ── _is_destructive (denylist de commandes catastrophiques) ───────────────────

class TestIsDestructive:
    @pytest.mark.parametrize("cmd", [
        "rm -rf /",
        "rm -rf ~",
        "rm -rf *",
        "rm -fr /",
        "git push --force origin main",
        "git push -f",
        "git reset --hard HEAD~5",
        "git clean -fd",
        "mkfs.ext4 /dev/sda1",
        "dd if=/dev/zero of=/dev/sda",
        "chmod -R 777 /",
        "format C:",
        "Remove-Item -Recurse -Force C:\\",
    ])
    def test_blocks_catastrophic(self, cmd):
        assert _is_destructive(cmd) is True

    @pytest.mark.parametrize("cmd", [
        "rm -rf ./build",
        "rm -rf node_modules",
        "git push origin main",
        "git commit -m 'x'",
        "pytest -q",
        "ls -la",
        "python script.py",
        "git reset --soft HEAD~1",
    ])
    def test_allows_legitimate(self, cmd):
        assert _is_destructive(cmd) is False


# ── tool_bash refuse les commandes destructrices ──────────────────────────────

class TestBashDenylist:
    def test_rm_rf_root_blocked(self):
        r = tool_bash("rm -rf /")
        assert r.success is False
        assert "blocked" in r.error.lower()

    def test_force_push_blocked(self):
        r = tool_bash("git push --force origin main")
        assert r.success is False
        assert "destructive" in r.error.lower() or "blocked" in r.error.lower()

    def test_legitimate_command_not_blocked(self):
        # Une commande inoffensive passe (echo).
        r = tool_bash("echo hello")
        assert "blocked" not in (r.error or "").lower()


# ── dispatch_tool confine write/edit au sandbox ───────────────────────────────

class TestDispatchConfinement:
    def test_write_escape_refused(self, tmp_path):
        outside = str(tmp_path.parent / "ESCAPE.txt")
        r = dispatch_tool("write_file",
                          {"file_path": outside, "content": "x"},
                          cwd=str(tmp_path))
        assert r.success is False
        assert "escapes" in r.error.lower()
        assert not Path(outside).exists()

    def test_write_traversal_refused(self, tmp_path):
        r = dispatch_tool("write_file",
                          {"file_path": "../pwned.txt", "content": "x"},
                          cwd=str(tmp_path))
        assert r.success is False
        assert not (tmp_path.parent / "pwned.txt").exists()

    def test_write_inside_allowed(self, tmp_path):
        r = dispatch_tool("write_file",
                          {"file_path": "ok.txt", "content": "hi"},
                          cwd=str(tmp_path))
        assert r.success is True
        assert (tmp_path / "ok.txt").read_text(encoding="utf-8") == "hi"

    def test_edit_escape_refused(self, tmp_path):
        outside = tmp_path.parent / "victim.txt"
        outside.write_text("secret", encoding="utf-8")
        try:
            r = dispatch_tool("edit_file",
                              {"file_path": str(outside),
                               "old_string": "secret", "new_string": "hacked"},
                              cwd=str(tmp_path))
            assert r.success is False
            assert "escapes" in r.error.lower()
            assert outside.read_text(encoding="utf-8") == "secret"
        finally:
            outside.unlink()

    def test_write_missing_path(self, tmp_path):
        r = dispatch_tool("write_file", {"content": "x"}, cwd=str(tmp_path))
        assert r.success is False
        assert "file_path" in r.error

    def test_edit_missing_path(self, tmp_path):
        r = dispatch_tool("edit_file",
                          {"old_string": "a", "new_string": "b"},
                          cwd=str(tmp_path))
        assert r.success is False
        assert "file_path" in r.error

    # ── READ-side confinement ────────────────────────────────────────────────

    def test_read_escape_refused(self, tmp_path):
        outside = tmp_path.parent / "secret.txt"
        outside.write_text("API_KEY", encoding="utf-8")
        try:
            r = dispatch_tool("read_file",
                              {"file_path": str(outside)},
                              cwd=str(tmp_path))
            assert r.success is False
            assert "escapes" in r.error.lower()
            assert "API_KEY" not in r.output
        finally:
            outside.unlink()

    def test_read_traversal_refused(self, tmp_path):
        outside = tmp_path.parent / "secret2.txt"
        outside.write_text("API_KEY", encoding="utf-8")
        try:
            r = dispatch_tool("read_file",
                              {"file_path": "../secret2.txt"},
                              cwd=str(tmp_path))
            assert r.success is False
            assert "escapes" in r.error.lower()
            assert "API_KEY" not in r.output
        finally:
            outside.unlink()

    def test_read_inside_allowed(self, tmp_path):
        (tmp_path / "data.txt").write_text("hello", encoding="utf-8")
        r = dispatch_tool("read_file",
                          {"file_path": "data.txt"},
                          cwd=str(tmp_path))
        assert r.success is True
        assert "hello" in r.output

    def test_glob_escape_refused(self, tmp_path):
        outside = str(tmp_path.parent)
        r = dispatch_tool("glob",
                          {"pattern": "*.txt", "path": outside},
                          cwd=str(tmp_path))
        assert r.success is False
        assert "escapes" in r.error.lower()

    def test_glob_inside_allowed(self, tmp_path):
        (tmp_path / "a.py").write_text("x", encoding="utf-8")
        r = dispatch_tool("glob",
                          {"pattern": "*.py", "path": str(tmp_path)},
                          cwd=str(tmp_path))
        assert r.success is True
        assert "a.py" in r.output

    def test_grep_escape_refused(self, tmp_path):
        outside = tmp_path.parent / "secret3.txt"
        outside.write_text("SECRET_VALUE", encoding="utf-8")
        try:
            r = dispatch_tool("grep",
                              {"pattern": "SECRET_VALUE", "path": str(outside)},
                              cwd=str(tmp_path))
            assert r.success is False
            assert "escapes" in r.error.lower()
            assert "SECRET_VALUE" not in r.output
        finally:
            outside.unlink()

    def test_grep_inside_allowed(self, tmp_path):
        (tmp_path / "code.py").write_text("def foo(): pass", encoding="utf-8")
        r = dispatch_tool("grep",
                          {"pattern": "def foo", "path": str(tmp_path)},
                          cwd=str(tmp_path))
        assert r.success is True
        assert "foo" in r.output


# ── tool_bash cwd ─────────────────────────────────────────────────────────────

class TestToolBashCwd:
    def test_bash_runs_in_cwd(self, tmp_path):
        # echo redirect crée le fichier dans le cwd passé, pas le cwd du process
        (tmp_path / "marker.txt").write_text("hi", encoding="utf-8")
        # pwd/Get-Location doit refléter le cwd de la tâche
        import platform
        cmd = "Get-Location | Select-Object -ExpandProperty Path" if platform.system() == "Windows" else "pwd"
        r = tool_bash(cmd, cwd=str(tmp_path))
        assert r.success
        # le chemin de tmp_path apparaît dans la sortie
        assert tmp_path.name in r.output

    @patch("nodus_tools.platform.system", return_value="Linux")
    @patch("nodus_tools.subprocess.run")
    def test_cwd_passed_to_subprocess(self, mock_run, _mock_sys):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        tool_bash("echo hi", cwd="/my/task")
        assert mock_run.call_args[1]["cwd"] == "/my/task"

    @patch("nodus_tools.platform.system", return_value="Linux")
    @patch("nodus_tools.subprocess.run")
    def test_cwd_defaults_none(self, mock_run, _mock_sys):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        tool_bash("echo hi")
        assert mock_run.call_args[1]["cwd"] is None


# ── dispatch_tool cwd anchoring (intégration) ─────────────────────────────────

class TestDispatchCwdAnchoring:
    def test_write_relative_lands_in_cwd(self, tmp_path):
        dispatch_tool("write_file", {"file_path": "out.txt", "content": "42"}, cwd=str(tmp_path))
        assert (tmp_path / "out.txt").exists()
        assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "42"

    def test_read_relative_from_cwd(self, tmp_path):
        (tmp_path / "data.txt").write_text("hello", encoding="utf-8")
        r = dispatch_tool("read_file", {"file_path": "data.txt"}, cwd=str(tmp_path))
        assert r.success
        assert "hello" in r.output

    def test_glob_defaults_to_cwd(self, tmp_path):
        (tmp_path / "a.py").write_text("x", encoding="utf-8")
        r = dispatch_tool("glob", {"pattern": "*.py"}, cwd=str(tmp_path))
        assert r.success
        assert "a.py" in r.output


# ── _normalize_command ────────────────────────────────────────────────────────

class TestNormalizeCommand:
    def test_strips_bash_prefix(self):
        assert _normalize_command("bash grep -c def file.py") == "grep -c def file.py"

    def test_strips_bash_uppercase(self):
        assert _normalize_command("BASH grep file.py") == "grep file.py"

    def test_strips_bash_extra_spaces(self):
        assert _normalize_command("bash  grep file.py") == "grep file.py"

    def test_no_bash_prefix_unchanged(self):
        assert _normalize_command("python -m pytest") == "python -m pytest"

    def test_empty_string_unchanged(self):
        assert _normalize_command("") == ""

    def test_only_bash_stripped_to_empty(self):
        assert _normalize_command("bash ") == ""

    def test_does_not_strip_inner_bash(self):
        # "bash" inside the command (not a prefix) should NOT be stripped
        cmd = "python -c \"import bash\""
        assert _normalize_command(cmd) == cmd

    def test_grep_command_preserved(self):
        assert _normalize_command("bash grep -c \"^def \" nodus_tools.py") == "grep -c \"^def \" nodus_tools.py"

    def test_pure_no_mutation(self):
        original = "bash ls -la"
        result = _normalize_command(original)
        assert original == "bash ls -la"  # original untouched
        assert result == "ls -la"


# ── _rewrite_windows_powershell ───────────────────────────────────────────────

class TestRewriteWindowsPowershell:
    def test_and_and_to_semicolon(self):
        cmd = "cd C:\\task && python script.py"
        assert "&&" not in _rewrite_windows_powershell(cmd)
        assert "; python script.py" in _rewrite_windows_powershell(cmd)

    def test_cd_d_to_set_location(self):
        cmd = "cd /d C:\\task && python x.py"
        out = _rewrite_windows_powershell(cmd)
        assert "cd /d" not in out.lower()
        assert "Set-Location" in out

    def test_strips_redundant_cd_when_cwd_matches(self, tmp_path):
        task = str(tmp_path)
        cmd = f"cd {task}; python demo.py"
        out = _rewrite_windows_powershell(cmd, cwd=task)
        assert out.lower().startswith("python")

    def test_absolute_python_path_when_cwd_set(self, tmp_path):
        task = str(tmp_path)
        script = tmp_path / "demo.py"
        script.write_text("print('ok')", encoding="utf-8")
        out = _rewrite_windows_powershell("python demo.py", cwd=task)
        assert str(script.resolve()) in out

    def test_keeps_absolute_python_path(self):
        cmd = r"python C:\already\abs.py"
        assert _rewrite_windows_powershell(cmd, cwd=r"C:\task") == cmd

    def test_bash_prefix_stripped(self):
        out = _rewrite_windows_powershell("bash echo hi")
        assert out == "echo hi"


# ── _unix_hint ────────────────────────────────────────────────────────────────

class TestUnixHint:
    def test_wc_l_returns_hint(self):
        hint = _unix_hint("wc -l file.py")
        assert "wc" in hint or "Hint" in hint

    def test_find_dot_returns_hint(self):
        hint = _unix_hint("find . -name '*.py'")
        assert hint != ""

    def test_tail_returns_hint(self):
        hint = _unix_hint("tail -n 20 file.py")
        assert hint != ""

    def test_grep_r_returns_hint(self):
        hint = _unix_hint("grep -r pattern .")
        assert hint != ""

    def test_grep_l_returns_hint(self):
        hint = _unix_hint("grep -l pattern .")
        assert hint != ""

    def test_gsutil_returns_hint(self):
        hint = _unix_hint("gsutil cat gs://bucket/file.txt")
        assert "gsutil" in hint

    def test_gcloud_storage_returns_hint(self):
        hint = _unix_hint("gcloud storage ls gs://bucket/file.txt")
        assert "gcloud" in hint

    def test_plain_gcloud_no_hint(self):
        # "gcloud storage" is the verification pattern; other gcloud use is untouched
        assert _unix_hint("gcloud config list") == ""

    def test_normal_command_returns_empty(self):
        assert _unix_hint("python -m pytest") == ""

    def test_and_and_returns_hint(self):
        hint = _unix_hint("cd x && python y.py")
        assert "&&" in hint or "PowerShell" in hint

    def test_grep_single_file_no_hint(self):
        # grep on a single file is fine on Windows — no hint
        assert _unix_hint("grep -c '^def ' file.py") == ""

    def test_hint_is_string(self):
        result = _unix_hint("wc -l file.py")
        assert isinstance(result, str)

    def test_empty_command_returns_empty(self):
        assert _unix_hint("") == ""


# ── ToolResult ─────────────────────────────────────────────────────────────────

class TestToolResult:
    def test_to_str_success_with_output(self):
        r = ToolResult(success=True, output="hello")
        assert r.to_str() == "hello"

    def test_to_str_success_empty_output(self):
        r = ToolResult(success=True, output="")
        assert r.to_str() == "(no output)"

    def test_to_str_failure(self):
        r = ToolResult(success=False, output="", error="oops")
        assert r.to_str() == "Error: oops"

    def test_error_defaults_to_none(self):
        r = ToolResult(success=True, output="x")
        assert r.error is None

    def test_frozen_rejects_field_mutation(self):
        # Hygiène tools : polaroid, pas post-it. Mutation in-place = FrozenInstanceError.
        r = ToolResult(success=True, output="ok")
        with pytest.raises(Exception) as exc_info:
            r.success = False  # type: ignore[misc]
        assert "frozen" in type(exc_info.value).__name__.lower() or "frozen" in str(exc_info.value).lower()
        with pytest.raises(Exception):
            r.output = "mutated"  # type: ignore[misc]
        with pytest.raises(Exception):
            r.error = "nope"  # type: ignore[misc]
        # Original intact
        assert r.success is True and r.output == "ok" and r.error is None

    def test_equality_and_hash_stable(self):
        a = ToolResult(success=True, output="x")
        b = ToolResult(success=True, output="x")
        c = ToolResult(success=False, output="", error="e")
        assert a == b
        assert a != c
        assert hash(a) == hash(b)
        # Utilisable dans un set (contrat immutable)
        assert len({a, b, c}) == 2

    def test_redact_returns_new_instance_leaves_original(self):
        from nodus_tools import _redact_result
        raw = ToolResult(success=True, output="key sk-or-v1-abcdefghijklmnopqrstuvwxyz12")
        red = _redact_result(raw)
        assert red is not raw
        assert "sk-or-v1-" in raw.output  # original non muté
        assert "[REDACTED-SECRET]" in red.output
        assert red.success is True


# ── Protected reference files ─────────────────────────────────────────────────

class TestProtectedReferenceFiles:
    def test_existing_mini_pytest_is_protected(self, tmp_path):
        ref = tmp_path / "mini_pytest.py"
        ref.write_text("print('reference')", encoding="utf-8")
        err = _protected_reference_error(str(ref))
        assert err is not None
        assert "protected reference file" in err

    def test_missing_mini_pytest_not_blocked(self, tmp_path):
        err = _protected_reference_error(str(tmp_path / "mini_pytest.py"))
        assert err is None

    def test_env_allows_reference_overwrite(self, tmp_path, monkeypatch):
        ref = tmp_path / "mini_pytest.py"
        ref.write_text("print('reference')", encoding="utf-8")
        monkeypatch.setenv("NODUS_ALLOW_REFERENCE_OVERWRITE", "1")
        assert _protected_reference_error(str(ref)) is None


# ── _normalize_quotes ──────────────────────────────────────────────────────────

class TestNormalizeQuotes:
    def test_curly_single_open(self):
        assert _normalize_quotes("‘hello") == "'hello"

    def test_curly_single_close(self):
        assert _normalize_quotes("hello’") == "hello'"

    def test_curly_double_open(self):
        assert _normalize_quotes("“hello") == '"hello'

    def test_curly_double_close(self):
        assert _normalize_quotes("hello”") == 'hello"'

    def test_straight_quotes_unchanged(self):
        assert _normalize_quotes("'hello'") == "'hello'"

    def test_mixed_quotes(self):
        result = _normalize_quotes("‘hi’ and “bye”")
        assert result == "'hi' and \"bye\""


# ── _find_actual_string ────────────────────────────────────────────────────────

class TestFindActualString:
    def test_exact_match(self):
        assert _find_actual_string("hello world", "hello") == "hello"

    def test_normalized_curly_match(self):
        content = "He said 'hello'"
        result = _find_actual_string(content, "‘hello’")
        assert result == "'hello'"

    def test_no_match_returns_none(self):
        assert _find_actual_string("hello world", "xyz") is None

    def test_normalized_same_as_original_no_match(self):
        # straight quotes, not in content → None
        assert _find_actual_string("goodbye", "xyz") is None


# ── tool_bash ─────────────────────────────────────────────────────────────────

class TestToolBash:
    @patch("nodus_tools.platform.system", return_value="Linux")
    @patch("nodus_tools.subprocess.run")
    def test_success_linux(self, mock_run, _mock_sys):
        mock_run.return_value = MagicMock(returncode=0, stdout="output", stderr="")
        r = tool_bash("echo hi")
        assert r.success is True
        assert "output" in r.output
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "bash"

    @patch("nodus_tools.platform.system", return_value="Windows")
    @patch("nodus_tools.subprocess.run")
    def test_success_windows_uses_powershell(self, mock_run, _mock_sys):
        mock_run.return_value = MagicMock(returncode=0, stdout="win_out", stderr="")
        r = tool_bash("echo hi")
        assert r.success is True
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "powershell"

    @patch("nodus_tools.platform.system", return_value="Windows")
    @patch("nodus_tools.subprocess.run")
    def test_windows_rewrites_and_and(self, mock_run, _mock_sys, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="OK", stderr="")
        task = str(tmp_path)
        script = tmp_path / "demo.py"
        script.write_text("print('OK')", encoding="utf-8")
        r = tool_bash(f"cd {task} && python demo.py", cwd=task)
        assert r.success is True
        ps_cmd = mock_run.call_args[0][0][-1]
        assert "&&" not in ps_cmd
        assert str(script.resolve()) in ps_cmd

    @patch("nodus_tools.platform.system", return_value="Linux")
    @patch("nodus_tools.subprocess.run")
    def test_nonzero_exit_code_is_failure(self, mock_run, _mock_sys):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="some error")
        r = tool_bash("bad_cmd")
        assert r.success is False
        assert "Exit code 1" in r.error

    @patch("nodus_tools.platform.system", return_value="Linux")
    @patch("nodus_tools.subprocess.run")
    def test_stderr_appended_to_output(self, mock_run, _mock_sys):
        mock_run.return_value = MagicMock(returncode=0, stdout="out", stderr="warn")
        r = tool_bash("cmd")
        assert "warn" in r.output
        assert "[stderr]" in r.output

    @patch("nodus_tools.platform.system", return_value="Linux")
    @patch("nodus_tools.subprocess.run")
    def test_blank_stderr_not_appended(self, mock_run, _mock_sys):
        mock_run.return_value = MagicMock(returncode=0, stdout="out", stderr="   ")
        r = tool_bash("cmd")
        assert "[stderr]" not in r.output

    @patch("nodus_tools.platform.system", return_value="Linux")
    @patch("nodus_tools.subprocess.run")
    def test_timeout_clamped_to_max(self, mock_run, _mock_sys):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        tool_bash("echo", timeout=9999)
        _, kwargs = mock_run.call_args
        assert kwargs["timeout"] <= MAX_TIMEOUT

    @patch("nodus_tools.platform.system", return_value="Linux")
    @patch("nodus_tools.subprocess.run")
    def test_output_truncated_at_max(self, mock_run, _mock_sys):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="x" * (MAX_OUTPUT_CHARS + 100), stderr=""
        )
        r = tool_bash("echo")
        assert len(r.output) <= MAX_OUTPUT_CHARS

    @patch("nodus_tools.platform.system", return_value="Linux")
    @patch("nodus_tools.subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 5))
    def test_timeout_expired(self, _mock_run, _mock_sys):
        r = tool_bash("sleep 100", timeout=1)
        assert r.success is False
        assert "Timeout" in r.error

    @patch("nodus_tools.platform.system", return_value="Linux")
    @patch("nodus_tools.subprocess.run", side_effect=FileNotFoundError("no shell"))
    def test_shell_not_found(self, _mock_run, _mock_sys):
        r = tool_bash("echo hi")
        assert r.success is False
        assert "Shell not found" in r.error

    @patch("nodus_tools.platform.system", return_value="Linux")
    @patch("nodus_tools.subprocess.run", side_effect=OSError("unexpected"))
    def test_generic_exception(self, _mock_run, _mock_sys):
        r = tool_bash("echo hi")
        assert r.success is False

    @patch("nodus_tools.platform.system", return_value="Windows")
    @patch("nodus_tools.subprocess.run")
    def test_windows_strips_bash_prefix(self, mock_run, _mock_sys):
        """'bash grep ...' → PowerShell reçoit 'grep ...' sans le préfixe"""
        mock_run.return_value = MagicMock(returncode=0, stdout="42", stderr="")
        tool_bash("bash grep -c def file.py")
        cmd = mock_run.call_args[0][0]
        # La commande passée à powershell ne doit pas commencer par "bash"
        assert cmd[-1] == "grep -c def file.py"

    @patch("nodus_tools.platform.system", return_value="Windows")
    @patch("nodus_tools.subprocess.run")
    def test_windows_unix_hint_in_error(self, mock_run, _mock_sys):
        """Quand une commande Unix échoue, le message d'erreur contient un hint"""
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not recognized")
        r = tool_bash("wc -l file.py")
        assert r.success is False
        assert "Hint" in r.error


# ── tool_read_file ─────────────────────────────────────────────────────────────

class TestToolReadFile:
    def test_read_full_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\nline3", encoding="utf-8")
        r = tool_read_file(str(f))
        assert r.success is True
        assert "1\tline1" in r.output
        assert "3\tline3" in r.output

    def test_read_with_offset(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("a\nb\nc\nd", encoding="utf-8")
        r = tool_read_file(str(f), offset=2)
        assert r.success is True
        assert "3\tc" in r.output
        assert "1\ta" not in r.output

    def test_read_with_limit(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("a\nb\nc\nd", encoding="utf-8")
        r = tool_read_file(str(f), offset=0, limit=2)
        assert r.success is True
        assert "1\ta" in r.output
        assert "2\tb" in r.output
        assert "c" not in r.output

    def test_file_not_found(self, tmp_path):
        r = tool_read_file(str(tmp_path / "nonexistent.txt"))
        assert r.success is False
        assert "not found" in r.error.lower()

    def test_similar_file_hint(self, tmp_path):
        (tmp_path / "myfile.py").write_text("hello", encoding="utf-8")
        # Same stem, different extension → triggers _find_similar hint
        r = tool_read_file(str(tmp_path / "myfile.yaml"))
        assert r.success is False
        assert "Did you mean" in r.error

    def test_no_similar_hint_when_none(self, tmp_path):
        r = tool_read_file(str(tmp_path / "zzz_totally_unknown.py"))
        assert r.success is False
        assert "Did you mean" not in r.error

    def test_directory_returns_entry_list(self, tmp_path):
        (tmp_path / "a.py").write_text("x")
        (tmp_path / "b.py").write_text("y")
        r = tool_read_file(str(tmp_path))
        assert r.success is True
        assert "a.py" in r.output
        assert "b.py" in r.output

    def test_file_too_large(self, tmp_path):
        f = tmp_path / "big.bin"
        f.write_bytes(b"x" * (256 * 1024 + 1))
        r = tool_read_file(str(f))
        assert r.success is False
        assert "too large" in r.error.lower()

    def test_read_text_exception_returns_failure(self, tmp_path):
        f = tmp_path / "unreadable.txt"
        f.write_text("content", encoding="utf-8")
        with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            r = tool_read_file(str(f))
        assert r.success is False


# ── _find_similar ──────────────────────────────────────────────────────────────

class TestFindSimilar:
    def test_finds_case_insensitive(self, tmp_path):
        (tmp_path / "MyFile.py").write_text("x")
        result = _find_similar(tmp_path / "myfile.py")
        assert result is not None
        assert "MyFile.py" in result

    def test_finds_by_stem(self, tmp_path):
        (tmp_path / "config.json").write_text("{}")
        result = _find_similar(tmp_path / "config.yaml")
        assert result is not None

    def test_parent_not_dir_returns_none(self, tmp_path):
        result = _find_similar(tmp_path / "nonexistent_dir" / "file.py")
        assert result is None

    def test_no_match_returns_none(self, tmp_path):
        result = _find_similar(tmp_path / "zzz_no_match.py")
        assert result is None


# ── tool_edit_file ─────────────────────────────────────────────────────────────

class TestToolEditFile:
    def test_simple_replace(self, tmp_path):
        f = tmp_path / "edit.py"
        f.write_text("hello world", encoding="utf-8")
        r = tool_edit_file(str(f), "hello", "goodbye")
        assert r.success is True
        assert f.read_text(encoding="utf-8") == "goodbye world"

    def test_file_not_found(self, tmp_path):
        r = tool_edit_file(str(tmp_path / "missing.py"), "x", "y")
        assert r.success is False
        assert "not found" in r.error.lower()

    def test_old_string_not_in_file(self, tmp_path):
        f = tmp_path / "edit.py"
        f.write_text("hello world", encoding="utf-8")
        r = tool_edit_file(str(f), "xyz", "abc")
        assert r.success is False
        assert "not found" in r.error.lower()

    def test_multiple_occurrences_without_replace_all_fails(self, tmp_path):
        f = tmp_path / "edit.py"
        f.write_text("x x x", encoding="utf-8")
        r = tool_edit_file(str(f), "x", "y")
        assert r.success is False
        assert "3" in r.error

    def test_replace_all_replaces_all(self, tmp_path):
        f = tmp_path / "edit.py"
        f.write_text("x x x", encoding="utf-8")
        r = tool_edit_file(str(f), "x", "y", replace_all=True)
        assert r.success is True
        assert f.read_text(encoding="utf-8") == "y y y"
        assert "3" in r.output

    def test_curly_quote_normalization(self, tmp_path):
        f = tmp_path / "edit.py"
        # _normalize_quotes replaces ‘/’ (curly) with ‘ (straight)
        f.write_text("He said ‘hello’", encoding="utf-8")
        left, right = "‘", "’"   # LEFT / RIGHT SINGLE QUOTATION MARK
        r = tool_edit_file(str(f), left + "hello" + right, "goodbye")
        assert r.success is True
        assert "goodbye" in f.read_text(encoding="utf-8")

    def test_write_text_exception_returns_failure(self, tmp_path):
        f = tmp_path / "edit.py"
        f.write_text("hello world", encoding="utf-8")
        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            r = tool_edit_file(str(f), "hello", "goodbye")
        assert r.success is False


# ── tool_write_file ────────────────────────────────────────────────────────────

class TestToolWriteFile:
    def test_write_new_file(self, tmp_path):
        f = tmp_path / "new.txt"
        r = tool_write_file(str(f), "hello\nworld")
        assert r.success is True
        assert f.read_text(encoding="utf-8") == "hello\nworld"
        assert "2 lines" in r.output

    def test_overwrite_existing_file(self, tmp_path):
        f = tmp_path / "existing.txt"
        f.write_text("old")
        r = tool_write_file(str(f), "new content")
        assert r.success is True
        assert f.read_text(encoding="utf-8") == "new content"

    def test_creates_parent_directories(self, tmp_path):
        f = tmp_path / "sub" / "dir" / "new.txt"
        r = tool_write_file(str(f), "data")
        assert r.success is True
        assert f.exists()

    def test_reports_char_count(self, tmp_path):
        f = tmp_path / "x.txt"
        r = tool_write_file(str(f), "hello")
        assert "5" in r.output

    def test_write_to_impossible_path_fails(self, tmp_path):
        existing_file = tmp_path / "file.txt"
        existing_file.write_text("x")
        r = tool_write_file(str(existing_file / "impossible" / "sub.txt"), "x")
        assert r.success is False


# ── tool_glob ─────────────────────────────────────────────────────────────────

class TestToolGlob:
    def test_finds_python_files(self, tmp_path):
        (tmp_path / "a.py").write_text("x")
        (tmp_path / "b.py").write_text("y")
        r = tool_glob("*.py", str(tmp_path))
        assert r.success is True
        assert "a.py" in r.output
        assert "b.py" in r.output

    def test_no_files_returns_message(self, tmp_path):
        r = tool_glob("*.xyz", str(tmp_path))
        assert r.success is True
        assert "no files found" in r.output

    def test_skips_pycache_directory(self, tmp_path):
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "mod.cpython-310.pyc").write_bytes(b"x")
        (tmp_path / "real.py").write_text("x")
        r = tool_glob("**/*", str(tmp_path))
        assert "__pycache__" not in r.output
        assert "real.py" in r.output

    def test_skips_pyc_extension(self, tmp_path):
        (tmp_path / "module.pyc").write_bytes(b"x")
        r = tool_glob("**/*.pyc", str(tmp_path))
        assert r.success is True
        assert "(no files found)" in r.output

    def test_max_results_shows_truncation(self, tmp_path):
        for i in range(MAX_GLOB_RESULTS + 5):
            (tmp_path / f"f{i}.txt").write_text("x")
        r = tool_glob("*.txt", str(tmp_path))
        assert r.success is True
        assert "more" in r.output

    def test_uses_cwd_when_no_path(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "test.py").write_text("x")
        r = tool_glob("*.py")
        assert r.success is True
        assert "test.py" in r.output

    def test_glob_exception_returns_failure(self):
        with patch("nodus_tools.Path.glob", side_effect=ValueError("bad pattern")):
            r = tool_glob("**/*.py", "/tmp")
        assert r.success is False


# ── tool_grep ─────────────────────────────────────────────────────────────────

class TestToolGrep:
    def test_content_mode_match(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("def hello():\n    pass\n", encoding="utf-8")
        r = tool_grep("def", str(f))
        assert r.success is True
        assert "def hello" in r.output

    def test_content_mode_no_match(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("hello world", encoding="utf-8")
        r = tool_grep("xyz_absent", str(f))
        assert r.success is True
        assert "no matches" in r.output

    def test_files_with_matches_mode(self, tmp_path):
        (tmp_path / "a.py").write_text("def foo(): pass")
        (tmp_path / "b.py").write_text("hello world")
        r = tool_grep("def", str(tmp_path), output_mode="files_with_matches")
        assert r.success is True
        assert "a.py" in r.output
        assert "b.py" not in r.output

    def test_files_with_matches_no_match(self, tmp_path):
        (tmp_path / "a.py").write_text("hello")
        r = tool_grep("xyz_absent", str(tmp_path), output_mode="files_with_matches")
        assert r.success is True
        assert "no matches" in r.output

    def test_invalid_regex_returns_error(self, tmp_path):
        r = tool_grep("[invalid(", str(tmp_path))
        assert r.success is False
        assert "Invalid regex" in r.error

    def test_skips_pycache_directory(self, tmp_path):
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "mod.cpython-310.pyc").write_bytes(b"def secret(): pass")
        (tmp_path / "real.py").write_text("def visible(): pass")
        r = tool_grep("def", str(tmp_path))
        assert "__pycache__" not in r.output
        assert "real.py" in r.output

    def test_case_insensitive_by_default(self, tmp_path):
        f = tmp_path / "f.py"
        f.write_text("HELLO WORLD", encoding="utf-8")
        r = tool_grep("hello", str(f))
        assert r.success is True
        assert "HELLO WORLD" in r.output

    def test_glob_filter_limits_files(self, tmp_path):
        (tmp_path / "a.py").write_text("match here")
        (tmp_path / "b.txt").write_text("match here too")
        r = tool_grep("match", str(tmp_path), glob="*.py")
        assert r.success is True
        assert "a.py" in r.output
        assert "b.txt" not in r.output

    def test_scan_single_file(self, tmp_path):
        f = tmp_path / "single.py"
        f.write_text("line1\nfoo_here\nline3")
        r = tool_grep("foo_here", str(f))
        assert r.success is True
        assert "foo_here" in r.output

    def test_max_results_respected(self, tmp_path):
        lines = "match\n" * (MAX_GREP_RESULTS + 10)
        f = tmp_path / "big.py"
        f.write_text(lines, encoding="utf-8")
        r = tool_grep("match", str(f))
        assert r.success is True
        result_lines = [ln for ln in r.output.split("\n") if ln.strip()]
        assert len(result_lines) <= MAX_GREP_RESULTS

    def test_uses_cwd_when_no_path(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "x.py").write_text("needle_word")
        r = tool_grep("needle_word")
        assert r.success is True
        assert "needle_word" in r.output

    def test_grep_unreadable_file_skipped(self, tmp_path):
        f = tmp_path / "unreadable.py"
        f.write_text("match")
        with patch("nodus_tools.Path.read_text", side_effect=PermissionError("denied")):
            r = tool_grep("match", str(tmp_path))
        assert r.success is True
        assert "(no matches)" in r.output

    def test_grep_outer_exception_returns_failure(self, tmp_path):
        with patch("nodus_tools.Path.resolve", side_effect=OSError("broken")):
            r = tool_grep("pattern", str(tmp_path))
        assert r.success is False


# ── tool_web_fetch ─────────────────────────────────────────────────────────────

def _mock_stream_resp(content_type, body_bytes):
    """Construit une réponse requests simulée en mode stream (iter_content)."""
    mock_resp = MagicMock()
    mock_resp.headers = {"content-type": content_type}
    mock_resp.raise_for_status.return_value = None
    # web_fetch suit les redirections à la main (anti-SSRF) : une vraie réponse
    # non-redirigée a is_redirect=False — un MagicMock le rendrait vrai par défaut.
    mock_resp.is_redirect = False
    mock_resp.is_permanent_redirect = False

    def _iter(chunk_size=8192):
        for i in range(0, len(body_bytes), chunk_size):
            yield body_bytes[i:i + chunk_size]
    mock_resp.iter_content.side_effect = _iter
    mock_resp.close.return_value = None
    return mock_resp


class TestToolWebFetch:
    @pytest.fixture(autouse=True)
    def _allow_urls(self):
        # Les tests de contenu ne testent pas le SSRF → on autorise l'URL pour
        # rester hermétique (pas de vraie résolution DNS). tool_web_fetch passe
        # désormais par _validate_and_pin_url (et plus _is_blocked_url), donc on
        # neutralise CE point d'entrée — sinon getaddrinfo resoudrait pour de vrai.
        from urllib.parse import urlparse

        def _allow(u):
            return (False, "", u, urlparse(u).hostname)
        with patch("nodus_tools._validate_and_pin_url", side_effect=_allow):
            yield

    @patch("nodus_tools.requests.get")
    def test_success_text_content(self, mock_get):
        mock_get.return_value = _mock_stream_resp("text/html", b"<html>hello</html>")
        r = tool_web_fetch("http://example.com")
        assert r.success is True
        assert "hello" in r.output

    @patch("nodus_tools.requests.get")
    def test_success_json_content(self, mock_get):
        mock_get.return_value = _mock_stream_resp("application/json", b'{"key": "value"}')
        r = tool_web_fetch("http://api.example.com/data")
        assert r.success is True
        assert "value" in r.output

    @patch("nodus_tools.requests.get")
    def test_binary_content_returns_info(self, mock_get):
        mock_get.return_value = _mock_stream_resp("image/png", b"\x89PNG" * 10)
        r = tool_web_fetch("http://example.com/img.png")
        assert r.success is True
        assert "binary" in r.output

    @patch("nodus_tools.requests.get")
    def test_text_truncated_when_too_long(self, mock_get):
        body = b"x" * (MAX_FETCH_CHARS + 100)
        mock_get.return_value = _mock_stream_resp("text/plain", body)
        r = tool_web_fetch("http://example.com", max_chars=MAX_FETCH_CHARS)
        assert r.success is True
        assert "truncated" in r.output

    @patch("nodus_tools.requests.get")
    def test_download_capped_at_max_bytes(self, mock_get):
        # Durcissement red-team r4 : un serveur qui stream au-delà du plafond
        # ne charge JAMAIS plus de MAX_FETCH_BYTES en mémoire.
        from nodus_tools import MAX_FETCH_BYTES
        body = b"a" * (MAX_FETCH_BYTES + 1_000_000)  # 1 MB de trop
        mock_get.return_value = _mock_stream_resp("text/plain", body)
        r = tool_web_fetch("http://flood.example.com", max_chars=MAX_FETCH_CHARS)
        assert r.success is True
        assert "truncated" in r.output
        # Le marqueur "+" signale qu'on a coupé au plafond d'octets
        assert "+ bytes" in r.output

    @patch("nodus_tools.requests.get")
    def test_binary_download_capped(self, mock_get):
        from nodus_tools import MAX_FETCH_BYTES
        body = b"\x00" * (MAX_FETCH_BYTES + 500_000)
        mock_get.return_value = _mock_stream_resp("image/png", body)
        r = tool_web_fetch("http://flood.example.com/big.bin")
        assert r.success is True
        assert "binary" in r.output
        assert "+ bytes" in r.output

    @patch("nodus_tools.requests.get")
    def test_skips_empty_chunks(self, mock_get):
        # iter_content peut yield des chunks vides (keep-alive) — ignorés.
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "text/plain"}
        mock_resp.raise_for_status.return_value = None
        mock_resp.is_redirect = False
        mock_resp.is_permanent_redirect = False
        mock_resp.iter_content.side_effect = lambda chunk_size=8192: iter(
            [b"", b"hi", b"", b"there"])
        mock_resp.close.return_value = None
        mock_get.return_value = mock_resp
        r = tool_web_fetch("http://example.com")
        assert r.success is True
        assert "hithere" in r.output

    @patch("nodus_tools.requests.get")
    def test_http_error(self, mock_get):
        import requests as req
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.is_redirect = False
        mock_resp.is_permanent_redirect = False
        mock_get.return_value = mock_resp
        mock_get.return_value.raise_for_status.side_effect = req.HTTPError(
            response=mock_resp
        )
        r = tool_web_fetch("http://example.com/missing")
        assert r.success is False
        assert "404" in r.error or "HTTP" in r.error

    @patch("nodus_tools.requests.get")
    def test_timeout(self, mock_get):
        import requests as req
        mock_get.side_effect = req.Timeout()
        r = tool_web_fetch("http://slow.example.com")
        assert r.success is False
        assert "Timeout" in r.error

    @patch("nodus_tools.requests.get")
    def test_request_exception(self, mock_get):
        import requests as req
        mock_get.side_effect = req.RequestException("connection refused")
        r = tool_web_fetch("http://bad.example.com")
        assert r.success is False

    @patch("nodus_tools.requests.get")
    def test_generic_exception(self, mock_get):
        mock_get.side_effect = ValueError("something unexpected")
        r = tool_web_fetch("http://example.com")
        assert r.success is False


# ── _is_blocked_url + SSRF (anti-SSRF, round 6 issu de l'autoresearch) ─────────

def _addrinfo(ip):
    """Forge un retour socket.getaddrinfo pour une IP donnée."""
    return [(2, 1, 6, "", (ip, 0))]


class TestIsBlockedUrl:
    def test_ftp_scheme_blocked(self):
        blocked, reason = _is_blocked_url("ftp://example.com/x")
        assert blocked is True
        assert "scheme" in reason

    def test_file_scheme_blocked(self):
        assert _is_blocked_url("file:///etc/passwd")[0] is True

    def test_missing_host_blocked(self):
        assert _is_blocked_url("http://")[0] is True

    def test_unparseable_blocked(self):
        with patch("nodus_tools.urlparse", side_effect=ValueError("boom")):
            assert _is_blocked_url("http://x")[0] is True

    def test_cloud_metadata_blocked(self):
        with patch("nodus_tools.socket.getaddrinfo", return_value=_addrinfo("169.254.169.254")):
            blocked, reason = _is_blocked_url("http://metadata.evil/latest/meta-data/")
        assert blocked is True
        assert "SSRF" in reason

    def test_loopback_blocked(self):
        with patch("nodus_tools.socket.getaddrinfo", return_value=_addrinfo("127.0.0.1")):
            assert _is_blocked_url("http://localhost:8080/admin")[0] is True

    def test_private_10_blocked(self):
        with patch("nodus_tools.socket.getaddrinfo", return_value=_addrinfo("10.0.0.5")):
            assert _is_blocked_url("http://internal.svc/")[0] is True

    def test_private_192_blocked(self):
        with patch("nodus_tools.socket.getaddrinfo", return_value=_addrinfo("192.168.1.1")):
            assert _is_blocked_url("http://router.local/")[0] is True

    def test_public_allowed(self):
        with patch("nodus_tools.socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")):
            blocked, reason = _is_blocked_url("https://example.com/page")
        assert blocked is False
        assert reason == ""

    def test_unresolvable_blocked(self):
        with patch("nodus_tools.socket.getaddrinfo", side_effect=socket.gaierror("nope")):
            assert _is_blocked_url("http://nonexistent.invalid/")[0] is True

    def test_invalid_ip_in_addrinfo_skipped(self):
        # Une entrée non-IP est ignorée ; une IP publique suit → autorisée.
        infos = [(2, 1, 6, "", ("not-an-ip", 0)), (2, 1, 6, "", ("8.8.8.8", 0))]
        with patch("nodus_tools.socket.getaddrinfo", return_value=infos):
            assert _is_blocked_url("http://mixed.example/")[0] is False


class TestWebFetchSSRF:
    def test_fetch_metadata_refused(self):
        with patch("nodus_tools.socket.getaddrinfo", return_value=_addrinfo("169.254.169.254")):
            r = tool_web_fetch("http://169.254.169.254/latest/meta-data/iam/")
        assert r.success is False
        assert "Blocked URL" in r.error

    def test_fetch_localhost_refused(self):
        with patch("nodus_tools.socket.getaddrinfo", return_value=_addrinfo("127.0.0.1")):
            r = tool_web_fetch("http://localhost/secret")
        assert r.success is False
        assert "Blocked URL" in r.error

    def test_fetch_public_allowed(self):
        with patch("nodus_tools.socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")):
            with patch("nodus_tools.requests.get",
                       return_value=_mock_stream_resp("text/html", b"ok")):
                r = tool_web_fetch("https://example.com")
        assert r.success is True
        assert "ok" in r.output


# ── TOOL_SCHEMAS ───────────────────────────────────────────────────────────────

class TestToolSchemas:
    def test_has_nine_schemas(self):
        # 8 natifs + gcs_upload (capability tool de livraison, côté harnais).
        assert len(TOOL_SCHEMAS) == 9

    def test_all_schemas_have_function_key(self):
        for schema in TOOL_SCHEMAS:
            assert schema["type"] == "function"
            assert "function" in schema
            assert "name" in schema["function"]

    def test_schema_names(self):
        names = {s["function"]["name"] for s in TOOL_SCHEMAS}
        assert names == {
            "bash", "read_file", "edit_file", "write_file",
            "glob", "grep", "web_fetch", "brave_search",
            "gcs_upload",
        }


# ── dispatch_tool ──────────────────────────────────────────────────────────────

class TestDispatchTool:
    def test_dispatch_bash(self):
        with patch("nodus_tools.tool_bash") as mock:
            mock.return_value = ToolResult(success=True, output="ok")
            dispatch_tool("bash", {"command": "echo hi"})
            mock.assert_called_once_with("echo hi", DEFAULT_TIMEOUT, cwd=None)

    def test_dispatch_bash_custom_timeout(self):
        with patch("nodus_tools.tool_bash") as mock:
            mock.return_value = ToolResult(success=True, output="ok")
            dispatch_tool("bash", {"command": "echo hi", "timeout": 60})
            mock.assert_called_once_with("echo hi", 60, cwd=None)

    def test_dispatch_bash_with_cwd(self):
        with patch("nodus_tools.tool_bash") as mock:
            mock.return_value = ToolResult(success=True, output="ok")
            dispatch_tool("bash", {"command": "echo hi"}, cwd="/task/dir")
            mock.assert_called_once_with("echo hi", DEFAULT_TIMEOUT, cwd="/task/dir")

    def test_dispatch_read_file(self):
        with patch("nodus_tools.tool_read_file") as mock:
            mock.return_value = ToolResult(success=True, output="content")
            dispatch_tool("read_file", {"file_path": "/tmp/f.py"})
            mock.assert_called_once_with("/tmp/f.py", 0, None)

    def test_dispatch_read_file_with_offset_limit(self):
        with patch("nodus_tools.tool_read_file") as mock:
            mock.return_value = ToolResult(success=True, output="ok")
            dispatch_tool("read_file", {"file_path": "/tmp/f.py", "offset": 5, "limit": 10})
            mock.assert_called_once_with("/tmp/f.py", 5, 10)

    def test_dispatch_edit_file(self):
        with patch("nodus_tools.tool_edit_file") as mock:
            mock.return_value = ToolResult(success=True, output="ok")
            dispatch_tool("edit_file", {
                "file_path": "/tmp/f.py",
                "old_string": "old",
                "new_string": "new",
            })
            mock.assert_called_once_with("/tmp/f.py", "old", "new", False)

    def test_dispatch_edit_file_replace_all(self):
        with patch("nodus_tools.tool_edit_file") as mock:
            mock.return_value = ToolResult(success=True, output="ok")
            dispatch_tool("edit_file", {
                "file_path": "/tmp/f.py",
                "old_string": "x",
                "new_string": "y",
                "replace_all": True,
            })
            mock.assert_called_once_with("/tmp/f.py", "x", "y", True)

    def test_dispatch_write_file(self):
        with patch("nodus_tools.tool_write_file") as mock:
            mock.return_value = ToolResult(success=True, output="ok")
            dispatch_tool("write_file", {"file_path": "/tmp/f.py", "content": "x"})
            mock.assert_called_once_with("/tmp/f.py", "x")

    def test_dispatch_glob(self):
        with patch("nodus_tools.tool_glob") as mock:
            mock.return_value = ToolResult(success=True, output="ok")
            dispatch_tool("glob", {"pattern": "**/*.py"})
            mock.assert_called_once_with("**/*.py", None)

    def test_dispatch_glob_with_path(self):
        with patch("nodus_tools.tool_glob") as mock:
            mock.return_value = ToolResult(success=True, output="ok")
            dispatch_tool("glob", {"pattern": "**/*.py", "path": "/src"})
            mock.assert_called_once_with("**/*.py", "/src")

    def test_dispatch_grep(self):
        with patch("nodus_tools.tool_grep") as mock:
            mock.return_value = ToolResult(success=True, output="ok")
            dispatch_tool("grep", {"pattern": "def"})
            mock.assert_called_once_with("def", None, None, "content")

    def test_dispatch_grep_with_all_options(self):
        with patch("nodus_tools.tool_grep") as mock:
            mock.return_value = ToolResult(success=True, output="ok")
            dispatch_tool("grep", {
                "pattern": "def",
                "path": "/tmp",
                "glob": "*.py",
                "output_mode": "files_with_matches",
            })
            mock.assert_called_once_with("def", "/tmp", "*.py", "files_with_matches")

    def test_dispatch_web_fetch(self):
        with patch("nodus_tools.tool_web_fetch") as mock:
            mock.return_value = ToolResult(success=True, output="ok")
            dispatch_tool("web_fetch", {"url": "http://example.com"})
            mock.assert_called_once_with("http://example.com", MAX_FETCH_CHARS)

    def test_dispatch_unknown_tool(self):
        r = dispatch_tool("unknown_xyz", {})
        assert r.success is False
        assert "Unknown tool" in r.error

    def test_dispatch_missing_required_key(self):
        r = dispatch_tool("bash", {})  # missing "command"
        assert r.success is False
        assert "Missing argument" in r.error

    def test_dispatch_generic_exception(self):
        with patch("nodus_tools.tool_bash", side_effect=RuntimeError("unexpected")):
            r = dispatch_tool("bash", {"command": "echo"})
            assert r.success is False
            assert "Tool error" in r.error

    # ── path alias (LLM sends "path" instead of "file_path") ──────────────────

    def test_read_file_path_alias(self, tmp_path):
        f = tmp_path / "x.txt"
        f.write_text("hello")
        r = dispatch_tool("read_file", {"path": str(f)})
        assert r.success is True
        assert "hello" in r.output

    def test_edit_file_path_alias(self, tmp_path):
        f = tmp_path / "x.txt"
        f.write_text("hello world")
        r = dispatch_tool("edit_file", {"path": str(f), "old_string": "hello", "new_string": "bye"})
        assert r.success is True

    def test_write_file_path_alias(self, tmp_path):
        f = tmp_path / "x.txt"
        r = dispatch_tool("write_file", {"path": str(f), "content": "data"})
        assert r.success is True

    # ── missing file_path / path → explicit error ──────────────────────────────

    def test_read_file_missing_path(self):
        r = dispatch_tool("read_file", {})
        assert r.success is False
        assert "Missing argument" in r.error

    def test_edit_file_missing_path(self):
        r = dispatch_tool("edit_file", {"old_string": "a", "new_string": "b"})
        assert r.success is False
        assert "Missing argument" in r.error

    def test_write_file_missing_path(self):
        r = dispatch_tool("write_file", {"content": "x"})
        assert r.success is False
        assert "Missing argument" in r.error


# ── _resolve_file_path ────────────────────────────────────────────────────────

class TestResolveFilePath:
    def test_prefers_file_path_over_path(self):
        assert _resolve_file_path({"file_path": "/a", "path": "/b"}) == "/a"

    def test_falls_back_to_path(self):
        assert _resolve_file_path({"path": "/b"}) == "/b"

    def test_empty_when_neither(self):
        assert _resolve_file_path({}) == ""


# ── tool_brave_search ─────────────────────────────────────────────────────────

def _brave_ok(results=None):
    """Factory: simule une réponse Brave Search réussie."""
    if results is None:
        results = [
            {
                "title": "Temple IAM",
                "url": "https://temple-iam.com",
                "description": "Site officiel",
            }
        ]
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {"web": {"results": results}}
    return mock


class TestToolBraveSearch:
    def test_returns_formatted_results(self):
        with patch("nodus_tools.requests.get", return_value=_brave_ok()):
            r = tool_brave_search("Temple IAM", api_key="fake-key")
        assert r.success is True
        assert "Temple IAM" in r.output
        assert "https://temple-iam.com" in r.output
        assert "Site officiel" in r.output

    def test_multiple_results_numbered(self):
        results = [
            {"title": f"R{i}", "url": f"https://r{i}.com", "description": f"Desc{i}"}
            for i in range(1, 4)
        ]
        with patch("nodus_tools.requests.get", return_value=_brave_ok(results)):
            r = tool_brave_search("query", count=3, api_key="fake-key")
        assert r.success is True
        assert "1. R1" in r.output
        assert "2. R2" in r.output
        assert "3. R3" in r.output

    def test_no_results_returns_no_results(self):
        with patch("nodus_tools.requests.get", return_value=_brave_ok([])):
            r = tool_brave_search("nothing", api_key="fake-key")
        assert r.success is True
        assert r.output == "(no results)"

    def test_count_clamped_to_max(self):
        with patch("nodus_tools.requests.get", return_value=_brave_ok()) as mock_get:
            tool_brave_search("q", count=999, api_key="fake-key")
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["count"] == MAX_SEARCH_RESULTS

    def test_count_clamped_to_min(self):
        with patch("nodus_tools.requests.get", return_value=_brave_ok()) as mock_get:
            tool_brave_search("q", count=0, api_key="fake-key")
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["count"] == 1

    def test_missing_api_key_returns_failure(self):
        r = tool_brave_search("q", api_key=None)
        # Temporarily patch BRAVE_API_KEY to None to ensure no key available
        import nodus_tools
        orig = nodus_tools.BRAVE_API_KEY
        nodus_tools.BRAVE_API_KEY = None
        try:
            r = tool_brave_search("q", api_key=None)
        finally:
            nodus_tools.BRAVE_API_KEY = orig
        assert r.success is False
        assert "manquante" in r.error

    def test_http_error_returns_failure(self):
        import requests as _req
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        with patch("nodus_tools.requests.get",
                   side_effect=_req.HTTPError(response=mock_resp)):
            r = tool_brave_search("q", api_key="fake-key")
        assert r.success is False
        assert "429" in r.error

    def test_timeout_returns_failure(self):
        import requests as _req
        with patch("nodus_tools.requests.get", side_effect=_req.Timeout()):
            r = tool_brave_search("q", api_key="fake-key")
        assert r.success is False
        assert "Timeout" in r.error

    def test_request_exception_returns_failure(self):
        import requests as _req
        with patch("nodus_tools.requests.get",
                   side_effect=_req.RequestException("conn refused")):
            r = tool_brave_search("q", api_key="fake-key")
        assert r.success is False
        assert "conn refused" in r.error

    def test_generic_exception_returns_failure(self):
        with patch("nodus_tools.requests.get", side_effect=ValueError("bad json")):
            r = tool_brave_search("q", api_key="fake-key")
        assert r.success is False
        assert "bad json" in r.error

    def test_result_missing_optional_fields(self):
        results = [{"title": "Minimal"}]  # no url, no description
        with patch("nodus_tools.requests.get", return_value=_brave_ok(results)):
            r = tool_brave_search("q", api_key="fake-key")
        assert r.success is True
        assert "Minimal" in r.output

    def test_dispatch_brave_search(self):
        with patch("nodus_tools.tool_brave_search") as mock:
            mock.return_value = ToolResult(success=True, output="results")
            dispatch_tool("brave_search", {"query": "test"})
            mock.assert_called_once_with("test", 5)

    def test_dispatch_brave_search_custom_count(self):
        with patch("nodus_tools.tool_brave_search") as mock:
            mock.return_value = ToolResult(success=True, output="ok")
            dispatch_tool("brave_search", {"query": "test", "count": 3})
            mock.assert_called_once_with("test", 3)

    def test_schema_includes_brave_search(self):
        names = {s["function"]["name"] for s in TOOL_SCHEMAS}
        assert "brave_search" in names


# ── Couverture branches restantes (reprise du WIP) ────────────────────────────

class TestRewritePowershellEdges:
    def test_or_or_becomes_if_not(self):
        assert "if (-not $?)" in _rewrite_windows_powershell("foo || bar")

    def test_invalid_cwd_returns_command(self):
        out = _rewrite_windows_powershell("echo hi", cwd="a\x00b")
        assert "echo hi" in out

    def test_invalid_cd_target_swallowed(self):
        import tempfile
        d = tempfile.mkdtemp()
        out = _rewrite_windows_powershell("cd a\x00b ; echo done", cwd=d)
        assert "echo done" in out

    def test_absolute_python_script_not_rewritten(self):
        out = _rewrite_windows_powershell(r"python C:\abs\s.py", cwd=r"C:\task")
        assert r"C:\abs\s.py" in out

    def test_relative_python_script_rewritten_to_absolute(self, tmp_path):
        out = _rewrite_windows_powershell("python demo.py", cwd=str(tmp_path))
        assert "demo.py" in out
        assert tmp_path.name in out  # ancré en absolu sur le cwd


class TestValidateAndPinEdges:
    def test_public_literal_ip_allowed(self):
        assert _is_blocked_url("http://8.8.8.8/path")[0] is False

    def test_resolves_to_no_valid_ip_blocked(self):
        with patch("nodus_tools.socket.getaddrinfo",
                   return_value=[(2, 1, 6, "", ("not-an-ip", 0))]):
            blocked, reason = _is_blocked_url("http://weird.example.org")
        assert blocked is True
        assert "resolve" in reason


class TestProtectedReference:
    def test_invalid_path_returns_none(self):
        assert _protected_reference_error("a\x00b") is None

    def test_edit_protected_file_blocked(self, tmp_path):
        (tmp_path / "mini_pytest.py").write_text("x")
        r = dispatch_tool("edit_file", {"file_path": "mini_pytest.py",
                                        "old_string": "x", "new_string": "y"},
                          cwd=str(tmp_path))
        assert r.success is False
        assert "protected reference" in r.error

    def test_write_protected_file_blocked(self, tmp_path):
        (tmp_path / "mini_pytest.py").write_text("x")
        r = dispatch_tool("write_file", {"file_path": "mini_pytest.py",
                                         "content": "z"}, cwd=str(tmp_path))
        assert r.success is False
        assert "protected reference" in r.error
