#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ TEMPLE IAM - Tests nodus_agent.py
⚡ Coverage target: 100%
Copyright © 2024 Temple IAM - All Rights Reserved
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from nodus_agent import (
    DEFAULT_MODEL,
    MAX_CHALLENGES,
    MAX_CONTEXT_CHARS,
    MAX_ROUNDS,
    AgentResult,
    MAX_CONTINUATIONS,
    _SYSTEM_PROMPT,
    _challenge_message,
    _chat,
    _continuation_message,
    _count_task_steps,
    _format_tool_result,
    _classify_backend_error,
    _is_continuation,
    _should_challenge,
    _trim_history,
    run_agent,
    stream_agent,
)
from nodus_tools import ToolResult


# ── Helpers ───────────────────────────────────────────────────────────────────

def _msg(content="", tool_calls=None):
    """Build a minimal Ollama assistant message dict."""
    msg = {"role": "assistant", "content": content}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return msg


def _tc(name, args, call_id="call_1"):
    """Build a tool_call entry."""
    return {"id": call_id, "function": {"name": name, "arguments": args}}


# ── _SYSTEM_PROMPT (garde-fous red-team) ──────────────────────────────────────

class TestSystemPrompt:
    def test_warns_tool_output_untrusted(self):
        # Durcissement red-team r3 : la sortie d'outil est DONNÉE, pas instruction
        low = _SYSTEM_PROMPT.lower()
        assert "untrusted data" in low
        assert "must not be obeyed" in low

    def test_claim_proves_nothing(self):
        assert "proves nothing" in _SYSTEM_PROMPT.lower()

    def test_immunizes_against_jailbreak_override(self):
        # Round 11 — système immunitaire : la LAW nomme les patterns d'override
        # pour que le modèle les RECONNAISSE et refuse de s'y conformer.
        low = _SYSTEM_PROMPT.lower()
        assert "resist override" in low
        assert "cannot be disabled" in low
        assert "jailbreak" in low
        assert "dan" in low  # persona non restreinte nommée
        for pattern in ("ignore previous", "developer mode",
                        "skip verification", "bypass the sandbox"):
            assert pattern in low

    def test_output_and_delivery_discipline(self):
        # Friction Windows mesuree (lab3) : Unicode console + round brule au polish.
        low = _SYSTEM_PROMPT.lower()
        assert "ascii only" in low
        assert "cp1252" in low
        assert "cosmetic polish" in low
        assert "ship the working artifact" in low

    def test_intent_gate_before_behavior_edit(self):
        # A/B GLM 5.2 x piege s2 (reports/glm52_s2_intent.md) : sans INTENT,
        # 0/2 code intact ; avec INTENT, 2/2 refusent de corrompre la spec.
        # Artefact force (fable-method Step 4.1) — mid-tier suit un point de
        # decision, pas une liste de valeurs.
        # P1 : si spec > test et pas de redefinition user, corriger le test
        # (pas seulement surfacer).
        low = _SYSTEM_PROMPT.lower()
        assert "intent gate" in low
        assert "intent: code does" in low
        assert "authority order" in low
        assert "explicit user statement" in low
        assert "make the tests pass" in low
        assert "does not promote the tests" in low
        assert "losing side" in low
        assert "leave correct" in low
        assert "readme/spec untouched" in low
        assert "do not stop at" in low

    def test_auth_gate_before_outward_action(self):
        # fable-method authorization gate — README n'autorise pas un deploy.
        # PENDING force (comme INTENT) : s9 A/B GLM avait 0/4 pending_named
        # avec la formulation "optionnelle" ; artefact obligatoire attendu.
        low = _SYSTEM_PROMPT.lower()
        assert "auth gate" in low
        assert 'auth: user said' in low
        assert "is not authorization" in low
        assert "pending artifact" in low or "mandatory artifact" in low
        assert "pending:" in low
        assert "awaiting your authorization" in low
        assert "silent drop" in low
        assert "open readme" in low
        assert "does not waive" in low or "health check green" in low

    def test_twins_gate_after_defect_fix(self):
        # fable-method twin check — un fix local sans sweep = theater.
        low = _SYSTEM_PROMPT.lower()
        assert "twins gate" in low
        assert "twins: searched" in low
        assert "presumed to recur" in low
        assert "verification theater" in low

    def test_gate_markers_preserved_for_cloud_evals(self):
        # C2 : e2e_glm_s2_intent / s5_twins / s9_auth decoupent _SYSTEM_PROMPT
        # entre des markers. S'ils derivent, les slices deviennent vides et les
        # evals cloud se vident SANS bruit (echec silencieux). Test de preservation.
        intent_start = "INTENT GATE — before ANY behavior-changing edit:"
        auth_start = "AUTH GATE — before ANY irreversible or outward-facing action:"
        twins_start = "TWINS GATE — whenever you fixed a defect:"
        tool_sel = "TOOL SELECTION:"
        for marker in (intent_start, auth_start, twins_start, tool_sel):
            assert marker in _SYSTEM_PROMPT, f"gate marker missing: {marker!r}"
        # Ordre impose par les evals → chaque slice est non-vide.
        assert _SYSTEM_PROMPT.find(intent_start) < _SYSTEM_PROMPT.find(tool_sel)
        assert _SYSTEM_PROMPT.find(twins_start) < _SYSTEM_PROMPT.find(tool_sel)
        assert _SYSTEM_PROMPT.find(auth_start) < _SYSTEM_PROMPT.find(twins_start)


# ── _count_task_steps ─────────────────────────────────────────────────────────

class TestCountTaskSteps:
    def test_empty_task_returns_one(self):
        assert _count_task_steps("") == 1

    def test_simple_task_returns_one(self):
        assert _count_task_steps("Count the functions in nodus_tools.py") == 1

    def test_two_numbered_dot_steps(self):
        assert _count_task_steps("1. grep pattern\n2. write file") == 2

    def test_three_numbered_dot_steps(self):
        assert _count_task_steps("1. grep\n2. write\n3. confirm") == 3

    def test_step_prefix_uppercase(self):
        assert _count_task_steps("STEP 1: bash\nSTEP 2: write\nSTEP 3: read") == 3

    def test_step_prefix_lowercase(self):
        assert _count_task_steps("step 1: grep\nstep 2: write") == 2

    def test_bash_prefix(self):
        assert _count_task_steps("bash 1: cmd\nbash 2: cmd\nbash 3: cmd") == 3

    def test_etape_prefix_ascii(self):
        assert _count_task_steps("etape 1: grep\netape 2: write") == 2

    def test_single_numbered_item_returns_one(self):
        # Only 1 numbered item — not a multi-step task
        assert _count_task_steps("1. do something important") == 1

    def test_parenthesis_numbering(self):
        assert _count_task_steps("1) first\n2) second\n3) third") == 3

    def test_minimum_always_one(self):
        assert _count_task_steps("no steps here") >= 1

    def test_then_connectors(self):
        assert _count_task_steps("read X then edit Y then write Z") == 3

    def test_max_challenges_constant_is_positive(self):
        assert MAX_CHALLENGES > 0


# ── _challenge_message ────────────────────────────────────────────────────────

class TestChallengeMessage:
    def test_returns_string(self):
        assert isinstance(_challenge_message(0, 3), str)

    def test_contains_steps_done(self):
        msg = _challenge_message(2, 5)
        assert "2" in msg

    def test_contains_steps_required(self):
        msg = _challenge_message(2, 5)
        assert "5" in msg

    def test_mentions_next_step_number(self):
        # next step = steps_done + 1
        msg = _challenge_message(2, 5)
        assert "3" in msg

    def test_message_zero_done(self):
        msg = _challenge_message(0, 3)
        assert "0" in msg
        assert "3" in msg
        assert "1" in msg  # next step = 1


# ── _should_challenge ─────────────────────────────────────────────────────────

class TestShouldChallenge:
    def test_single_step_never_challenges(self):
        # required_steps=1 → no enforcement, even with 0 tool calls
        assert _should_challenge(0, 1, 0) is False

    def test_two_step_zero_calls_challenges(self):
        assert _should_challenge(0, 2, 0) is True

    def test_two_step_one_call_challenges(self):
        # The granite bug: 1 call on a 2-step task MUST be challenged
        assert _should_challenge(1, 2, 0) is True

    def test_two_step_two_calls_no_challenge(self):
        # Both steps done → allowed to answer
        assert _should_challenge(2, 2, 0) is False

    def test_three_step_two_calls_challenges(self):
        assert _should_challenge(2, 3, 0) is True

    def test_three_step_three_calls_no_challenge(self):
        assert _should_challenge(3, 3, 0) is False

    def test_max_challenges_reached_stops(self):
        assert _should_challenge(0, 3, MAX_CHALLENGES) is False

    def test_below_max_challenges_still_fires(self):
        assert _should_challenge(0, 3, MAX_CHALLENGES - 1) is True

    def test_returns_bool(self):
        assert isinstance(_should_challenge(1, 2, 0), bool)


# ── _is_continuation / _continuation_message ──────────────────────────────────

class TestContinuationDetector:
    def test_empty_is_not_continuation(self):
        assert _is_continuation("") is False

    def test_real_conclusion_not_continuation(self):
        assert _is_continuation("I have created todo.py and all tests pass.") is False

    def test_next_ill_detected(self):
        assert _is_continuation("Next, I'll write the test file.") is True

    def test_first_ill_detected(self):
        assert _is_continuation("First, I'll read the current content.") is True

    def test_now_ill_detected(self):
        assert _is_continuation("Now I'll add the list command.") is True

    def test_going_to_detected(self):
        assert _is_continuation("I'm going to create the module now.") is True

    def test_french_marker(self):
        assert _is_continuation("Ensuite je vais écrire les tests.") is True

    def test_case_insensitive(self):
        assert _is_continuation("NEXT, WE will add the feature.") is True

    def test_returns_bool(self):
        assert isinstance(_is_continuation("hello"), bool)

    def test_message_is_string(self):
        assert isinstance(_continuation_message(), str)

    def test_message_mentions_tool_call(self):
        assert "tool call" in _continuation_message().lower()

    def test_max_continuations_positive(self):
        assert MAX_CONTINUATIONS > 0


# ── _trim_history ─────────────────────────────────────────────────────────────

def _make_history(tool_contents):
    """
    Construit un historique minimal:
      [system, user_task, tool0, tool1, ..., toolN]
    Utile pour tester _trim_history sans logique métier.
    """
    msgs = [
        {"role": "system",    "content": "sys"},
        {"role": "user",      "content": "task"},
    ]
    for content in tool_contents:
        msgs.append({"role": "tool", "content": content, "tool_call_id": "x"})
    return msgs


class TestTrimHistory:
    # ── Cas de base ──────────────────────────────────────────────────────────

    def test_empty_list_unchanged(self):
        assert _trim_history([]) == []

    def test_short_history_unchanged(self):
        msgs = _make_history(["small"])
        result = _trim_history(msgs, max_chars=9999)
        assert result == msgs

    def test_returns_new_list_when_trimming(self):
        # When trimming occurs a new list object is returned
        big = "x" * 500
        msgs = _make_history([big, "last"])
        result = _trim_history(msgs, max_chars=50)
        assert result is not msgs

    def test_returns_same_list_when_no_trim_needed(self):
        # When under limit the original list is returned as-is (no copy overhead)
        msgs = _make_history(["a"])
        result = _trim_history(msgs, max_chars=9999)
        assert result is msgs

    def test_max_context_chars_constant_exists(self):
        assert isinstance(MAX_CONTEXT_CHARS, int)
        assert MAX_CONTEXT_CHARS > 0

    # ── Troncature ───────────────────────────────────────────────────────────

    def test_long_tool_result_truncated(self):
        big = "x" * 500
        msgs = _make_history([big, "last"])
        result = _trim_history(msgs, max_chars=50)
        # premier tool result tronqué
        assert len(result[2]["content"]) < 500
        assert "…[+" in result[2]["content"]

    def test_truncated_content_starts_with_original(self):
        big = "ABCDE" * 100
        msgs = _make_history([big, "last"])
        result = _trim_history(msgs, max_chars=50)
        assert result[2]["content"].startswith("ABCDE")

    def test_truncated_suffix_shows_remaining_chars(self):
        big = "x" * 500
        msgs = _make_history([big, "last"])
        result = _trim_history(msgs, max_chars=50)
        # Suffix du genre "…[+380c]"
        assert "+380c]" in result[2]["content"]

    def test_last_message_always_preserved(self):
        big = "x" * 1000
        msgs = _make_history([big, "LAST_PRESERVED"])
        result = _trim_history(msgs, max_chars=50)
        assert result[-1]["content"] == "LAST_PRESERVED"

    def test_system_message_always_preserved(self):
        big = "x" * 1000
        msgs = _make_history([big, "last"])
        result = _trim_history(msgs, max_chars=50)
        assert result[0]["content"] == "sys"

    def test_initial_user_task_always_preserved(self):
        big = "x" * 1000
        msgs = _make_history([big, "last"])
        result = _trim_history(msgs, max_chars=50)
        assert result[1]["content"] == "task"

    def test_stops_trimming_once_under_limit(self):
        # 3 tool results: trimming first (300→~133) brings total under 500
        # sys(3)+task(4)+300+300+last(4) = 611 > 500
        # after trim first: 3+4+133+300+4 = 444 < 500 → stop
        msgs = _make_history(["x" * 300, "y" * 300, "last"])
        result = _trim_history(msgs, max_chars=500)
        # second tool result should be unchanged (trimming stopped after first)
        assert result[3]["content"] == "y" * 300

    def test_small_tool_result_not_truncated(self):
        # content ≤ 120 chars → not modified
        small = "a" * 120
        big = "z" * 5000
        msgs = _make_history([small, big, "last"])
        result = _trim_history(msgs, max_chars=50)
        # small should be untouched (len==120, not > 120)
        assert result[2]["content"] == small

    def test_non_tool_messages_not_truncated(self):
        big = "x" * 1000
        msgs = [
            {"role": "system",    "content": "sys"},
            {"role": "user",      "content": "task"},
            {"role": "assistant", "content": big},
            {"role": "tool",      "content": "z" * 500, "tool_call_id": "x"},
            {"role": "tool",      "content": "last"},
        ]
        result = _trim_history(msgs, max_chars=50)
        # assistant message NOT trimmed (only tool role targeted)
        assert result[2]["content"] == big

    def test_original_messages_not_mutated(self):
        big = "x" * 500
        msgs = _make_history([big, "last"])
        original_content = msgs[2]["content"]
        _trim_history(msgs, max_chars=50)
        # original list and dicts are untouched
        assert msgs[2]["content"] == original_content

    def test_length_preserved_when_under_limit(self):
        msgs = _make_history(["a", "b", "c"])
        result = _trim_history(msgs, max_chars=9999)
        assert len(result) == len(msgs)


# ── AgentResult ───────────────────────────────────────────────────────────────

class TestAgentResult:
    def test_str_returns_answer(self):
        r = AgentResult(answer="hello", tool_calls=2, rounds=3, stopped_reason="done")
        assert str(r) == "hello"

    def test_attributes_stored(self):
        r = AgentResult(answer="hi", tool_calls=1, rounds=2, stopped_reason="max_rounds")
        assert r.tool_calls == 1
        assert r.rounds == 2
        assert r.stopped_reason == "max_rounds"
        assert r.answer == "hi"

    def test_lessons_default_empty(self):
        r = AgentResult(answer="hi", tool_calls=0, rounds=1, stopped_reason="done")
        assert r.lessons == []

    def test_lessons_stored(self):
        r = AgentResult(
            answer="hi", tool_calls=0, rounds=1, stopped_reason="done",
            lessons=["a", "b"],
        )
        assert r.lessons == ["a", "b"]


# ── _format_tool_result ────────────────────────────────────────────────────────

class TestFormatToolResult:
    def test_success_result(self):
        r = ToolResult(success=True, output="file contents")
        msg = _format_tool_result("call_123", r)
        assert msg["role"] == "tool"
        assert msg["tool_call_id"] == "call_123"
        assert "file contents" in msg["content"]

    def test_failure_result(self):
        r = ToolResult(success=False, output="", error="not found")
        msg = _format_tool_result("call_456", r)
        assert msg["role"] == "tool"
        assert "Error: not found" in msg["content"]


# ── _classify_backend_error ───────────────────────────────────────────────────

def _http_exc(status):
    from types import SimpleNamespace
    e = requests.HTTPError("boom")
    e.response = SimpleNamespace(status_code=status)
    return e


class TestClassifyBackendError:
    def test_no_response_is_ollama_error(self):
        reason, msg = _classify_backend_error(requests.ConnectionError("refused"))
        assert reason == "ollama_error" and "connection" in msg.lower()

    def test_429_surfaces_rate_limit(self):
        reason, msg = _classify_backend_error(_http_exc(429))
        assert reason == "http_429" and "rate-limited" in msg

    def test_401_surfaces_auth(self):
        reason, msg = _classify_backend_error(_http_exc(401))
        assert reason == "http_401" and "auth" in msg

    def test_unknown_status_still_surfaced(self):
        reason, msg = _classify_backend_error(_http_exc(500))
        assert reason == "http_500" and "500" in msg

    @patch("nodus_agent._chat")
    def test_run_agent_surfaces_http_429(self, mock_chat):
        mock_chat.side_effect = _http_exc(429)
        r = run_agent("do a thing", max_rounds=3)
        assert r.stopped_reason == "http_429"

    @patch("nodus_agent._chat")
    def test_stream_surfaces_http_429(self, mock_chat):
        mock_chat.side_effect = _http_exc(429)
        events = list(stream_agent("do a thing", max_rounds=3))
        assert any(e.get("reason") == "http_429" for e in events)


# ── _chat ─────────────────────────────────────────────────────────────────────

class TestChat:
    @patch("nodus_agent.requests.post")
    def test_returns_message_dict(self, mock_post):
        mock_post.return_value.json.return_value = {
            "message": {"role": "assistant", "content": "hello"}
        }
        mock_post.return_value.raise_for_status.return_value = None
        result = _chat([{"role": "user", "content": "hi"}], model="qwen3.5:2b")
        assert result["content"] == "hello"

    @patch("nodus_agent.requests.post")
    def test_includes_tools_in_payload(self, mock_post):
        mock_post.return_value.json.return_value = {"message": {}}
        mock_post.return_value.raise_for_status.return_value = None
        tools = [{"type": "function", "function": {"name": "bash"}}]
        _chat([], model="qwen3.5:2b", tools=tools)
        payload = mock_post.call_args[1]["json"]
        assert payload["tools"] == tools

    @patch("nodus_agent.requests.post")
    def test_no_tools_key_when_tools_is_none(self, mock_post):
        mock_post.return_value.json.return_value = {"message": {}}
        mock_post.return_value.raise_for_status.return_value = None
        _chat([], model="qwen3.5:2b", tools=None)
        payload = mock_post.call_args[1]["json"]
        assert "tools" not in payload

    @patch("nodus_agent.requests.post")
    def test_keep_alive_from_env(self, mock_post):
        mock_post.return_value.json.return_value = {"message": {}}
        mock_post.return_value.raise_for_status.return_value = None
        with patch.dict(os.environ, {"NODUS_OLLAMA_KEEP_ALIVE": "0"}, clear=False):
            _chat([], model="qwen3.5:2b")
        payload = mock_post.call_args[1]["json"]
        assert payload["keep_alive"] == 0

    @patch("nodus_agent.requests.post")
    def test_returns_empty_dict_when_no_message_key(self, mock_post):
        mock_post.return_value.json.return_value = {}
        mock_post.return_value.raise_for_status.return_value = None
        result = _chat([], model="qwen3.5:2b")
        assert result == {}

    @patch("nodus_agent.chat_api", return_value={"role": "assistant", "content": "from api"})
    @patch("nodus_agent.requests.post")
    def test_routes_to_api_backend_for_claude(self, mock_post, mock_api):
        # An API model must NOT hit Ollama; it goes through chat_api
        result = _chat([{"role": "user", "content": "hi"}], model="claude-sonnet-4-5")
        assert result["content"] == "from api"
        mock_api.assert_called_once()
        mock_post.assert_not_called()

    @patch("nodus_agent.chat_api", return_value={"role": "assistant", "content": "ds"})
    @patch("nodus_agent.requests.post")
    def test_routes_to_api_backend_for_deepseek(self, mock_post, mock_api):
        result = _chat([], model="deepseek-chat")
        assert result["content"] == "ds"
        mock_api.assert_called_once()
        mock_post.assert_not_called()

    @patch("nodus_agent.chat_api")
    @patch("nodus_agent.requests.post")
    def test_ollama_model_does_not_call_api(self, mock_post, mock_api):
        mock_post.return_value.json.return_value = {"message": {"content": "local"}}
        mock_post.return_value.raise_for_status.return_value = None
        _chat([], model="qwen3.5:2b")
        mock_api.assert_not_called()
        mock_post.assert_called_once()


# ── run_agent ─────────────────────────────────────────────────────────────────

class TestRunAgent:
    @patch("nodus_agent._chat")
    def test_final_answer_no_tools(self, mock_chat):
        mock_chat.return_value = _msg(content="The answer is 42")
        result = run_agent("What is the answer?")
        assert result.stopped_reason == "done"
        assert result.answer == "The answer is 42"
        assert result.tool_calls == 0
        assert result.rounds == 1

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_one_tool_call_then_done(self, mock_chat, mock_dispatch):
        mock_chat.side_effect = [
            _msg(tool_calls=[_tc("bash", {"command": "echo hi"})]),
            _msg(content="Done"),
        ]
        mock_dispatch.return_value = ToolResult(success=True, output="hi")
        result = run_agent("run echo hi")
        assert result.stopped_reason == "done"
        assert result.answer == "Done"
        assert result.tool_calls == 1
        assert result.rounds == 2

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_tool_args_as_json_string(self, mock_chat, mock_dispatch):
        mock_chat.side_effect = [
            _msg(tool_calls=[_tc("bash", '{"command": "ls"}')]),
            _msg(content="Listed"),
        ]
        mock_dispatch.return_value = ToolResult(success=True, output="file.py")
        run_agent("list files")
        mock_dispatch.assert_called_once_with("bash", {"command": "ls"}, cwd=None)

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_tool_args_invalid_json_string_falls_back_to_command(self, mock_chat, mock_dispatch):
        mock_chat.side_effect = [
            _msg(tool_calls=[_tc("bash", "echo hello")]),
            _msg(content="OK"),
        ]
        mock_dispatch.return_value = ToolResult(success=True, output="hello")
        run_agent("run something")
        mock_dispatch.assert_called_once_with("bash", {"command": "echo hello"}, cwd=None)

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_tool_call_without_id_uses_fallback(self, mock_chat, mock_dispatch):
        tc_no_id = {"function": {"name": "bash", "arguments": {"command": "ls"}}}
        mock_chat.side_effect = [
            _msg(tool_calls=[tc_no_id]),
            _msg(content="Done"),
        ]
        mock_dispatch.return_value = ToolResult(success=True, output="files")
        result = run_agent("task")
        assert result.answer == "Done"

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_max_rounds_returns_stopped_reason(self, mock_chat, mock_dispatch):
        mock_dispatch.return_value = ToolResult(success=True, output="hi")
        mock_chat.return_value = _msg(tool_calls=[_tc("bash", {"command": "ls"})])
        result = run_agent("task", max_rounds=3)
        assert result.stopped_reason == "max_rounds"
        assert result.rounds == 3

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_max_rounds_last_assistant_content_used(self, mock_chat, mock_dispatch):
        mock_dispatch.return_value = ToolResult(success=True, output="x")
        mock_chat.return_value = _msg(
            content="thinking...", tool_calls=[_tc("bash", {"command": "ls"})]
        )
        result = run_agent("task", max_rounds=2)
        assert result.stopped_reason == "max_rounds"
        assert "thinking..." in result.answer

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_max_rounds_empty_content_uses_fallback_message(self, mock_chat, mock_dispatch):
        mock_dispatch.return_value = ToolResult(success=True, output="x")
        mock_chat.return_value = _msg(content="", tool_calls=[_tc("bash", {"command": "ls"})])
        result = run_agent("task", max_rounds=2)
        assert result.stopped_reason == "max_rounds"
        assert "stopped" in result.answer.lower() or "2" in result.answer

    @patch("nodus_agent.requests.post")
    def test_ollama_connection_error(self, mock_post):
        import requests as req
        mock_post.side_effect = req.ConnectionError("refused")
        result = run_agent("do something")
        assert result.stopped_reason == "ollama_error"
        assert "connection error" in result.answer.lower()

    @patch("nodus_agent._chat")
    def test_cwd_injected_into_system_prompt(self, mock_chat):
        mock_chat.return_value = _msg(content="ok")
        run_agent("task", cwd="/my/project")
        messages = mock_chat.call_args[0][0]
        system = messages[0]
        assert system["role"] == "system"
        assert "/my/project" in system["content"]

    @patch("nodus_agent._chat")
    def test_no_cwd_system_prompt_unchanged(self, mock_chat):
        mock_chat.return_value = _msg(content="ok")
        run_agent("task", cwd=None)
        messages = mock_chat.call_args[0][0]
        system_content = messages[0]["content"]
        assert "Current working directory" not in system_content

    @patch("nodus_agent._chat")
    def test_default_model_used(self, mock_chat):
        mock_chat.return_value = _msg(content="ok")
        run_agent("task")
        assert mock_chat.call_args[1]["model"] == DEFAULT_MODEL

    @patch("nodus_agent._chat")
    def test_custom_model_forwarded(self, mock_chat):
        mock_chat.return_value = _msg(content="ok")
        run_agent("task", model="granite4.1:3b")
        assert mock_chat.call_args[1]["model"] == "granite4.1:3b"

    @patch("nodus_agent._chat")
    def test_empty_content_returns_no_response(self, mock_chat):
        mock_chat.return_value = _msg(content="")
        result = run_agent("task")
        assert result.answer == "(no response)"

    @patch("nodus_agent._chat")
    def test_verbose_prints_round_headers(self, mock_chat, capsys):
        mock_chat.return_value = _msg(content="Done")
        run_agent("task", verbose=True)
        out = capsys.readouterr().out
        assert "round 1" in out
        assert "final answer" in out

    @patch("nodus_agent._chat")
    def test_verbose_prints_task_and_model(self, mock_chat, capsys):
        mock_chat.return_value = _msg(content="Done")
        run_agent("my task here", verbose=True, model="qwen3.5:2b")
        out = capsys.readouterr().out
        assert "my task here" in out
        assert "qwen3.5:2b" in out

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_verbose_prints_tool_call_and_ok(self, mock_chat, mock_dispatch, capsys):
        mock_chat.side_effect = [
            _msg(tool_calls=[_tc("bash", {"command": "ls"})]),
            _msg(content="Done"),
        ]
        mock_dispatch.return_value = ToolResult(success=True, output="file.py")
        run_agent("task", verbose=True)
        out = capsys.readouterr().out
        assert "TOOL bash" in out
        assert "OK" in out

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_verbose_prints_err_on_tool_failure(self, mock_chat, mock_dispatch, capsys):
        mock_chat.side_effect = [
            _msg(tool_calls=[_tc("bash", {"command": "bad"})]),
            _msg(content="Done"),
        ]
        mock_dispatch.return_value = ToolResult(success=False, output="", error="fail")
        run_agent("task", verbose=True)
        out = capsys.readouterr().out
        assert "ERR" in out

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_verbose_max_rounds_warning(self, mock_chat, mock_dispatch, capsys):
        mock_dispatch.return_value = ToolResult(success=True, output="x")
        mock_chat.return_value = _msg(tool_calls=[_tc("bash", {"command": "ls"})])
        run_agent("task", max_rounds=1, verbose=True)
        out = capsys.readouterr().out
        assert "max_rounds" in out or "WARNING" in out

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_multiple_tool_calls_in_one_round(self, mock_chat, mock_dispatch):
        # Ollama can return multiple tool_calls in one message
        mock_chat.side_effect = [
            _msg(tool_calls=[
                _tc("bash", {"command": "ls"}, "c1"),
                _tc("bash", {"command": "pwd"}, "c2"),
            ]),
            _msg(content="Done"),
        ]
        mock_dispatch.return_value = ToolResult(success=True, output="x")
        result = run_agent("task")
        assert result.tool_calls == 2
        assert result.answer == "Done"

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_tool_args_as_empty_dict(self, mock_chat, mock_dispatch):
        tc = {"id": "c1", "function": {"name": "glob", "arguments": None}}
        mock_chat.side_effect = [
            _msg(tool_calls=[tc]),
            _msg(content="Done"),
        ]
        mock_dispatch.return_value = ToolResult(success=True, output="files")
        result = run_agent("task")
        # Should not crash — args defaults to {}
        assert result.answer == "Done"

    # ── Garde anti-shortcut ───────────────────────────────────────────────────

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_anti_shortcut_challenge_on_premature_answer(self, mock_chat, mock_dispatch):
        """Réponse après 0 tool calls sur tâche 3 étapes → challenge injecté."""
        mock_dispatch.return_value = ToolResult(success=True, output="x")
        mock_chat.side_effect = [
            _msg(content="premature"),                              # 0/3 → challenge
            _msg(tool_calls=[_tc("bash", {"command": "s1"})]),     # tool call 1
            _msg(tool_calls=[_tc("bash", {"command": "s2"})]),     # tool call 2
            _msg(tool_calls=[_tc("bash", {"command": "s3"})]),     # tool call 3
            _msg(content="final answer"),                           # 3 >= 3 → OK
        ]
        task = "1. do first\n2. do second\n3. confirm"
        result = run_agent(task)
        assert result.answer == "final answer"
        assert result.tool_calls == 3

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_anti_shortcut_multiple_challenges(self, mock_chat, mock_dispatch):
        """Plusieurs réponses prématurées → challenges successifs jusqu'au bon chemin."""
        mock_dispatch.return_value = ToolResult(success=True, output="x")
        mock_chat.side_effect = [
            _msg(content="premature 1"),                           # 0/3 → challenge 1
            _msg(content="premature 2"),                           # 0/3 → challenge 2
            _msg(tool_calls=[_tc("bash", {"command": "s1"})]),     # tool call 1
            _msg(content="premature 3"),                           # 1/3 → challenge 3
            _msg(tool_calls=[_tc("bash", {"command": "s2"})]),     # tool call 2
            _msg(tool_calls=[_tc("bash", {"command": "s3"})]),     # tool call 3
            _msg(content="real final"),                            # 3 >= 3 → OK
        ]
        task = "1. step one\n2. step two\n3. step three"
        result = run_agent(task)
        assert result.answer == "real final"
        assert result.tool_calls == 3

    @patch("nodus_agent._chat")
    def test_anti_shortcut_stops_after_max_challenges(self, mock_chat):
        """Après MAX_CHALLENGES injections, la réponse suivante est acceptée."""
        # Toujours réponse prématurée — doit s'arrêter après MAX_CHALLENGES
        mock_chat.return_value = _msg(content="always early")
        task = "1. step\n2. step\n3. step\n4. step"  # 4 étapes, min 3 tool calls
        result = run_agent(task, max_rounds=20)
        # Accepté après MAX_CHALLENGES épuisés
        assert result.stopped_reason == "done"
        assert result.answer == "always early"

    @patch("nodus_agent._chat")
    def test_anti_shortcut_not_triggered_for_single_step_task(self, mock_chat):
        """Tâche simple (1 étape) : pas de challenge, réponse immédiate OK."""
        mock_chat.return_value = _msg(content="direct answer")
        result = run_agent("What is 2+2?")
        assert result.answer == "direct answer"
        assert result.tool_calls == 0
        assert result.stopped_reason == "done"

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_anti_shortcut_verbose_prints_message(self, mock_chat, mock_dispatch, capsys):
        """En mode verbose, le challenge anti-shortcut est loggé."""
        mock_dispatch.return_value = ToolResult(success=True, output="x")
        mock_chat.side_effect = [
            _msg(content="too early"),                             # 0/3 → challenge
            _msg(tool_calls=[_tc("bash", {"command": "s1"})]),
            _msg(tool_calls=[_tc("bash", {"command": "s2"})]),
            _msg(tool_calls=[_tc("bash", {"command": "s3"})]),
            _msg(content="done"),
        ]
        task = "1. run this\n2. run that\n3. write result"
        run_agent(task, verbose=True)
        out = capsys.readouterr().out
        assert "ANTI-SHORTCUT" in out

    # ── Détecteur de continuation ─────────────────────────────────────────────

    @patch("nodus_agent._chat")
    def test_continuation_challenged(self, mock_chat):
        """Une réponse-narration (sans tool calls) est relancée, pas acceptée."""
        mock_chat.side_effect = [
            _msg(content="Next, I'll write the test file."),  # narration → relance
            _msg(content="All done, file created and tests pass."),  # vraie fin
        ]
        result = run_agent("simple task")
        assert result.answer == "All done, file created and tests pass."
        assert mock_chat.call_count == 2

    @patch("nodus_agent._chat")
    def test_continuation_stops_after_max(self, mock_chat):
        """Après MAX_CONTINUATIONS, on accepte même une narration (anti-boucle)."""
        mock_chat.return_value = _msg(content="Next, I'll keep going forever.")
        result = run_agent("simple task", max_rounds=20)
        assert result.stopped_reason == "done"
        # plafonné : MAX_CONTINUATIONS relances puis acceptation
        assert mock_chat.call_count == MAX_CONTINUATIONS + 1

    @patch("nodus_agent._chat")
    def test_real_conclusion_accepted_immediately(self, mock_chat):
        """Une vraie conclusion n'est PAS relancée."""
        mock_chat.return_value = _msg(content="I have created the file. Done.")
        result = run_agent("simple task")
        assert mock_chat.call_count == 1

    @patch("nodus_agent._chat")
    def test_continuation_verbose_prints(self, mock_chat, capsys):
        mock_chat.side_effect = [
            _msg(content="First, I'll read the file."),
            _msg(content="Finished."),
        ]
        run_agent("simple task", verbose=True)
        out = capsys.readouterr().out
        assert "CONTINUATION" in out

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_telemetry_emits_full_event_stream(self, mock_chat, mock_dispatch):
        """Le sink Grafana reçoit task → plan → tool_call → tool_result → result."""
        from nodus_grafana import GrafanaSink

        mock_chat.side_effect = [
            _msg(tool_calls=[
                _tc("bash", {"command": "echo hi"}, call_id="call_1"),
                _tc("bash", {"command": "echo done"}, call_id="call_2"),
            ]),
            _msg(content="Done"),
        ]
        mock_dispatch.return_value = ToolResult(success=True, output="hi")
        sink = GrafanaSink(mode="mock")
        result = run_agent(
            "run echo hi then stop",   # connecteur séquentiel → needs_planning=True
            plan=True,
            plan_source="nodus",
            plan_names=["bash", "bash"],   # 2 steps estimés (then) → pas d'anti-shortcut
            plan_slotfill=False,   # évite un appel _chat du slot-fill
            telemetry=sink,
        )
        assert result.answer == "Done"
        kinds = [e["kind"] for e in sink.events]
        assert kinds[0] == "task"
        assert "plan" in kinds
        assert kinds[-1] == "result"
        # le plan statique injecté
        plan_evt = next(e for e in sink.events if e["kind"] == "plan")
        assert plan_evt["names"] == ["bash", "bash"]
        # les tool_call + tool_result apparaissent
        assert sum(1 for e in sink.events if e["kind"] == "tool_call") == 2
        assert sum(1 for e in sink.events if e["kind"] == "tool_result") == 2
        sink.close()


# ── run_agent memory integration ──────────────────────────────────────────────

class TestRunAgentMemory:
    @patch("nodus_agent.append_memory_entry")
    @patch("nodus_agent.load_memory", return_value="")
    @patch("nodus_agent._chat")
    def test_memory_disabled_by_default(self, mock_chat, mock_load, mock_append):
        mock_chat.return_value = _msg(content="done")
        run_agent("simple task")
        # When memory=False, neither load nor append should be touched
        mock_load.assert_not_called()
        mock_append.assert_not_called()

    @patch("nodus_agent.append_memory_entry", return_value=True)
    @patch("nodus_agent.load_memory", return_value="")
    @patch("nodus_agent._chat")
    def test_memory_enabled_loads(self, mock_chat, mock_load, mock_append):
        mock_chat.return_value = _msg(content="done")
        run_agent("simple task", memory=True, memory_path="/tmp/m.md")
        mock_load.assert_called_once()

    @patch("nodus_agent.append_memory_entry", return_value=True)
    @patch("nodus_agent.load_memory", return_value="")
    @patch("nodus_agent._chat")
    def test_memory_enabled_saves_on_done(self, mock_chat, mock_load, mock_append):
        mock_chat.return_value = _msg(content="the result")
        run_agent("task X", memory=True, memory_path="/tmp/m.md")
        mock_append.assert_called_once()
        # The saved task and answer should match
        args = mock_append.call_args[0]
        assert "task X" in args  # task passed
        assert "the result" in args  # answer passed

    @patch("nodus_agent.append_memory_entry", return_value=True)
    @patch("nodus_agent.load_memory", return_value="previous fact: 42")
    @patch("nodus_agent._chat")
    def test_memory_content_injected_in_system(self, mock_chat, mock_load, mock_append):
        mock_chat.return_value = _msg(content="done")
        run_agent("task", memory=True, memory_path="/tmp/m.md")
        # The first _chat call's system message should contain the memory
        first_call_messages = mock_chat.call_args_list[0][0][0]
        system_msg = first_call_messages[0]["content"]
        assert "previous fact: 42" in system_msg

    @patch("nodus_agent.append_memory_entry", return_value=True)
    @patch("nodus_agent.load_memory", return_value="")
    @patch("nodus_agent._chat")
    def test_empty_memory_not_injected(self, mock_chat, mock_load, mock_append):
        mock_chat.return_value = _msg(content="done")
        run_agent("task", memory=True, memory_path="/tmp/m.md")
        first_call_messages = mock_chat.call_args_list[0][0][0]
        system_msg = first_call_messages[0]["content"]
        assert "MEMORY FROM PREVIOUS" not in system_msg

    @patch("nodus_agent.append_memory_entry", return_value=True)
    @patch("nodus_agent.load_memory", return_value="old fact")
    @patch("nodus_agent._chat")
    def test_memory_verbose_prints(self, mock_chat, mock_load, mock_append, capsys):
        mock_chat.return_value = _msg(content="done")
        run_agent("task", memory=True, memory_path="/tmp/m.md", verbose=True)
        out = capsys.readouterr().out
        assert "memory loaded" in out
        assert "memory saved" in out

    @patch("nodus_agent.append_memory_entry", return_value=False)
    @patch("nodus_agent.load_memory", return_value="old fact")
    @patch("nodus_agent._chat")
    def test_memory_save_failure_verbose(self, mock_chat, mock_load, mock_append, capsys):
        mock_chat.return_value = _msg(content="done")
        run_agent("task", memory=True, memory_path="/tmp/m.md", verbose=True)
        out = capsys.readouterr().out
        assert "SAVE FAILED" in out

    # ── Mémoire stoïcienne : se souvenir des échecs ───────────────────────────

    @patch("nodus_agent.append_memory_entry", return_value=True)
    @patch("nodus_agent.load_memory", return_value="")
    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_memory_saves_on_max_rounds(self, mock_chat, mock_dispatch, mock_load, mock_append):
        # Never answers → max_rounds. Memory must still record the failure.
        mock_chat.return_value = _msg(tool_calls=[_tc("bash", {"command": "x"})])
        mock_dispatch.return_value = ToolResult(success=True, output="ok")
        run_agent("hard task", memory=True, memory_path="/tmp/m.md", max_rounds=2)
        mock_append.assert_called_once()
        # The saved note must carry the original task and a FAILED marker
        saved_args = mock_append.call_args[0]
        assert "hard task" in saved_args
        assert any("FAILED" in str(a) for a in saved_args)

    @patch("nodus_agent.append_memory_entry", return_value=True)
    @patch("nodus_agent.load_memory", return_value="")
    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_no_memory_no_failure_save(self, mock_chat, mock_dispatch, mock_load, mock_append):
        # memory disabled → nothing saved even on max_rounds
        mock_chat.return_value = _msg(tool_calls=[_tc("bash", {"command": "x"})])
        mock_dispatch.return_value = ToolResult(success=True, output="ok")
        run_agent("hard task", max_rounds=2)
        mock_append.assert_not_called()

    @patch("nodus_agent.append_memory_entry", return_value=False)
    @patch("nodus_agent.load_memory", return_value="")
    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_memory_failure_save_verbose(self, mock_chat, mock_dispatch, mock_load, mock_append, capsys):
        mock_chat.return_value = _msg(tool_calls=[_tc("bash", {"command": "x"})])
        mock_dispatch.return_value = ToolResult(success=True, output="ok")
        run_agent("hard task", memory=True, memory_path="/tmp/m.md", max_rounds=2, verbose=True)
        out = capsys.readouterr().out
        assert "SAVE FAILED" in out


# ── run_agent planning integration ────────────────────────────────────────────

class TestRunAgentPlan:
    @patch("nodus_agent._chat")
    def test_plan_disabled_by_default(self, mock_chat):
        # plan=False → pas de pre-call planning : le premier appel est la boucle
        # ReAct (system + task). Le challenge anti-shortcut (reponse prematuree
        # sur tache multi-etapes) peut ajouter des rounds — aucun prompt plan.
        mock_chat.return_value = _msg(content="done")
        run_agent("read the file then count the lines and write a report now")
        first_msgs = mock_chat.call_args_list[0][0][0]
        assert first_msgs[0]["role"] == "system"
        assert first_msgs[1]["role"] == "user"
        assert "read the file then count" in first_msgs[1]["content"]
        for call in mock_chat.call_args_list:
            sys_content = call[0][0][0]["content"]
            assert "EXECUTION PLAN" not in sys_content

    @patch("nodus_agent._chat")
    def test_plan_not_triggered_for_simple_task(self, mock_chat):
        mock_chat.return_value = _msg(content="done")
        run_agent("list files", plan=True)
        # Simple task → no extra planning call
        assert mock_chat.call_count == 1

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_plan_triggered_for_complex_task(self, mock_chat, mock_dispatch):
        # Plan (2 steps) → 2 tool calls → answer. required_steps=2 satisfied.
        mock_chat.side_effect = [
            _msg(content="1. read file\n2. count lines"),       # plan
            _msg(tool_calls=[_tc("bash", {"command": "x"})]),   # tool call 1
            _msg(tool_calls=[_tc("bash", {"command": "y"})]),   # tool call 2
            _msg(content="all done"),                            # 2 >= 2 → answer
        ]
        mock_dispatch.return_value = ToolResult(success=True, output="ok")
        run_agent("read the file then count the lines", plan=True)
        # The first _chat call must be the planning prompt
        plan_prompt = mock_chat.call_args_list[0][0][0][0]["content"]
        assert "PLAN" in plan_prompt.upper()

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_plan_injected_in_system(self, mock_chat, mock_dispatch):
        mock_chat.side_effect = [
            _msg(content="1. step one\n2. step two"),           # plan
            _msg(tool_calls=[_tc("bash", {"command": "x"})]),   # tool call 1
            _msg(tool_calls=[_tc("bash", {"command": "y"})]),   # tool call 2
            _msg(content="done"),                                # 2 >= 2 → answer
        ]
        mock_dispatch.return_value = ToolResult(success=True, output="ok")
        run_agent("do A puis do B avec beaucoup de details ici", plan=True)
        # The second call (ReAct) system message should contain the plan
        react_messages = mock_chat.call_args_list[1][0][0]
        system_msg = react_messages[0]["content"]
        assert "EXECUTION PLAN" in system_msg
        assert "step one" in system_msg

    @patch("nodus_agent._chat")
    def test_plan_sets_required_steps(self, mock_chat):
        # Plan has 3 steps → required_steps=3. Agent answers immediately each
        # round → anti-shortcut fires MAX_CHALLENGES times, then returns.
        mock_chat.side_effect = [
            _msg(content="1. a\n2. b\n3. c"),  # plan
            _msg(content="premature 1"),        # round 1 → challenge 1
            _msg(content="premature 2"),        # round 2 → challenge 2
            _msg(content="premature 3"),        # round 3 → challenge 3
            _msg(content="final answer"),       # round 4 → MAX reached, returns
        ]
        result = run_agent(
            "do A puis B puis C with many words here to be complex", plan=True
        )
        assert result.answer == "final answer"
        assert mock_chat.call_count == 5

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_plan_ollama_error_skips_gracefully(self, mock_chat, mock_dispatch):
        # Planning call raises, ReAct still proceeds (2 steps → 2 tool calls)
        mock_chat.side_effect = [
            requests.RequestException("boom"),
            _msg(tool_calls=[_tc("bash", {"command": "x"})]),
            _msg(tool_calls=[_tc("bash", {"command": "y"})]),
            _msg(content="done anyway"),
        ]
        mock_dispatch.return_value = ToolResult(success=True, output="ok")
        result = run_agent("do A puis do B with enough words here ok", plan=True)
        assert result.answer == "done anyway"

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_plan_verbose_prints(self, mock_chat, mock_dispatch, capsys):
        mock_chat.side_effect = [
            _msg(content="1. one\n2. two"),                     # plan
            _msg(tool_calls=[_tc("bash", {"command": "x"})]),   # tool call 1
            _msg(tool_calls=[_tc("bash", {"command": "y"})]),   # tool call 2
            _msg(content="done"),                                # 2 >= 2 → answer
        ]
        mock_dispatch.return_value = ToolResult(success=True, output="ok")
        run_agent("do A puis do B with sufficient words to plan", plan=True, verbose=True)
        out = capsys.readouterr().out
        assert "plan source=cloud" in out

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_plan_error_verbose_prints(self, mock_chat, mock_dispatch, capsys):
        mock_chat.side_effect = [
            requests.RequestException("down"),
            _msg(tool_calls=[_tc("bash", {"command": "x"})]),
            _msg(tool_calls=[_tc("bash", {"command": "y"})]),
            _msg(content="done"),
        ]
        mock_dispatch.return_value = ToolResult(success=True, output="ok")
        run_agent("do A puis do B with sufficient words here", plan=True, verbose=True)
        out = capsys.readouterr().out
        assert "planning skipped" in out

    @patch("nodus_agent._chat")
    def test_plan_source_off_skips_cloud(self, mock_chat):
        # plan_source="off" → aucun appel planning ; le premier appel est ReAct.
        mock_chat.return_value = _msg(content="done")
        run_agent(
            "read the file then count the lines and write a report now",
            plan=True,
            plan_source="off",
        )
        first_msgs = mock_chat.call_args_list[0][0][0]
        assert first_msgs[0]["role"] == "system"
        assert "EXECUTION PLAN" not in first_msgs[0]["content"]
        assert first_msgs[1]["role"] == "user"
        assert "read the file then count" in first_msgs[1]["content"]

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    @patch("nodus_agent.try_plan_tool_names")
    @patch("nodus_agent.fill_plan_targets", return_value=["TODO", None])
    def test_plan_source_nodus_valid_no_cloud_plan(
        self, mock_fill, mock_nodus, mock_chat, mock_dispatch
    ):
        # fill_plan_targets est mocke (sinon il consommerait des reponses _chat
        # de la side_effect ci-dessous — le slot-fill appelle _chat en interne).
        mock_nodus.return_value = ["grep", "read_file"]
        mock_chat.side_effect = [
            _msg(tool_calls=[_tc("grep", {"pattern": "x"})]),
            _msg(tool_calls=[_tc("read_file", {"path": "a.py"})]),
            _msg(content="done"),
        ]
        mock_dispatch.return_value = ToolResult(success=True, output="ok")
        run_agent(
            "search then read the file with enough words here please",
            plan=True,
            plan_source="nodus",
        )
        # No cloud planning call — first _chat is ReAct (system + task)
        first_msgs = mock_chat.call_args_list[0][0][0]
        assert first_msgs[0]["role"] == "system"
        assert "SUGGESTED TOOL SEQUENCE" in first_msgs[0]["content"]
        assert "`grep`" in first_msgs[0]["content"]
        assert first_msgs[1]["role"] == "user"
        assert "search then read" in first_msgs[1]["content"]
        mock_nodus.assert_called_once()

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    @patch("nodus_agent.try_plan_tool_names")
    def test_plan_source_nodus_invalid_falls_back_cloud(
        self, mock_nodus, mock_chat, mock_dispatch
    ):
        mock_nodus.return_value = None
        mock_chat.side_effect = [
            _msg(content="1. grep\n2. read"),                   # cloud plan
            _msg(tool_calls=[_tc("bash", {"command": "x"})]),
            _msg(tool_calls=[_tc("bash", {"command": "y"})]),
            _msg(content="done"),
        ]
        mock_dispatch.return_value = ToolResult(success=True, output="ok")
        run_agent(
            "search then read the file with enough words here please",
            plan=True,
            plan_source="nodus",
        )
        plan_prompt = mock_chat.call_args_list[0][0][0][0]["content"]
        assert "PLAN" in plan_prompt.upper()


class TestRunAgentProfile:
    @patch("nodus_agent._chat")
    def test_no_profile_by_default(self, mock_chat):
        mock_chat.return_value = _msg(content="done")
        run_agent("write tests for x")
        system_msg = mock_chat.call_args_list[0][0][0][0]["content"]
        assert "ROLE: TEST" not in system_msg

    @patch("nodus_agent._chat")
    def test_explicit_profile_injected(self, mock_chat):
        mock_chat.return_value = _msg(content="done")
        run_agent("do something", profile="debug")
        system_msg = mock_chat.call_args_list[0][0][0][0]["content"]
        assert "ROLE: DEBUG" in system_msg

    @patch("nodus_agent._chat")
    def test_auto_profile_routes(self, mock_chat):
        mock_chat.return_value = _msg(content="done")
        run_agent("write unit tests for nodus_tools.py", profile="auto")
        system_msg = mock_chat.call_args_list[0][0][0][0]["content"]
        assert "ROLE: TEST" in system_msg

    @patch("nodus_agent._chat")
    def test_general_profile_no_block(self, mock_chat):
        mock_chat.return_value = _msg(content="done")
        run_agent("do X", profile="general")
        system_msg = mock_chat.call_args_list[0][0][0][0]["content"]
        assert "ROLE:" not in system_msg

    @patch("nodus_agent._chat")
    def test_auto_profile_general_for_plain_task(self, mock_chat):
        mock_chat.return_value = _msg(content="done")
        run_agent("just say hello", profile="auto")
        system_msg = mock_chat.call_args_list[0][0][0][0]["content"]
        assert "ROLE:" not in system_msg

    @patch("nodus_agent._chat")
    def test_profile_verbose_prints(self, mock_chat, capsys):
        mock_chat.return_value = _msg(content="done")
        run_agent("do X", profile="code", verbose=True)
        out = capsys.readouterr().out
        assert "profile: code" in out


# ── run_agent reflection integration ──────────────────────────────────────────

class TestRunAgentReflect:
    @patch("nodus_agent._chat")
    def test_no_reflect_empty_lessons(self, mock_chat):
        mock_chat.return_value = _msg(content="done")
        result = run_agent("do X")
        assert result.lessons == []

    @patch("nodus_agent.save_lessons", return_value=True)
    @patch("nodus_agent.load_lessons", return_value=[])
    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_reflect_clean_run_no_lessons(self, mock_chat, mock_dispatch, mock_load, mock_save):
        mock_chat.side_effect = [
            _msg(tool_calls=[_tc("bash", {"command": "x"})]),
            _msg(content="done"),
        ]
        mock_dispatch.return_value = ToolResult(success=True, output="ok")
        result = run_agent("do X", reflect=True)
        assert result.lessons == []

    @patch("nodus_agent.save_lessons", return_value=True)
    @patch("nodus_agent.load_lessons", return_value=[])
    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_reflect_repeated_errors_produce_lesson(self, mock_chat, mock_dispatch, mock_load, mock_save):
        # Two bash failures then answer → repeated-error lesson
        mock_chat.side_effect = [
            _msg(tool_calls=[_tc("bash", {"command": "bad"})]),
            _msg(tool_calls=[_tc("bash", {"command": "bad"})]),
            _msg(content="gave up"),
        ]
        mock_dispatch.return_value = ToolResult(success=False, output="", error="exit 1")
        result = run_agent("do X", reflect=True)
        assert any("bash" in l for l in result.lessons)

    @patch("nodus_agent.save_lessons", return_value=True)
    @patch("nodus_agent.load_lessons", return_value=[])
    @patch("nodus_agent._chat")
    def test_reflect_max_rounds_lesson(self, mock_chat, mock_load, mock_save):
        # Always returns tool calls → never finishes → max_rounds
        mock_chat.return_value = _msg(tool_calls=[_tc("bash", {"command": "x"})])
        with patch("nodus_agent.dispatch_tool", return_value=ToolResult(success=True, output="ok")):
            result = run_agent("do X", reflect=True, max_rounds=3)
        assert result.stopped_reason == "max_rounds"
        assert any("complex" in l.lower() or "round" in l.lower() for l in result.lessons)

    @patch("nodus_agent.save_lessons", return_value=True)
    @patch("nodus_agent.load_lessons", return_value=[])
    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_reflect_persists_to_lessons_store(self, mock_chat, mock_dispatch, mock_load, mock_save):
        mock_chat.side_effect = [
            _msg(tool_calls=[_tc("bash", {"command": "bad"})]),
            _msg(tool_calls=[_tc("bash", {"command": "bad"})]),
            _msg(content="done"),
        ]
        mock_dispatch.return_value = ToolResult(success=False, output="", error="exit 1")
        run_agent("do X", reflect=True)
        # The lessons store must be written with the merged lessons
        mock_save.assert_called_once()
        saved_lessons = mock_save.call_args[0][1]
        assert any("bash" in l for l in saved_lessons)

    @patch("nodus_agent.save_lessons", return_value=True)
    @patch("nodus_agent.load_lessons", return_value=["old lesson from before"])
    @patch("nodus_agent._chat")
    def test_reflect_injects_past_lessons(self, mock_chat, mock_load, mock_save):
        mock_chat.return_value = _msg(content="done")
        run_agent("do X", reflect=True)
        # The system prompt of the first call must contain the past lesson
        system_msg = mock_chat.call_args_list[0][0][0][0]["content"]
        assert "AVOID PAST MISTAKES" in system_msg
        assert "old lesson from before" in system_msg

    @patch("nodus_agent.save_lessons", return_value=True)
    @patch("nodus_agent.load_lessons", return_value=["prior lesson"])
    @patch("nodus_agent._chat")
    def test_reflect_past_lessons_verbose(self, mock_chat, mock_load, mock_save, capsys):
        mock_chat.return_value = _msg(content="done")
        run_agent("do X", reflect=True, verbose=True)
        out = capsys.readouterr().out
        assert "past lesson(s) loaded" in out

    @patch("nodus_agent.save_lessons", return_value=True)
    @patch("nodus_agent.load_lessons", return_value=[])
    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_reflect_verbose_prints(self, mock_chat, mock_dispatch, mock_load, mock_save, capsys):
        mock_chat.side_effect = [
            _msg(tool_calls=[_tc("bash", {"command": "bad"})]),
            _msg(tool_calls=[_tc("bash", {"command": "bad"})]),
            _msg(content="done"),
        ]
        mock_dispatch.return_value = ToolResult(success=False, output="", error="exit 1")
        run_agent("do X", reflect=True, verbose=True)
        out = capsys.readouterr().out
        assert "reflection:" in out

    @patch("nodus_agent.save_lessons", return_value=False)
    @patch("nodus_agent.load_lessons", return_value=[])
    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_reflect_save_failure_verbose(self, mock_chat, mock_dispatch, mock_load, mock_save, capsys):
        mock_chat.side_effect = [
            _msg(tool_calls=[_tc("bash", {"command": "bad"})]),
            _msg(tool_calls=[_tc("bash", {"command": "bad"})]),
            _msg(content="done"),
        ]
        mock_dispatch.return_value = ToolResult(success=False, output="", error="exit 1")
        run_agent("do X", reflect=True, verbose=True)
        out = capsys.readouterr().out
        assert "SAVE FAILED" in out


# ── run_agent skills integration ──────────────────────────────────────────────

class TestRunAgentSkills:
    @patch("nodus_agent._chat")
    def test_no_skills_by_default(self, mock_chat):
        mock_chat.return_value = _msg(content="done")
        run_agent("write a file")
        system_msg = mock_chat.call_args_list[0][0][0][0]["content"]
        assert "SKILLS (authoritative" not in system_msg

    @patch("nodus_agent._chat")
    def test_skills_injected_when_enabled(self, mock_chat):
        mock_chat.return_value = _msg(content="done")
        run_agent("write a file with the count", skills=True)
        system_msg = mock_chat.call_args_list[0][0][0][0]["content"]
        assert "SKILLS (authoritative" in system_msg
        assert "write_file" in system_msg

    @patch("nodus_agent._chat")
    def test_skills_no_match_no_block(self, mock_chat):
        mock_chat.return_value = _msg(content="done")
        run_agent("xyzzy qwerty", skills=True)
        system_msg = mock_chat.call_args_list[0][0][0][0]["content"]
        assert "SKILLS (authoritative" not in system_msg

    @patch("nodus_agent._chat")
    def test_skills_verbose_prints(self, mock_chat, capsys):
        mock_chat.return_value = _msg(content="done")
        run_agent("write a file", skills=True, verbose=True)
        out = capsys.readouterr().out
        assert "skill(s) injected" in out


# ── run_agent verification integration ────────────────────────────────────────

class TestRunAgentVerify:
    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_no_verify_accepts_unverified_answer(self, mock_chat, mock_dispatch, tmp_path):
        # Without verify, a claimed-done answer is accepted even if file missing
        mock_chat.side_effect = [
            _msg(tool_calls=[_tc("bash", {"command": "x"})]),
            _msg(content="I createdvresult.txt"),
        ]
        mock_dispatch.return_value = ToolResult(success=True, output="ok")
        result = run_agent("write result.txt", cwd=str(tmp_path))
        assert result.stopped_reason == "done"

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_verify_rejects_missing_file(self, mock_chat, mock_dispatch, tmp_path):
        # The model claims done but never creates the file → verify forces retry
        mock_chat.side_effect = [
            _msg(content="done, I wrote result.txt"),     # claim 1 → verify rejects
            _msg(content="really done now"),               # claim 2 → verify rejects
            _msg(content="truly finished"),                # claim 3 → verify rejects
            _msg(content="final"),                         # retries exhausted → FAIL-CLOSED
        ]
        result = run_agent("write result.txt", cwd=str(tmp_path), verify=True)
        # 4 chat calls: 3 verification retries, then the fail-closed gate fires
        assert mock_chat.call_count == 4
        assert result.stopped_reason == "verify_failed"

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_verify_accepts_when_file_exists(self, mock_chat, mock_dispatch, tmp_path):
        # If the file actually exists, verify passes immediately
        (tmp_path / "result.txt").write_text("13", encoding="utf-8")
        mock_chat.return_value = _msg(content="done")
        result = run_agent("write result.txt", cwd=str(tmp_path), verify=True)
        assert result.stopped_reason == "done"
        assert mock_chat.call_count == 1

    @patch("nodus_agent._chat")
    def test_verify_no_expected_files_no_effect(self, mock_chat, tmp_path):
        # Task with no file-creation intent → verify is a no-op
        mock_chat.return_value = _msg(content="the answer is 42")
        result = run_agent("what is 6 times 7?", cwd=str(tmp_path), verify=True)
        assert result.stopped_reason == "done"
        assert mock_chat.call_count == 1

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_verify_passes_once_file_created(self, mock_chat, mock_dispatch, tmp_path):
        # Round 1: claim done (file missing) → verify rejects.
        # Round 2: the tool actually creates the file.
        # Round 3: claim done → verify passes.
        target = tmp_path / "result.txt"

        def _create(*_args, **_kwargs):
            target.write_text("13", encoding="utf-8")
            return ToolResult(success=True, output="written")

        mock_dispatch.side_effect = _create
        mock_chat.side_effect = [
            _msg(content="done (lying)"),                          # verify rejects
            _msg(tool_calls=[_tc("write_file", {"file_path": str(target)})]),  # real create
            _msg(content="done for real"),                         # verify passes
        ]
        result = run_agent("write result.txt", cwd=str(tmp_path), verify=True)
        assert result.answer == "done for real"
        assert target.exists()

    @patch("nodus_agent._chat")
    def test_content_verify_rejects_broken_py(self, mock_chat, tmp_path, capsys):
        # Un .py présent mais qui NE COMPILE PAS → la gate de contenu mord
        # (alors que verify_files le voit comme "présent").
        (tmp_path / "out.py").write_text("def f(:\n    pass\n", encoding="utf-8")
        mock_chat.return_value = _msg(content="done")
        run_agent("write out.py", cwd=str(tmp_path), verify=True,
                  verbose=True, max_rounds=8)
        assert "CONTENT-VERIFY" in capsys.readouterr().out

    @patch("nodus_agent._chat")
    def test_stream_content_verify_event(self, mock_chat, tmp_path):
        (tmp_path / "out.py").write_text("def f(:\n", encoding="utf-8")
        mock_chat.return_value = _msg(content="done")
        events = list(stream_agent("write out.py", cwd=str(tmp_path),
                                   verify=True, max_rounds=8))
        assert any(e["type"] == "content_verify" for e in events)

    @patch("nodus_agent._chat")
    def test_verify_verbose_prints(self, mock_chat, tmp_path, capsys):
        mock_chat.side_effect = [
            _msg(content="claimed done"),   # verify retry 1
            _msg(content="still lying"),    # verify retry 2
            _msg(content="more"),           # verify retry 3
            _msg(content="final"),          # retries exhausted → accept
        ]
        run_agent("write result.txt", cwd=str(tmp_path), verify=True, verbose=True)
        out = capsys.readouterr().out
        assert "VERIFY" in out


# ── Oracle sémantique (gate avec dents) ───────────────────────────────────────

class TestOracleGate:
    """La gate refuse le « done » si les tests ne rejettent pas le code cassé."""

    _TASK = (
        "create lru.py and test_lru.py, run python test_lru.py and prove exit 0"
    )

    def _setup_files(self, tmp_path):
        # impl + test réels : le verify fichiers ET commande (exit 0) passent,
        # de sorte que la gate ORACLE soit bien atteinte.
        (tmp_path / "lru.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        (tmp_path / "test_lru.py").write_text("print('ok')\n", encoding="utf-8")

    @patch("nodus_agent.evaluate_oracle_checks")
    @patch("nodus_agent._chat")
    def test_oracle_rejects_vacuous_then_passes(
        self, mock_chat, mock_eval, tmp_path, capsys
    ):
        self._setup_files(tmp_path)
        mock_chat.return_value = _msg(content="done")
        mock_eval.side_effect = [
            {"reason": "vacuous", "target": "lru.py", "score": 0.0,
             "survived": ["arithmetic Add -> Sub"], "ok": False},
            None,  # 2e passage : suite renforcée → certifiée
        ]
        result = run_agent(
            self._TASK, cwd=str(tmp_path), verify=True, oracle=True,
            verbose=True, max_rounds=6,
        )
        assert result.stopped_reason == "done"
        assert mock_eval.call_count == 2
        assert "ORACLE" in capsys.readouterr().out

    @patch("nodus_agent.evaluate_oracle_checks")
    @patch("nodus_agent._chat")
    def test_oracle_off_skips_gate(self, mock_chat, mock_eval, tmp_path):
        # Sans --oracle, la gate n'est jamais consultée.
        self._setup_files(tmp_path)
        mock_chat.return_value = _msg(content="done")
        run_agent(self._TASK, cwd=str(tmp_path), verify=True, oracle=False)
        mock_eval.assert_not_called()

    @patch("nodus_agent.evaluate_oracle_checks")
    @patch("nodus_agent._chat")
    def test_stream_oracle_event(self, mock_chat, mock_eval, tmp_path):
        self._setup_files(tmp_path)
        mock_chat.return_value = _msg(content="done")
        mock_eval.side_effect = [
            {"reason": "vacuous", "target": "lru.py", "score": 0.0,
             "survived": ["x"], "ok": False},
            None,
        ]
        events = list(stream_agent(
            self._TASK, cwd=str(tmp_path), verify=True, oracle=True, max_rounds=6,
        ))
        assert any(
            e["type"] == "oracle" and e["reason"] == "vacuous" for e in events
        )
        assert any(e["type"] == "done" for e in events)

    # ── Oracle d'acceptation (intention humaine) ─────────────────────────────

    _ATASK = "create impl.py; assert impl_fn(2) == 4"

    @patch("nodus_agent.acceptance_verdict")
    @patch("nodus_agent._chat")
    def test_acceptance_rejects_then_passes(self, mock_chat, mock_av, tmp_path, capsys):
        (tmp_path / "impl.py").write_text("def impl_fn(x):\n    return x\n", encoding="utf-8")
        mock_chat.return_value = _msg(content="done")
        mock_av.side_effect = [
            {"ok": False, "reason": "fail",
             "failures": ["assert impl_fn(2) == 4 -> AssertionError()"]},
            {"ok": True, "reason": "pass", "failures": []},
        ]
        result = run_agent(
            self._ATASK, cwd=str(tmp_path), verify=True, oracle=True,
            verbose=True, max_rounds=6,
        )
        assert result.stopped_reason == "done"
        assert mock_av.call_count == 2
        assert "ACCEPTANCE" in capsys.readouterr().out

    @patch("nodus_agent.acceptance_verdict")
    @patch("nodus_agent._chat")
    def test_stream_acceptance_event(self, mock_chat, mock_av, tmp_path):
        (tmp_path / "impl.py").write_text("def impl_fn(x):\n    return x\n", encoding="utf-8")
        mock_chat.return_value = _msg(content="done")
        mock_av.side_effect = [
            {"ok": False, "reason": "fail", "failures": ["x -> e"]},
            {"ok": True, "reason": "pass", "failures": []},
        ]
        events = list(stream_agent(
            self._ATASK, cwd=str(tmp_path), verify=True, oracle=True, max_rounds=6,
        ))
        assert any(
            e["type"] == "acceptance" and e["reason"] == "fail" for e in events
        )
        assert any(e["type"] == "done" for e in events)

    @patch("nodus_agent._chat")
    def test_code_task_relaxes_read_budget(self, mock_chat, tmp_path, capsys):
        # Tâche de code (.py) → budget de lecture relâché (anti read-paralysis).
        (tmp_path / "foo.py").write_text("x = 1\n", encoding="utf-8")
        mock_chat.return_value = _msg(content="done")
        run_agent("create foo.py with a helper", cwd=str(tmp_path),
                  model="openrouter/x", verify=True, verbose=True, max_rounds=3)
        assert "read budget relaxed" in capsys.readouterr().out

    # ── Oracle de falsification (reverse-NODUS) ──────────────────────────────

    _FTASK = "create median.py; falsify against median_props.py"

    @patch("nodus_agent.evaluate_falsify")
    @patch("nodus_agent._chat")
    def test_falsify_rejects_then_passes(self, mock_chat, mock_fal, tmp_path, capsys):
        (tmp_path / "median.py").write_text("def median(x):\n    return 0\n", encoding="utf-8")
        mock_chat.return_value = _msg(content="done")
        mock_fal.side_effect = [
            {"property": "even_average", "counterexample": "[1,2]", "detail": "out=2"},
            None,  # 2e passage : corrigé → plus de contre-exemple
        ]
        result = run_agent(self._FTASK, cwd=str(tmp_path), verify=True, oracle=True,
                           verbose=True, max_rounds=6)
        assert result.stopped_reason == "done"
        assert mock_fal.call_count == 2
        assert "FALSIFY" in capsys.readouterr().out

    @patch("nodus_agent.evaluate_falsify")
    @patch("nodus_agent._chat")
    def test_stream_falsify_event(self, mock_chat, mock_fal, tmp_path):
        (tmp_path / "median.py").write_text("def median(x):\n    return 0\n", encoding="utf-8")
        mock_chat.return_value = _msg(content="done")
        mock_fal.side_effect = [
            {"property": "even_average", "counterexample": "[1,2]", "detail": "o"},
            None,
        ]
        events = list(stream_agent(self._FTASK, cwd=str(tmp_path), verify=True,
                                   oracle=True, max_rounds=6))
        assert any(e["type"] == "falsify" and e["property"] == "even_average"
                   for e in events)
        assert any(e["type"] == "done" for e in events)

    # ── Oracle perceptuel (média) ────────────────────────────────────────────

    _PTASK = "render out.png matching ref.png"

    @patch("nodus_agent.evaluate_perceptual_checks")
    @patch("nodus_agent._chat")
    def test_perceptual_rejects_then_passes(
        self, mock_chat, mock_peval, tmp_path, capsys
    ):
        # out.png/ref.png sont désormais des expected_files (Gap A) → ils doivent
        # exister pour que la file-verify passe avant la gate perceptuelle.
        (tmp_path / "out.png").write_bytes(b"\x89PNG\x00")
        (tmp_path / "ref.png").write_bytes(b"\x89PNG\x00")
        mock_chat.return_value = _msg(content="done")
        mock_peval.side_effect = [
            {"reason": "mismatch", "target": "out.png", "similarity": 0.4,
             "teeth_similarity": 0.1, "ok": False},
            None,  # 2e passage : rendu corrigé → match
        ]
        result = run_agent(
            self._PTASK, cwd=str(tmp_path), verify=True, oracle=True,
            verbose=True, max_rounds=6,
        )
        assert result.stopped_reason == "done"
        assert mock_peval.call_count == 2
        assert "PERCEPTUAL" in capsys.readouterr().out

    @patch("nodus_agent.evaluate_perceptual_checks")
    @patch("nodus_agent._chat")
    def test_stream_perceptual_event(self, mock_chat, mock_peval, tmp_path):
        (tmp_path / "out.png").write_bytes(b"\x89PNG\x00")
        (tmp_path / "ref.png").write_bytes(b"\x89PNG\x00")
        mock_chat.return_value = _msg(content="done")
        mock_peval.side_effect = [
            {"reason": "mismatch", "target": "out.png", "similarity": 0.4,
             "ok": False},
            None,
        ]
        events = list(stream_agent(
            self._PTASK, cwd=str(tmp_path), verify=True, oracle=True, max_rounds=6,
        ))
        assert any(
            e["type"] == "perceptual" and e["reason"] == "mismatch" for e in events
        )
        assert any(e["type"] == "done" for e in events)


# ── run_agent régime adaptatif backend (policy) ───────────────────────────────

class TestRunAgentPolicy:
    @patch("nodus_agent._chat")
    def test_cloud_injects_transition_gate(self, mock_chat):
        mock_chat.return_value = _msg(content="done")
        run_agent("do a thing", model="openrouter/anthropic/claude-opus-4.8")
        system_msg = mock_chat.call_args_list[0][0][0][0]["content"]
        assert "DECIDE FAST" in system_msg

    @patch("nodus_agent._chat")
    def test_local_no_transition_gate(self, mock_chat):
        mock_chat.return_value = _msg(content="done")
        run_agent("do a thing", model="qwen3.5:2b")
        system_msg = mock_chat.call_args_list[0][0][0][0]["content"]
        assert "DECIDE FAST" not in system_msg

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_cloud_forces_write_after_bash_probes(self, mock_chat, mock_dispatch):
        seen = []

        def chat(messages, model, tools=None, text_tools=False):
            seen.append(" ".join(m.get("content", "") or "" for m in messages))
            return _msg(tool_calls=[_tc("bash", {"command": "python -c pass"})])

        mock_chat.side_effect = chat
        mock_dispatch.return_value = ToolResult(success=True, output="ok")
        run_agent(
            "probe only",
            model="openrouter/deepseek/deepseek-v4-pro",
            max_rounds=8,
            verbose=True,
        )
        assert any("Stop reading" in s for s in seen)

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_cloud_forces_write_after_read_budget(self, mock_chat, mock_dispatch):
        seen = []

        def chat(messages, model, tools=None, text_tools=False):
            seen.append(" ".join(m.get("content", "") or "" for m in messages))
            return _msg(tool_calls=[_tc("read_file", {"file_path": "x"})])
        mock_chat.side_effect = chat
        mock_dispatch.return_value = ToolResult(success=True, output="data")
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            run_agent("read everything", model="openrouter/anthropic/claude-opus-4.8",
                      max_rounds=8, verbose=True)
        # Après le budget de lecture, une relance "force l'écriture" est injectée.
        assert any("Stop reading" in s for s in seen)
        out = buf.getvalue()
        assert "policy: cloud" in out
        assert "FORCE-WRITE" in out

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_stream_cloud_forces_write(self, mock_chat, mock_dispatch):
        def chat(messages, model, tools=None, text_tools=False):
            return _msg(tool_calls=[_tc("read_file", {"file_path": "x"})])
        mock_chat.side_effect = chat
        mock_dispatch.return_value = ToolResult(success=True, output="data")
        events = list(stream_agent(
            "read everything", model="openrouter/anthropic/claude-opus-4.8",
            max_rounds=8))
        assert any(e.get("type") == "force_write" for e in events)

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_local_never_forces_write(self, mock_chat, mock_dispatch):
        seen = []

        def chat(messages, model, tools=None, text_tools=False):
            seen.append(" ".join(m.get("content", "") or "" for m in messages))
            return _msg(tool_calls=[_tc("read_file", {"file_path": "x"})])
        mock_chat.side_effect = chat
        mock_dispatch.return_value = ToolResult(success=True, output="data")
        run_agent("read everything", model="qwen3.5:2b", max_rounds=8)
        # Local : pas de forçage, la boucle de lecture est tolérée.
        assert not any("Stop reading" in s for s in seen)


class TestMultiHitGrepGuard:
    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_injects_multi_hit_after_ambiguous_grep(self, mock_chat, mock_dispatch, capsys):
        seen = []

        def chat(messages, model, tools=None, text_tools=False):
            blob = " ".join(m.get("content", "") or "" for m in messages)
            seen.append(blob)
            if any("MULTI-HIT SEARCH" in (m.get("content") or "") for m in messages):
                return _msg(content="done after disambiguation")
            return _msg(tool_calls=[_tc("grep", {
                "pattern": "estimate_task_steps",
                "output_mode": "files_with_matches",
            })])

        mock_chat.side_effect = chat
        mock_dispatch.return_value = ToolResult(
            success=True,
            output="nodus_agent.py\nnodus_planner.py\nreal_usage_p0_harness.py",
        )
        run_agent(
            "Search for estimate_task_steps then write found.txt",
            model="qwen3.5:2b",
            max_rounds=4,
            verbose=True,
        )
        assert any("MULTI-HIT SEARCH" in s for s in seen)
        assert any("nodus_planner.py" in s for s in seen)
        out = capsys.readouterr().out
        assert "MULTI-HIT" in out

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_no_multi_hit_on_single_file(self, mock_chat, mock_dispatch):
        seen = []

        def chat(messages, model, tools=None, text_tools=False):
            seen.append(" ".join(m.get("content", "") or "" for m in messages))
            if len(seen) >= 2:
                return _msg(content="done")
            return _msg(tool_calls=[_tc("grep", {"pattern": "only_here"})])

        mock_chat.side_effect = chat
        mock_dispatch.return_value = ToolResult(success=True, output="only.py")
        run_agent("find only_here", model="qwen3.5:2b", max_rounds=3)
        assert not any("MULTI-HIT SEARCH" in s for s in seen)

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_stream_emits_multi_hit_event(self, mock_chat, mock_dispatch):
        def chat(messages, model, tools=None, text_tools=False):
            if any("MULTI-HIT SEARCH" in (m.get("content") or "") for m in messages):
                return _msg(content="done")
            return _msg(tool_calls=[_tc("grep", {"pattern": "x"})])

        mock_chat.side_effect = chat
        mock_dispatch.return_value = ToolResult(success=True, output="a.py\nb.py")
        events = list(stream_agent("find x", model="qwen3.5:2b", max_rounds=4))
        assert any(e.get("type") == "multi_hit" for e in events)


class TestRunAgentPolicyMore:
    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_writing_resets_read_counter(self, mock_chat, mock_dispatch):
        # Lecture puis écriture puis lecture → le compteur retombe, pas de forçage
        seq = [
            _msg(tool_calls=[_tc("read_file", {"file_path": "a"})]),
            _msg(tool_calls=[_tc("write_file", {"file_path": "a", "content": "x"})]),
            _msg(tool_calls=[_tc("read_file", {"file_path": "b"})]),
            _msg(content="done"),
        ]
        mock_chat.side_effect = seq
        mock_dispatch.return_value = ToolResult(success=True, output="ok")
        r = run_agent("mix reads and writes",
                      model="openrouter/anthropic/claude-opus-4.8", max_rounds=8)
        assert r.stopped_reason == "done"

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_cloud_blocks_duplicate_read_file(self, mock_chat, mock_dispatch):
        seq = [
            _msg(tool_calls=[_tc("read_file", {"file_path": "big.py"})]),
            _msg(tool_calls=[_tc("read_file", {"file_path": "big.py"})]),
            _msg(content="done"),
        ]
        mock_chat.side_effect = seq
        mock_dispatch.return_value = ToolResult(success=True, output="data")
        run_agent("inspect big.py", model="openrouter/deepseek/deepseek-v4-pro", max_rounds=5)
        assert mock_dispatch.call_count == 1

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_cloud_read_paralysis_stops_after_force_writes(self, mock_chat, mock_dispatch):
        mock_chat.return_value = _msg(tool_calls=[_tc("read_file", {"file_path": "x"})])
        mock_dispatch.return_value = ToolResult(success=True, output="data")
        r = run_agent(
            "read forever",
            model="openrouter/deepseek/deepseek-v4-pro",
            max_rounds=30,
        )
        assert r.stopped_reason == "read_paralysis"

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_cloud_refocus_on_thrash(self, mock_chat, mock_dispatch, tmp_path, capsys):
        # L'agent écrit du BRUIT (scratch.txt) alors que result.txt est attendu et
        # jamais créé (dispatch mocké) → au-delà du budget thrash : REFOCUS injecté.
        seen = []

        def chat(messages, model, tools=None, text_tools=False):
            seen.append(" ".join(m.get("content", "") or "" for m in messages))
            return _msg(tool_calls=[_tc("write_file", {"file_path": "scratch.txt",
                                                       "content": "noise"})])
        mock_chat.side_effect = chat
        mock_dispatch.return_value = ToolResult(success=True, output="ok")
        run_agent("create result.txt with the answer",
                  model="openrouter/anthropic/claude-opus-4.8",
                  cwd=str(tmp_path), verify=True, max_rounds=10, verbose=True)
        out = capsys.readouterr().out
        assert "REFOCUS" in out
        assert any("writing noise" in s for s in seen)

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_on_target_write_does_not_refocus(self, mock_chat, mock_dispatch, tmp_path):
        # Livrer la CIBLE attendue (result.txt apparaît réellement) = progrès →
        # l'ensemble manquant se vide → pas de recentrage.
        seen = []

        def chat(messages, model, tools=None, text_tools=False):
            seen.append(" ".join(m.get("content", "") or "" for m in messages))
            return _msg(tool_calls=[_tc("write_file", {"file_path": "result.txt",
                                                       "content": "x"})])
        mock_chat.side_effect = chat

        def disp(name, args, cwd=None):
            (Path(cwd) / "result.txt").write_text("delivered")
            return ToolResult(success=True, output="ok")
        mock_dispatch.side_effect = disp
        run_agent("create result.txt with the answer",
                  model="openrouter/anthropic/claude-opus-4.8",
                  cwd=str(tmp_path), verify=True, max_rounds=10)
        assert not any("writing noise" in s for s in seen)

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_rewriting_present_expected_still_thrash(self, mock_chat, mock_dispatch,
                                                     tmp_path, capsys):
        # Trou exposé par un run live : un attendu DÉJÀ présent (present.txt) est
        # réécrit en boucle pendant qu'un autre attendu (target.md) reste absent.
        # Réécrire le présent ne fait PAS progresser le manquant → REFOCUS doit fire.
        (tmp_path / "present.txt").write_text("already here")
        seen = []

        def chat(messages, model, tools=None, text_tools=False):
            seen.append(" ".join(m.get("content", "") or "" for m in messages))
            return _msg(tool_calls=[_tc("write_file", {"file_path": "present.txt",
                                                       "content": "again"})])
        mock_chat.side_effect = chat
        mock_dispatch.return_value = ToolResult(success=True, output="ok")
        run_agent("edit present.txt and create target.md",
                  model="openrouter/anthropic/claude-opus-4.8",
                  cwd=str(tmp_path), verify=True, max_rounds=10, verbose=True)
        out = capsys.readouterr().out
        assert "REFOCUS" in out
        assert any("target.md" in s for s in seen)

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_bash_created_junk_triggers_refocus(self, mock_chat, mock_dispatch,
                                                tmp_path, capsys):
        # Surface du 2e run live : le bruit créé par BASH (pas write_file) doit
        # être vu — bash ∈ MUTATING_TOOLS, round actif sans livraison → REFOCUS.
        counter = {"n": 0}

        def chat(messages, model, tools=None, text_tools=False):
            return _msg(tool_calls=[_tc("bash", {"command": "base64 x > dump"})])
        mock_chat.side_effect = chat

        def disp(name, args, cwd=None):
            counter["n"] += 1
            (Path(cwd) / f"_dump_{counter['n']}.txt").write_text("noise")
            return ToolResult(success=True, output="ok")
        mock_dispatch.side_effect = disp

        run_agent("create target.md with a design doc",
                  model="openrouter/anthropic/claude-opus-4.8",
                  cwd=str(tmp_path), verify=True, max_rounds=10, verbose=True)
        out = capsys.readouterr().out
        assert "REFOCUS" in out

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_stream_bash_junk_refocus(self, mock_chat, mock_dispatch, tmp_path):
        counter = {"n": 0}
        mock_chat.side_effect = lambda m, model, tools=None, text_tools=False: _msg(
            tool_calls=[_tc("bash", {"command": "echo x > dump"})])

        def disp(name, args, cwd=None):
            counter["n"] += 1
            (Path(cwd) / f"_dump_{counter['n']}.txt").write_text("noise")
            return ToolResult(success=True, output="ok")
        mock_dispatch.side_effect = disp
        events = list(stream_agent(
            "create target.md", model="openrouter/anthropic/claude-opus-4.8",
            cwd=str(tmp_path), verify=True, max_rounds=10))
        assert any(e.get("type") == "refocus" for e in events)

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_delivering_expected_resets_thrash(self, mock_chat, mock_dispatch,
                                               tmp_path, capsys):
        # Créer du bruit PUIS livrer l'attendu (réel) → le progrès remet à zéro,
        # pas de REFOCUS malgré le bruit antérieur.
        counter = {"n": 0}

        def chat(messages, model, tools=None, text_tools=False):
            counter["n"] += 1
            return _msg(tool_calls=[_tc("bash", {"command": "noise"})])
        mock_chat.side_effect = chat

        def disp(name, args, cwd=None):
            # round 1 → bruit ; round 2 → livre l'attendu target.md (progrès)
            if counter["n"] == 1:
                (Path(cwd) / "_noise.txt").write_text("x")
            else:
                (Path(cwd) / "target.md").write_text("# doc")
            return ToolResult(success=True, output="ok")
        mock_dispatch.side_effect = disp
        run_agent("create target.md", model="openrouter/anthropic/claude-opus-4.8",
                  cwd=str(tmp_path), verify=True, max_rounds=4, verbose=True)
        out = capsys.readouterr().out
        assert "REFOCUS" not in out

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_stream_delivering_expected_resets_thrash(self, mock_chat, mock_dispatch,
                                                      tmp_path):
        counter = {"n": 0}

        def chat(messages, model, tools=None, text_tools=False):
            counter["n"] += 1
            return _msg(tool_calls=[_tc("bash", {"command": "noise"})])
        mock_chat.side_effect = chat

        def disp(name, args, cwd=None):
            if counter["n"] == 1:
                (Path(cwd) / "_noise.txt").write_text("x")
            else:
                (Path(cwd) / "target.md").write_text("# doc")
            return ToolResult(success=True, output="ok")
        mock_dispatch.side_effect = disp
        events = list(stream_agent(
            "create target.md", model="openrouter/anthropic/claude-opus-4.8",
            cwd=str(tmp_path), verify=True, max_rounds=4))
        assert not any(e.get("type") == "refocus" for e in events)


    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_bash_inplace_no_newfile_refocus(self, mock_chat, mock_dispatch,
                                             tmp_path, capsys):
        # Surface du 3e run live : bash qui édite IN-PLACE / fichiers transitoires
        # → AUCUN nouveau fichier au bord du round. Le signal outcome (round actif
        # sans livraison) le voit quand même. C'est ce qu'un diff de fichiers ratait.
        def chat(messages, model, tools=None, text_tools=False):
            return _msg(tool_calls=[_tc("bash", {"command": "sed -i s/a/b/ x"})])
        mock_chat.side_effect = chat
        mock_dispatch.return_value = ToolResult(success=True, output="ok")  # rien créé
        run_agent("create target.md with a design doc",
                  model="openrouter/anthropic/claude-opus-4.8",
                  cwd=str(tmp_path), verify=True, max_rounds=10, verbose=True)
        out = capsys.readouterr().out
        assert "REFOCUS" in out

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_reads_only_does_not_refocus(self, mock_chat, mock_dispatch,
                                         tmp_path, capsys):
        # Lectures seules = domaine du force-write, PAS du thrash → pas de REFOCUS
        # (on ne sur-déclenche pas sur l'exploration légitime).
        def chat(messages, model, tools=None, text_tools=False):
            return _msg(tool_calls=[_tc("read_file", {"file_path": "x"})])
        mock_chat.side_effect = chat
        mock_dispatch.return_value = ToolResult(success=True, output="data")
        run_agent("create target.md", model="openrouter/anthropic/claude-opus-4.8",
                  cwd=str(tmp_path), verify=True, max_rounds=10, verbose=True)
        out = capsys.readouterr().out
        assert "REFOCUS" not in out

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_stream_refocus_on_thrash(self, mock_chat, mock_dispatch, tmp_path):
        def chat(messages, model, tools=None, text_tools=False):
            return _msg(tool_calls=[_tc("write_file", {"file_path": "scratch.txt",
                                                       "content": "noise"})])
        mock_chat.side_effect = chat
        mock_dispatch.return_value = ToolResult(success=True, output="ok")
        events = list(stream_agent(
            "create result.txt with the answer",
            model="openrouter/anthropic/claude-opus-4.8",
            cwd=str(tmp_path), verify=True, max_rounds=10))
        assert any(e.get("type") == "refocus" for e in events)


# ── run_agent knowledge integration (pont mémoire) ────────────────────────────

class TestRunAgentKnowledge:
    @patch("nodus_agent.save_finding", return_value=True)
    @patch("nodus_agent.load_findings", return_value=[])
    @patch("nodus_agent._chat")
    def test_no_knowledge_by_default(self, mock_chat, mock_load, mock_save):
        mock_chat.return_value = _msg(content="done")
        run_agent("investigate ssrf")
        mock_load.assert_not_called()
        mock_save.assert_not_called()

    @patch("nodus_agent.save_finding", return_value=True)
    @patch("nodus_agent.load_findings", return_value=[])
    @patch("nodus_agent._chat")
    def test_knowledge_saves_finding(self, mock_chat, mock_load, mock_save):
        mock_chat.return_value = _msg(content="Finding: revalidate each redirect hop")
        run_agent("investigate the ssrf redirect", knowledge=True)
        mock_save.assert_called_once()
        args = mock_save.call_args[0]
        assert "investigate the ssrf redirect" in args
        assert any("revalidate" in str(a) for a in args)

    @patch("nodus_agent.save_finding", return_value=True)
    @patch("nodus_agent.load_findings")
    @patch("nodus_agent._chat")
    def test_knowledge_injects_recalled(self, mock_chat, mock_load, mock_save):
        from nodus_knowledge import Finding as _F
        mock_load.return_value = [_F("revalidate each redirect hop",
                                     ("ssrf", "redirect", "fetch"), "2026-01-01")]
        mock_chat.return_value = _msg(content="done")
        run_agent("fix the ssrf redirect in fetch", knowledge=True)
        system_msg = mock_chat.call_args_list[0][0][0][0]["content"]
        assert "PAST FINDINGS" in system_msg
        assert "revalidate each redirect hop" in system_msg

    @patch("nodus_agent.save_finding", return_value=True)
    @patch("nodus_agent.load_findings")
    @patch("nodus_agent._chat")
    def test_knowledge_verbose_prints(self, mock_chat, mock_load, mock_save):
        from nodus_knowledge import Finding as _F
        mock_load.return_value = [_F("revalidate each redirect hop",
                                     ("ssrf", "redirect", "fetch"), "2026-01-01")]
        mock_chat.return_value = _msg(content="done")
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            run_agent("fix the ssrf redirect in fetch", knowledge=True, verbose=True)
        out = buf.getvalue()
        assert "recalled from knowledge" in out
        assert "finding saved to knowledge" in out


# ── run_agent playbook integration ────────────────────────────────────────────

class TestRunAgentPlaybook:
    @patch("nodus_agent.add_recipe", return_value=True)
    @patch("nodus_agent.match_recipes")
    @patch("nodus_agent.load_recipes", return_value=[])
    @patch("nodus_agent._chat")
    def test_no_playbook_by_default(self, mock_chat, mock_load, mock_match, mock_add):
        mock_chat.return_value = _msg(content="done")
        run_agent("build a stack")
        mock_load.assert_not_called()
        mock_add.assert_not_called()

    @patch("nodus_agent.add_recipe", return_value=True)
    @patch("nodus_agent.load_recipes", return_value=[])
    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_playbook_saves_winning_path(self, mock_chat, mock_dispatch, mock_load, mock_add):
        mock_chat.side_effect = [
            _msg(tool_calls=[_tc("write_file", {"file_path": "x", "content": "y"})]),
            _msg(content="done"),
        ]
        mock_dispatch.return_value = ToolResult(success=True, output="ok")
        run_agent("build a thing", playbook=True)
        mock_add.assert_called_once()
        # add_recipe(path, task, tool_path) — the tool path contains write_file
        args = mock_add.call_args[0]
        assert "build a thing" in args
        assert any("write_file" in str(a) for a in args)

    @patch("nodus_agent.add_recipe", return_value=True)
    @patch("nodus_agent.load_recipes")
    @patch("nodus_agent._chat")
    def test_playbook_injects_matched_recipe(self, mock_chat, mock_load, mock_add):
        from nodus_playbook import Recipe as _R
        mock_load.return_value = [_R("build a stack with tests",
                                     ("build", "stack", "tests"), ("write_file", "bash"))]
        mock_chat.return_value = _msg(content="done")
        run_agent("build a queue with tests", playbook=True)
        system_msg = mock_chat.call_args_list[0][0][0][0]["content"]
        assert "PROVEN PATHS" in system_msg

    @patch("nodus_agent.add_recipe", return_value=True)
    @patch("nodus_agent.load_recipes", return_value=[])
    @patch("nodus_agent._chat")
    def test_playbook_verbose_prints(self, mock_chat, mock_load, mock_add):
        from nodus_playbook import Recipe as _R
        mock_load.return_value = [_R("build a stack with tests",
                                     ("build", "stack", "tests"), ("write_file", "bash"))]
        mock_chat.return_value = _msg(content="done")
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            run_agent("build a stack with tests", playbook=True, verbose=True)
        out = buf.getvalue()
        assert "proven path" in out
        assert "recipe saved" in out


# ── main() CLI ─────────────────────────────────────────────────────────────────

class TestMain:
    @patch("nodus_agent.run_agent")
    def test_main_returns_zero(self, mock_run):
        mock_run.return_value = AgentResult(
            answer="42", tool_calls=1, rounds=2, stopped_reason="done"
        )
        with patch("sys.argv", ["nodus_agent", "What is the answer?"]):
            from nodus_agent import main
            rc = main()
        assert rc == 0

    @patch("nodus_agent.run_agent")
    def test_main_passes_all_args(self, mock_run):
        mock_run.return_value = AgentResult(
            answer="ok", tool_calls=0, rounds=1, stopped_reason="done"
        )
        with patch("sys.argv", [
            "nodus_agent", "task here",
            "--model", "granite4.1:3b",
            "--verbose",
            "--max-rounds", "5",
            "--cwd", "/my/project",
        ]):
            from nodus_agent import main
            main()

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["model"] == "granite4.1:3b"
        assert call_kwargs["verbose"] is True
        assert call_kwargs["max_rounds"] == 5
        assert call_kwargs["cwd"] == "/my/project"

    @patch("nodus_agent.run_agent")
    def test_main_memory_flag(self, mock_run):
        mock_run.return_value = AgentResult(
            answer="ok", tool_calls=0, rounds=1, stopped_reason="done"
        )
        with patch("sys.argv", ["nodus_agent", "task", "--memory"]):
            from nodus_agent import main
            main()
        assert mock_run.call_args[1]["memory"] is True

    @patch("nodus_agent.run_agent")
    def test_main_memory_default_false(self, mock_run):
        mock_run.return_value = AgentResult(
            answer="ok", tool_calls=0, rounds=1, stopped_reason="done"
        )
        with patch("sys.argv", ["nodus_agent", "task"]):
            from nodus_agent import main
            main()
        assert mock_run.call_args[1]["memory"] is False

    @patch("nodus_agent.run_agent")
    def test_main_plan_flag(self, mock_run):
        mock_run.return_value = AgentResult(
            answer="ok", tool_calls=0, rounds=1, stopped_reason="done"
        )
        with patch("sys.argv", ["nodus_agent", "task", "--plan"]):
            from nodus_agent import main
            main()
        assert mock_run.call_args[1]["plan"] is True

    @patch("nodus_agent.run_agent")
    def test_main_plan_default_false(self, mock_run):
        mock_run.return_value = AgentResult(
            answer="ok", tool_calls=0, rounds=1, stopped_reason="done"
        )
        with patch("sys.argv", ["nodus_agent", "task"]):
            from nodus_agent import main
            main()
        assert mock_run.call_args[1]["plan"] is False

    @patch("nodus_agent.run_agent")
    def test_main_profile_flag(self, mock_run):
        mock_run.return_value = AgentResult(
            answer="ok", tool_calls=0, rounds=1, stopped_reason="done"
        )
        with patch("sys.argv", ["nodus_agent", "task", "--profile", "debug"]):
            from nodus_agent import main
            main()
        assert mock_run.call_args[1]["profile"] == "debug"

    @patch("nodus_agent.run_agent")
    def test_main_profile_default_none(self, mock_run):
        mock_run.return_value = AgentResult(
            answer="ok", tool_calls=0, rounds=1, stopped_reason="done"
        )
        with patch("sys.argv", ["nodus_agent", "task"]):
            from nodus_agent import main
            main()
        assert mock_run.call_args[1]["profile"] is None

    @patch("nodus_agent.run_agent")
    def test_main_reflect_flag(self, mock_run):
        mock_run.return_value = AgentResult(
            answer="ok", tool_calls=0, rounds=1, stopped_reason="done"
        )
        with patch("sys.argv", ["nodus_agent", "task", "--reflect"]):
            from nodus_agent import main
            main()
        assert mock_run.call_args[1]["reflect"] is True

    @patch("nodus_agent.run_agent")
    def test_main_skills_flag(self, mock_run):
        mock_run.return_value = AgentResult(
            answer="ok", tool_calls=0, rounds=1, stopped_reason="done"
        )
        with patch("sys.argv", ["nodus_agent", "task", "--skills"]):
            from nodus_agent import main
            main()
        assert mock_run.call_args[1]["skills"] is True

    @patch("nodus_agent.run_agent")
    def test_main_skills_default_false(self, mock_run):
        mock_run.return_value = AgentResult(
            answer="ok", tool_calls=0, rounds=1, stopped_reason="done"
        )
        with patch("sys.argv", ["nodus_agent", "task"]):
            from nodus_agent import main
            main()
        assert mock_run.call_args[1]["skills"] is False

    @patch("nodus_agent.run_agent")
    def test_main_verify_flag(self, mock_run):
        mock_run.return_value = AgentResult(
            answer="ok", tool_calls=0, rounds=1, stopped_reason="done"
        )
        with patch("sys.argv", ["nodus_agent", "task", "--verify"]):
            from nodus_agent import main
            main()
        assert mock_run.call_args[1]["verify"] is True

    @patch("nodus_agent.run_agent")
    def test_main_verify_default_false(self, mock_run):
        mock_run.return_value = AgentResult(
            answer="ok", tool_calls=0, rounds=1, stopped_reason="done"
        )
        with patch("sys.argv", ["nodus_agent", "task"]):
            from nodus_agent import main
            main()
        assert mock_run.call_args[1]["verify"] is False

    @patch("nodus_agent.run_agent")
    def test_main_oracle_flag(self, mock_run):
        mock_run.return_value = AgentResult(
            answer="ok", tool_calls=0, rounds=1, stopped_reason="done"
        )
        with patch("sys.argv", ["nodus_agent", "task", "--verify", "--oracle"]):
            from nodus_agent import main
            main()
        assert mock_run.call_args[1]["oracle"] is True

    @patch("nodus_agent.run_agent")
    def test_main_oracle_default_false(self, mock_run):
        mock_run.return_value = AgentResult(
            answer="ok", tool_calls=0, rounds=1, stopped_reason="done"
        )
        with patch("sys.argv", ["nodus_agent", "task"]):
            from nodus_agent import main
            main()
        assert mock_run.call_args[1]["oracle"] is False

    @patch("nodus_amplify.amplified_run")
    def test_main_amplify_flag(self, mock_amp):
        from nodus_amplify import AmplifyResult
        mock_amp.return_value = AmplifyResult(
            verified=True, attempts=2, index=1,
            result=AgentResult(answer="ok", tool_calls=3, rounds=4,
                               stopped_reason="done"),
        )
        with patch("sys.argv", ["nodus_agent", "task", "--amplify", "3"]):
            from nodus_agent import main
            main()
        assert mock_amp.call_args[1]["n"] == 3

    @patch("nodus_amplify.amplified_run")
    def test_main_amplify_no_verified_result(self, mock_amp):
        from nodus_amplify import AmplifyResult
        mock_amp.return_value = AmplifyResult(
            verified=False, attempts=2, index=None, result=None
        )
        with patch("sys.argv", ["nodus_agent", "task", "--amplify", "2"]):
            from nodus_agent import main
            main()
        assert mock_amp.called

    @patch("nodus_agent.run_agent")
    def test_main_prints_lessons(self, mock_run, capsys):
        mock_run.return_value = AgentResult(
            answer="ok", tool_calls=0, rounds=1, stopped_reason="done",
            lessons=["lesson one", "lesson two"],
        )
        with patch("sys.argv", ["nodus_agent", "task", "--reflect"]):
            from nodus_agent import main
            main()
        out = capsys.readouterr().out
        assert "Lessons learned" in out
        assert "lesson one" in out

    @patch("nodus_agent.run_agent")
    def test_main_no_lessons_section_when_empty(self, mock_run, capsys):
        mock_run.return_value = AgentResult(
            answer="ok", tool_calls=0, rounds=1, stopped_reason="done", lessons=[]
        )
        with patch("sys.argv", ["nodus_agent", "task"]):
            from nodus_agent import main
            main()
        out = capsys.readouterr().out
        assert "Lessons learned" not in out

    @patch("nodus_agent.run_agent")
    def test_main_uses_cwd_when_not_provided(self, mock_run):
        mock_run.return_value = AgentResult(
            answer="ok", tool_calls=0, rounds=1, stopped_reason="done"
        )
        with patch("sys.argv", ["nodus_agent", "task"]):
            from nodus_agent import main
            main()

        call_kwargs = mock_run.call_args[1]
        # cwd should be set to something (current dir)
        assert call_kwargs["cwd"] is not None
        assert call_kwargs["cwd"] != ""

    @patch("nodus_agent.run_agent")
    def test_main_prints_result(self, mock_run, capsys):
        mock_run.return_value = AgentResult(
            answer="The answer is 42",
            tool_calls=3,
            rounds=4,
            stopped_reason="done",
        )
        with patch("sys.argv", ["nodus_agent", "task"]):
            from nodus_agent import main
            main()

        out = capsys.readouterr().out
        assert "The answer is 42" in out
        assert "Tool calls: 3" in out
        assert "Rounds: 4" in out


# ── stream_agent ──────────────────────────────────────────────────────────────

class TestStreamAgent:
    @patch("nodus_agent._chat")
    def test_done_on_no_tool_calls(self, mock_chat):
        mock_chat.return_value = _msg(content="final answer")
        events = list(stream_agent("task"))
        assert events[-1]["type"] == "done"
        assert events[-1]["answer"] == "final answer"
        assert events[-1]["stopped_reason"] == "done"
        assert events[-1]["tool_calls"] == 0

    @patch("nodus_agent._chat")
    @patch("nodus_agent.dispatch_tool")
    def test_emits_round_and_result_events(self, mock_dispatch, mock_chat):
        mock_dispatch.return_value = ToolResult(success=True, output="output")
        mock_chat.side_effect = [
            _msg(tool_calls=[_tc("bash", {"command": "echo hi"})]),
            _msg(content="done"),
        ]
        events = list(stream_agent("task"))
        types = [e["type"] for e in events]
        assert "round" in types
        assert "result" in types
        assert "done" in types

    @patch("nodus_agent._chat")
    @patch("nodus_agent.dispatch_tool")
    def test_round_event_has_tool_name(self, mock_dispatch, mock_chat):
        mock_dispatch.return_value = ToolResult(success=True, output="x")
        mock_chat.side_effect = [
            _msg(tool_calls=[_tc("read_file", {"file_path": "/f.py"})]),
            _msg(content="done"),
        ]
        events = list(stream_agent("task"))
        round_ev = next(e for e in events if e["type"] == "round")
        assert round_ev["tool"] == "read_file"

    @patch("nodus_agent._chat")
    @patch("nodus_agent.dispatch_tool")
    def test_result_event_has_success_and_output(self, mock_dispatch, mock_chat):
        mock_dispatch.return_value = ToolResult(success=True, output="hello")
        mock_chat.side_effect = [
            _msg(tool_calls=[_tc("bash", {"command": "echo"})]),
            _msg(content="ok"),
        ]
        events = list(stream_agent("task"))
        result_ev = next(e for e in events if e["type"] == "result")
        assert result_ev["success"] is True
        assert "hello" in result_ev["output"]

    @patch("nodus_agent.requests.post")
    def test_ollama_error_yields_error_event(self, mock_post):
        import requests as req
        mock_post.side_effect = req.ConnectionError("refused")
        events = list(stream_agent("task"))
        assert events[0]["type"] == "error"
        assert "connection error" in events[0]["error"].lower()

    @patch("nodus_agent._chat")
    @patch("nodus_agent.dispatch_tool")
    def test_max_rounds_yields_done_with_max_rounds_reason(self, mock_dispatch, mock_chat):
        mock_dispatch.return_value = ToolResult(success=True, output="x")
        # Always return tool calls — forces max_rounds
        mock_chat.return_value = _msg(
            content="partial",
            tool_calls=[_tc("bash", {"command": "echo"})],
        )
        events = list(stream_agent("task", max_rounds=2))
        done = events[-1]
        assert done["type"] == "done"
        assert done["stopped_reason"] == "max_rounds"
        assert done["rounds"] == 2

    @patch("nodus_agent._chat")
    def test_cwd_injected_in_system_prompt(self, mock_chat):
        mock_chat.return_value = _msg(content="ok")
        list(stream_agent("task", cwd="/mydir"))
        messages = mock_chat.call_args[0][0]
        assert "/mydir" in messages[0]["content"]

    @patch("nodus_agent._chat")
    def test_default_model_used(self, mock_chat):
        mock_chat.return_value = _msg(content="ok")
        list(stream_agent("task"))
        assert mock_chat.call_args[1]["model"] == DEFAULT_MODEL

    @patch("nodus_agent._chat")
    def test_empty_answer_replaced_with_no_response(self, mock_chat):
        mock_chat.return_value = _msg(content="")
        events = list(stream_agent("task"))
        assert events[-1]["answer"] == "(no response)"

    @patch("nodus_agent._chat")
    @patch("nodus_agent.dispatch_tool")
    def test_string_args_parsed_as_json(self, mock_dispatch, mock_chat):
        """Couvre les lignes 344-347 : args en str JSON → json.loads()"""
        mock_dispatch.return_value = ToolResult(success=True, output="x")
        mock_chat.side_effect = [
            _msg(tool_calls=[{
                "id": "c1",
                "function": {
                    "name": "bash",
                    "arguments": '{"command": "echo hi"}',  # str, pas dict
                },
            }]),
            _msg(content="done"),
        ]
        events = list(stream_agent("task"))
        done = events[-1]
        assert done["type"] == "done"
        # dispatch_tool should have been called with parsed dict
        called_args = mock_dispatch.call_args[0][1]
        assert called_args == {"command": "echo hi"}

    @patch("nodus_agent._chat")
    @patch("nodus_agent.dispatch_tool")
    def test_invalid_json_string_args_fallback(self, mock_dispatch, mock_chat):
        """Couvre la ligne 347 : json.loads échoue → fallback bash"""
        mock_dispatch.return_value = ToolResult(success=True, output="x")
        mock_chat.side_effect = [
            _msg(tool_calls=[{
                "id": "c1",
                "function": {"name": "bash", "arguments": "echo hi"},  # pas du JSON
            }]),
            _msg(content="done"),
        ]
        events = list(stream_agent("task"))
        called_args = mock_dispatch.call_args[0][1]
        assert called_args == {"command": "echo hi"}

    # ── Garde anti-shortcut (stream) ──────────────────────────────────────────

    @patch("nodus_agent._chat")
    @patch("nodus_agent.dispatch_tool")
    def test_stream_challenge_event_on_premature_answer(self, mock_dispatch, mock_chat):
        """Réponse prématurée → event 'challenge' émis, boucle continue."""
        mock_dispatch.return_value = ToolResult(success=True, output="x")
        mock_chat.side_effect = [
            _msg(content="too early"),                              # 0/3 → challenge
            _msg(tool_calls=[_tc("bash", {"command": "s1"})]),
            _msg(tool_calls=[_tc("bash", {"command": "s2"})]),
            _msg(tool_calls=[_tc("bash", {"command": "s3"})]),
            _msg(content="final"),
        ]
        task = "1. do this\n2. do that\n3. confirm"
        events = list(stream_agent(task))
        types = [e["type"] for e in events]
        assert "challenge" in types
        assert events[-1]["type"] == "done"
        assert events[-1]["answer"] == "final"

    @patch("nodus_agent._chat")
    @patch("nodus_agent.dispatch_tool")
    def test_stream_challenge_event_has_correct_fields(self, mock_dispatch, mock_chat):
        """L'event 'challenge' contient steps_done et steps_required."""
        mock_dispatch.return_value = ToolResult(success=True, output="x")
        mock_chat.side_effect = [
            _msg(content="premature"),
            _msg(tool_calls=[_tc("bash", {"command": "s1"})]),
            _msg(tool_calls=[_tc("bash", {"command": "s2"})]),
            _msg(tool_calls=[_tc("bash", {"command": "s3"})]),
            _msg(content="ok"),
        ]
        task = "1. first\n2. second\n3. third"
        events = list(stream_agent(task))
        challenge_ev = next(e for e in events if e["type"] == "challenge")
        assert challenge_ev["steps_done"] == 0
        assert challenge_ev["steps_required"] == 3

    @patch("nodus_agent._chat")
    def test_stream_anti_shortcut_stops_after_max_challenges(self, mock_chat):
        """MAX_CHALLENGES atteint → réponse suivante acceptée même si prématurée."""
        mock_chat.return_value = _msg(content="always early")
        task = "1. step\n2. step\n3. step\n4. step"
        events = list(stream_agent(task, max_rounds=20))
        done = events[-1]
        assert done["type"] == "done"
        assert done["answer"] == "always early"

    @patch("nodus_agent._chat")
    def test_stream_no_challenge_for_single_step(self, mock_chat):
        """Tâche simple → pas de challenge, done immédiat."""
        mock_chat.return_value = _msg(content="answer")
        events = list(stream_agent("Just answer this question"))
        types = [e["type"] for e in events]
        assert "challenge" not in types
        assert events[-1]["type"] == "done"

    # ── Symétrie avec run_agent : skills / memory / verify / reflect ──────────

    @patch("nodus_agent._chat")
    def test_stream_skills_injected(self, mock_chat):
        mock_chat.return_value = _msg(content="done")
        list(stream_agent("write a file", skills=True))
        system_msg = mock_chat.call_args_list[0][0][0][0]["content"]
        assert "SKILLS (authoritative" in system_msg

    @patch("nodus_agent._chat")
    def test_stream_profile_injected(self, mock_chat):
        mock_chat.return_value = _msg(content="done")
        list(stream_agent("do X", profile="debug"))
        system_msg = mock_chat.call_args_list[0][0][0][0]["content"]
        assert "ROLE: DEBUG" in system_msg

    @patch("nodus_agent.append_memory_entry", return_value=True)
    @patch("nodus_agent.load_memory", return_value="prior fact")
    @patch("nodus_agent._chat")
    def test_stream_memory_loaded_and_saved(self, mock_chat, mock_load, mock_append):
        mock_chat.return_value = _msg(content="done")
        list(stream_agent("task", memory=True, memory_path="/tmp/m.md"))
        # memory injected
        system_msg = mock_chat.call_args_list[0][0][0][0]["content"]
        assert "prior fact" in system_msg
        # answer saved on done
        mock_append.assert_called_once()

    @patch("nodus_agent.append_memory_entry", return_value=True)
    @patch("nodus_agent.load_memory", return_value="")
    @patch("nodus_agent._chat")
    def test_stream_memory_saves_on_max_rounds(self, mock_chat, mock_load, mock_append):
        # Never answers → max_rounds → stoic memory records the failure
        mock_chat.return_value = _msg(tool_calls=[_tc("bash", {"command": "x"})])
        with patch("nodus_agent.dispatch_tool", return_value=ToolResult(success=True, output="ok")):
            list(stream_agent("hard task", memory=True, memory_path="/tmp/m.md", max_rounds=2))
        mock_append.assert_called_once()
        assert any("FAILED" in str(a) for a in mock_append.call_args[0])

    @patch("nodus_agent._chat")
    def test_stream_verify_event_on_missing_file(self, mock_chat, tmp_path):
        # Claims done but file missing → 'verify' event, loop continues
        mock_chat.side_effect = [
            _msg(content="done (lying)"),   # verify rejects
            _msg(content="really"),          # verify rejects
            _msg(content="more"),            # verify rejects
            _msg(content="final"),           # retries exhausted → accept
        ]
        events = list(stream_agent("write result.txt", cwd=str(tmp_path), verify=True))
        types = [e["type"] for e in events]
        assert "verify" in types
        verify_ev = next(e for e in events if e["type"] == "verify")
        assert "result.txt" in verify_ev["missing"]

    @patch("nodus_agent._chat")
    def test_stream_verify_passes_when_file_exists(self, mock_chat, tmp_path):
        (tmp_path / "result.txt").write_text("13", encoding="utf-8")
        mock_chat.return_value = _msg(content="done")
        events = list(stream_agent("write result.txt", cwd=str(tmp_path), verify=True))
        types = [e["type"] for e in events]
        assert "verify" not in types
        assert events[-1]["type"] == "done"

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_stream_skips_false_verify_after_read_file(self, mock_chat, mock_dispatch, tmp_path):
        target = tmp_path / "mini_pytest.py"
        target.write_text("ok", encoding="utf-8")
        truncated = str(target).split(":\\", 1)[-1]

        mock_chat.side_effect = [
            _msg(tool_calls=[_tc("read_file", {"file_path": str(target)})]),
            _msg(tool_calls=[_tc("bash", {"command": "echo finish"})]),
            _msg(content="done"),
        ]
        mock_dispatch.return_value = ToolResult(success=True, output="file contents")
        events = list(
            stream_agent(
                f"read {truncated} then finish",
                cwd=str(tmp_path),
                verify=True,
                max_rounds=5,
            )
        )
        assert "verify" not in [e["type"] for e in events]
        assert events[-1]["type"] == "done"

    @patch("nodus_agent.save_lessons", return_value=True)
    @patch("nodus_agent.load_lessons", return_value=[])
    @patch("nodus_agent._chat")
    def test_stream_reflect_returns_lessons_on_done(self, mock_chat, mock_load, mock_save):
        # Two bash failures then answer → reflection produces a lesson
        mock_chat.side_effect = [
            _msg(tool_calls=[_tc("bash", {"command": "bad"})]),
            _msg(tool_calls=[_tc("bash", {"command": "bad"})]),
            _msg(content="gave up"),
        ]
        with patch("nodus_agent.dispatch_tool",
                   return_value=ToolResult(success=False, output="", error="exit 1")):
            events = list(stream_agent("do X", reflect=True))
        done = events[-1]
        assert done["type"] == "done"
        assert any("bash" in l for l in done["lessons"])

    @patch("nodus_agent.save_lessons", return_value=True)
    @patch("nodus_agent.load_lessons", return_value=[])
    @patch("nodus_agent._chat")
    def test_stream_reflect_lessons_on_max_rounds(self, mock_chat, mock_load, mock_save):
        mock_chat.return_value = _msg(tool_calls=[_tc("bash", {"command": "x"})])
        with patch("nodus_agent.dispatch_tool", return_value=ToolResult(success=True, output="ok")):
            events = list(stream_agent("do X", reflect=True, max_rounds=3))
        done = events[-1]
        assert done["stopped_reason"] == "max_rounds"
        assert any("round" in l.lower() or "complex" in l.lower() for l in done["lessons"])

    @patch("nodus_agent._chat")
    def test_stream_done_includes_lessons_key(self, mock_chat):
        # Even with reflect off, 'lessons' key is present (empty)
        mock_chat.return_value = _msg(content="answer")
        events = list(stream_agent("simple task"))
        assert events[-1]["lessons"] == []

    @patch("nodus_agent._chat")
    def test_stream_continuation_event(self, mock_chat):
        # A narration answer emits a 'continuation' event and the loop continues
        mock_chat.side_effect = [
            _msg(content="Next, I'll write the tests."),  # narration
            _msg(content="Done."),                          # real conclusion
        ]
        events = list(stream_agent("simple task"))
        types = [e["type"] for e in events]
        assert "continuation" in types
        assert events[-1]["type"] == "done"
        assert events[-1]["answer"] == "Done."

    @patch("nodus_agent.add_recipe", return_value=True)
    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_stream_playbook_saves_recipe(self, mock_chat, mock_dispatch, mock_add, tmp_path):
        # A successful run with a tool call should record the path in the playbook
        mock_chat.side_effect = [
            _msg(tool_calls=[_tc("write_file", {"file_path": "x", "content": "y"})]),
            _msg(content="done"),
        ]
        mock_dispatch.return_value = ToolResult(success=True, output="ok")
        list(stream_agent("build a thing", cwd=str(tmp_path), playbook=True))
        mock_add.assert_called_once()
        # the recorded path includes the tool used
        recorded_path = mock_add.call_args[0][2]
        assert "write_file" in recorded_path

    @patch("nodus_agent.save_finding", return_value=True)
    @patch("nodus_agent.load_findings", return_value=[])
    @patch("nodus_agent._chat")
    def test_stream_knowledge_saves_finding(self, mock_chat, mock_load, mock_save, tmp_path):
        mock_chat.return_value = _msg(content="Finding: revalidate each redirect hop")
        list(stream_agent("investigate the ssrf redirect", cwd=str(tmp_path), knowledge=True))
        mock_save.assert_called_once()
        args = mock_save.call_args[0]
        assert any("revalidate" in str(a) for a in args)


# ── run_agent / stream_agent : verification d'EXECUTION (commandes exit 0) ─────

class TestRunAgentExecVerify:
    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_exec_verify_challenges_failed_command(self, mock_chat, mock_dispatch,
                                                   tmp_path, capsys):
        # La tache exige `python check.py` exit 0 ; le fichier n'existe pas ->
        # verify_commands echoue -> challenge EXEC-VERIFY (verify au-dela du fichier).
        seq = [
            _msg(tool_calls=[_tc("bash", {"command": "echo hi"})]),
            _msg(content="done, it exits 0"),
            _msg(content="still"),
            _msg(content="more"),
            _msg(content="final"),
        ]
        mock_chat.side_effect = seq
        mock_dispatch.return_value = ToolResult(success=True, output="ok")
        run_agent("Run python check.py; it must exit 0", cwd=str(tmp_path),
                  verify=True, max_rounds=10, verbose=True)
        out = capsys.readouterr().out
        assert "EXEC-VERIFY" in out

    @patch("nodus_agent.dispatch_tool")
    @patch("nodus_agent._chat")
    def test_stream_exec_verify_event(self, mock_chat, mock_dispatch, tmp_path):
        seq = [_msg(tool_calls=[_tc("bash", {"command": "echo hi"})])] + \
              [_msg(content="done")] * 6
        mock_chat.side_effect = seq
        mock_dispatch.return_value = ToolResult(success=True, output="ok")
        events = list(stream_agent("Run python check.py; it must exit 0",
                                   cwd=str(tmp_path), verify=True, max_rounds=10))
        assert any(e.get("type") == "exec_verify" for e in events)


# ── FAIL-CLOSED gate : stopped_reason == 'verify_failed' ────────────────────

class TestFailClosedGate:
    """When the model never fixes the expected file, the agent must stop with
    stopped_reason='verify_failed' rather than 'done'."""

    @patch("nodus_agent._chat")
    def test_run_agent_verify_failed_when_file_never_created(self, mock_chat, tmp_path):
        # The model always replies "done" but never creates the expected file.
        mock_chat.return_value = _msg(content="done")
        result = run_agent(
            "create foo.txt",
            cwd=str(tmp_path),
            verify=True,
            max_rounds=6,
        )
        assert result.stopped_reason == "verify_failed", (
            f"expected 'verify_failed', got {result.stopped_reason!r}"
        )

    @patch("nodus_agent._chat")
    def test_stream_agent_verify_failed_when_file_never_created(self, mock_chat, tmp_path):
        # stream_agent: model always replies "done" but never creates the expected file.
        mock_chat.return_value = _msg(content="done")
        events = list(stream_agent(
            "create foo.txt",
            cwd=str(tmp_path),
            verify=True,
            max_rounds=6,
        ))
        final = events[-1]
        assert final["stopped_reason"] == "verify_failed", (
            f"expected 'verify_failed', got {final.get('stopped_reason')!r}"
        )
