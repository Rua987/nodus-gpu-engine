#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NODUS Vibe — session terminal type Claude Code.

Boucle interactive multi-tours sur le VRAI harness (nodus_agent + gates Fable):
  - stream_agent : outils visibles en direct (round / result / verify)
  - GLM 5.2 cloud par defaut, --verify, --text-tools si OpenRouter
  - memoire session (.nodus_memory.md), cwd = repertoire courant

Usage:
    python nodus_vibe.py
    python nodus_vibe.py --cwd C:\\Users\\admin\\nodus_sandbox
    python nodus_vibe.py -m openrouter/openai/gpt-oss-120b:free

PowerShell (profil) :
    function nodus-vibe { python ...\\nodus_vibe.py --cwd "$PWD" @args }
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, Optional

_HERE = Path(__file__).parent.resolve()
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from nodus_agent import OPENROUTER_CLOUD_MODEL, stream_agent  # noqa: E402
from nodus_chat import EXIT_COMMANDS, handle_command, parse_input  # noqa: E402
from nodus_memory import resolve_memory_path  # noqa: E402

PROMPT = "nodus> "

BANNER = """\
NODUS Vibe — coding agent (Claude Code style)
  cwd     = working tree for tools
  model   = cloud GLM by default
  /help   = commands   /exit = quit

Type a task; watch tools run live, then get the answer.
"""


def _needs_text_tools(model: str) -> bool:
    return model.startswith("openrouter/")


def _summarize_args(tool: str, args: dict) -> str:
    if not args:
        return ""
    if tool == "bash":
        cmd = args.get("command") or args.get("cmd") or ""
        return cmd[:120] + ("..." if len(cmd) > 120 else "")
    if tool in ("read_file", "write_file", "edit_file"):
        return str(args.get("file_path") or args.get("path") or "")[:100]
    if tool == "grep":
        return f"{args.get('pattern', '')!r} in {args.get('path', '')!r}"[:100]
    if tool == "glob":
        return str(args.get("pattern", ""))[:80]
    try:
        s = json.dumps(args, ensure_ascii=False)
    except TypeError:
        s = str(args)
    return s[:120] + ("..." if len(s) > 120 else "")


def format_tool_start(round_num: int, tool: str, args: dict) -> str:
    detail = _summarize_args(tool, args or {})
    if detail:
        return f"[{round_num}] -> {tool}  {detail}"
    return f"[{round_num}] -> {tool}"


def format_tool_result(round_num: int, tool: str, success: bool, output: str) -> str:
    mark = "OK" if success else "FAIL"
    text = (output or "").strip().replace("\n", " ")
    if len(text) > 160:
        text = text[:157] + "..."
    return f"    [{mark}] {text}" if text else f"    [{mark}]"


def format_done(answer: str, tool_calls: int, rounds: int, stopped: str) -> str:
    sep = "=" * 60
    return f"\n{sep}\n{answer.strip()}\n{sep}\n({tool_calls} tools · {rounds} rounds · {stopped})\n"


def run_task_streaming(
    task: str,
    *,
    cwd: str,
    model: str,
    verify: bool,
    memory: bool,
    text_tools: bool,
    profile: Optional[str],
    output_fn: Callable[[str], None],
) -> Optional[dict]:
    """Execute one task via stream_agent; print events. Returns final 'done' event."""
    done_ev: Optional[dict] = None
    for ev in stream_agent(
        task=task,
        cwd=cwd,
        model=model,
        memory=memory,
        verify=verify,
        text_tools=text_tools,
        profile=profile,
        reflect=True,
    ):
        t = ev.get("type")
        if t == "round":
            output_fn(format_tool_start(ev.get("round", 0), ev.get("tool", "?"), ev.get("args") or {}))
        elif t == "result":
            output_fn(format_tool_result(
                ev.get("round", 0),
                ev.get("tool", "?"),
                bool(ev.get("success")),
                ev.get("output") or "",
            ))
        elif t == "verify":
            missing = ev.get("missing") or []
            output_fn(f"    [VERIFY] missing: {missing}")
        elif t == "challenge":
            output_fn(f"    [CHALLENGE] steps {ev.get('steps_done')}/{ev.get('steps_required')}")
        elif t == "force_write":
            output_fn(f"    [FORCE-WRITE] relance #{ev.get('count')}")
        elif t == "error":
            output_fn(f"ERROR: {ev.get('error')}")
            return ev
        elif t == "done":
            done_ev = ev
            output_fn(format_done(
                ev.get("answer") or "",
                int(ev.get("tool_calls") or 0),
                int(ev.get("rounds") or 0),
                str(ev.get("stopped_reason") or "done"),
            ))
            lessons = ev.get("lessons") or []
            for lesson in lessons:
                output_fn(f"  lesson: {lesson}")
    return done_ev


def vibe_help_extra() -> str:
    return (
        "\nVibe-specific:\n"
        "  /status          cwd + model + flags\n"
        "  /model <slug>     change model (openrouter/...)\n"
        "  /verify on|off    toggle file verify\n"
        "  Any other line    task for the agent (tools stream live)\n"
    )


def handle_vibe_command(
    command: str,
    state: dict,
    memory_path: Path,
    output_fn: Callable[[str], None],
) -> bool:
    """Returns False to exit session."""
    if command.startswith("/model"):
        parts = command.split(maxsplit=1)
        if len(parts) < 2:
            output_fn(f"model = {state['model']}")
            return True
        state["model"] = parts[1].strip()
        state["text_tools"] = _needs_text_tools(state["model"])
        output_fn(f"model -> {state['model']}")
        return True

    if command.startswith("/verify"):
        parts = command.split(maxsplit=1)
        if len(parts) < 2:
            output_fn(f"verify = {state['verify']}")
            return True
        val = parts[1].strip().lower()
        state["verify"] = val in ("on", "true", "1", "yes")
        output_fn(f"verify -> {state['verify']}")
        return True

    if command == "/status":
        output_fn(
            f"cwd={state['cwd']}\n"
            f"model={state['model']}\n"
            f"verify={state['verify']}  text_tools={state['text_tools']}  memory={state['memory']}\n"
            f"memory_file={memory_path}"
        )
        return True

    if command == "/help":
        from nodus_chat import help_text
        output_fn(help_text() + vibe_help_extra())
        return True

    return handle_command(command, memory_path, output_fn)


def vibe_loop(
    cwd: str,
    model: str = OPENROUTER_CLOUD_MODEL,
    verify: bool = True,
    memory: bool = True,
    profile: Optional[str] = None,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> int:
    state = {
        "cwd": cwd,
        "model": model,
        "verify": verify,
        "memory": memory,
        "text_tools": _needs_text_tools(model),
    }
    memory_path = resolve_memory_path(cwd)
    output_fn(BANNER)
    output_fn(f"cwd: {cwd}\nmodel: {model}\n")

    while True:
        try:
            line = input_fn(PROMPT)
        except (EOFError, KeyboardInterrupt):
            output_fn("\nBye.")
            return 0

        kind, payload = parse_input(line)
        if kind == "empty":
            continue
        if kind == "command":
            if not handle_vibe_command(payload, state, memory_path, output_fn):
                return 0
            continue

        output_fn("")  # blank line before tool stream
        run_task_streaming(
            payload,
            cwd=state["cwd"],
            model=state["model"],
            verify=state["verify"],
            memory=state["memory"],
            text_tools=state["text_tools"],
            profile=profile,
            output_fn=output_fn,
        )


def main() -> int:
    parser = argparse.ArgumentParser(prog="nodus_vibe", description="NODUS interactive vibe coding session")
    parser.add_argument("--cwd", "-C", default=None, help="Working directory for tools")
    parser.add_argument("--model", "-m", default=OPENROUTER_CLOUD_MODEL, help="Model slug")
    parser.add_argument("--no-verify", action="store_true", help="Disable --verify")
    parser.add_argument("--no-memory", action="store_true", help="Disable session memory")
    parser.add_argument("--profile", "-P", default=None, help="Agent profile (code/research/...)")
    args = parser.parse_args()
    return vibe_loop(
        cwd=args.cwd or str(Path.cwd()),
        model=args.model,
        verify=not args.no_verify,
        memory=not args.no_memory,
        profile=args.profile,
    )


if __name__ == "__main__":
    raise SystemExit(main())
