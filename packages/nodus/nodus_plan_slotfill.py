#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Slot-fill harnais — chainon entre plan NODUS (noms) et args executeur.

NODUS : ["grep", "read_file"]
Qwen  : une etape a la fois, extrait la CIBLE depuis la tache (copie),
        ou null si elle depend d'un resultat precedent.
Harnais : injecte la suggestion enrichie ; l'executeur garde le dernier mot.

Pas de retrain. Zero cloud si model=ollama local.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, List, Optional

from nodus_verify import extract_expected_files  # noqa: E402  (pas de cycle)

# Argument primaire par outil (celui que la "cible" remplit en hint)
PRIMARY_ARG = {
    "bash": "command",
    "read_file": "file_path",
    "write_file": "file_path",
    "edit_file": "file_path",
    "glob": "pattern",
    "grep": "pattern",
    "web_fetch": "url",
    "brave_search": "query",
    "gcs_upload": "local_path",
}

_SLOT_PROMPT = """\
You extract ONE primary argument for a coding-agent tool.
Reply with ONLY a JSON object (no markdown, no prose):
  {{"target": "<exact string copied from the task>"}}
or
  {{"target": null}}
when the value is NOT written as a literal in the task and must come from a previous tool result.

Rules:
- Copy a literal from the task when clearly present (path, pattern, command, URL, query).
- Do NOT invent paths, filenames, or values absent from the task.
- If the task says "the file it finds / that defines it / the matching file / that page" → target MUST be null.
- If a previous step was a search/list/run and this step needs its result → null.
- Do not fill other arguments (content, old_string, etc.) — only the primary one.

Tool: {tool}
The primary argument you fill is `{arg_name}` (human-readable field name).
The JSON key of your answer is ALWAYS "target" — never `{arg_name}`, never any other name.
Step: {step}/{n_steps}
Previous steps: {previous}
Task: {task}
"""

_PRODUCERS = {"glob", "grep", "bash", "brave_search", "web_fetch"}
# Producteurs de CHEMIN (pour carry-the-path) : un read/glob/write fournit la
# cible du edit/write suivant. Distinct de _PRODUCERS (anaphore "that file").
_CARRY_PRODUCERS = ("read_file", "glob", "write_file")
_ANAPHORA = re.compile(
    r"\b(that file|the file it|the file that|the matching file|"
    r"that page|the page you|first result|the file containing)\b",
    re.I,
)


def _looks_like_path_or_url(tg: str, tool: str) -> bool:
    t = tg.strip()
    if tool == "web_fetch":
        return t.startswith("http://") or t.startswith("https://")
    if tool in ("read_file", "edit_file", "write_file"):
        if "/" in t or "\\" in t:
            return True
        # fichier simple type README.md / config.yaml
        return bool(re.search(r"\.\w{1,8}$", t)) and " " not in t
    return True


def _last_carried_path(previous: List[tuple]) -> Optional[str]:
    """Dernier chemin produit par une etape precedente (read/glob/write)."""
    for _tool, _tg in reversed(previous):
        if _tg and _tool in _CARRY_PRODUCERS:
            return _tg
    return None


def _sanitize_target(
    tool: str,
    tg: Optional[str],
    task: str,
    previous: List[tuple],
) -> Optional[str]:
    """Garde-fou deterministe : refuse les fausses cibles anaphoriques / non-chemins."""
    if tg is None:
        return None
    # read/write/edit : une cible qui ne ressemble pas a un chemin est du bruit
    # (ex. litteral "done" attrape dans "exactly done")
    if tool in ("read_file", "write_file", "edit_file") and not _looks_like_path_or_url(tg, tool):
        return None
    prev_tool = previous[-1][0] if previous else None
    if (
        tool in ("read_file", "edit_file", "web_fetch")
        and prev_tool in _PRODUCERS
        and (_ANAPHORA.search(task) or not _looks_like_path_or_url(tg, tool))
    ):
        return None
    # Cible inventee : edit/write vers un basename qui ne matche NI un fichier
    # attendu par la tache NI le chemin porte d'une etape precedente → bruit.
    if tool in ("edit_file", "write_file"):
        expected_bases = {Path(e).name.lower() for e in extract_expected_files(task)}
        carried = _last_carried_path(previous)
        known = set(expected_bases)
        if carried is not None:
            known.add(Path(carried).name.lower())
        if known and Path(tg).name.lower() not in known:
            return None
    return tg


def build_slotfill_prompt(
    task: str,
    tool: str,
    step: int,
    n_steps: int,
    previous: List[tuple],
) -> str:
    """previous = liste de (tool_name, target_or_None)."""
    if previous:
        prev_txt = "; ".join(
            f"{i+1}. {t} target={json.dumps(tg, ensure_ascii=False)}"
            for i, (t, tg) in enumerate(previous)
        )
    else:
        prev_txt = "(none)"
    return _SLOT_PROMPT.format(
        tool=tool,
        arg_name=PRIMARY_ARG.get(tool, "argument"),
        step=step,
        n_steps=n_steps,
        previous=prev_txt,
        task=task.strip(),
    )


def parse_slotfill(text: str) -> Optional[str]:
    """
    -> str (cible) | None (depend du precedent / invalide / absent).

    None = "pas de cible pre-remplie" : le harnais le dira clairement
    a l'executeur (utiliser le resultat precedent).
    """
    if not text or not text.strip():
        return None
    t = text.strip()
    # retire fences markdown eventuels
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    try:
        start, end = t.find("{"), t.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(t[start:end])
            if isinstance(data, dict) and "target" in data:
                tg = data["target"]
                if tg is None:
                    return None
                if isinstance(tg, str):
                    s = tg.strip()
                    if not s or s.lower() in ("null", "none", "n/a"):
                        return None
                    return s
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def fill_plan_targets(
    task: str,
    tool_names: List[str],
    chat_fn: Callable,
    model: str,
    *,
    verbose: bool = False,
    think: Optional[bool] = False,
) -> List[Optional[str]]:
    """
    Remplit les cibles une etape a la fois via chat_fn(messages, model=...).

    chat_fn doit renvoyer un dict style Ollama message ({"content": ...}).
    think=False (defaut) : desactive le raisonnement interne qwen3.5 — sinon
    content reste vide et num_predict est mange par le thinking.
    En cas d'erreur reseau/parse : target=None pour cette etape (pas de crash).
    """
    targets: List[Optional[str]] = []
    previous: List[tuple] = []
    n = len(tool_names)

    def _call(messages):
        # think est opt-in cote _chat ; mocks sans kwarg → fallback
        try:
            return chat_fn(messages, model=model, think=think)
        except TypeError:
            return chat_fn(messages, model=model)

    for i, tool in enumerate(tool_names, start=1):
        prompt = build_slotfill_prompt(task, tool, i, n, previous)
        try:
            msg = _call([{"role": "user", "content": prompt}])
            raw = (msg or {}).get("content", "") if isinstance(msg, dict) else ""
            tg = _sanitize_target(tool, parse_slotfill(raw), task, previous)
        except Exception as e:
            if verbose:
                print(f"[slotfill] step {i}/{n} {tool} failed: {e}")
            tg = None
        if verbose:
            print(f"[slotfill] {i}/{n} {tool} -> {tg!r}")
        targets.append(tg)
        previous.append((tool, tg))
    return targets


def format_plan_with_targets(
    names: List[str],
    targets: Optional[List[Optional[str]]] = None,
) -> str:
    """
    Bloc system prompt enrichi. Suggestion (pas ordre).
    targets[i] = str | None ; longueur alignee sur names (sinon ignore).
    """
    if not names:
        return ""
    tgts = targets if targets is not None and len(targets) == len(names) else [None] * len(names)
    lines = []
    for i, (name, tg) in enumerate(zip(names, tgts), start=1):
        arg = PRIMARY_ARG.get(name, "argument")
        if tg:
            lines.append(
                f"{i}. Call tool `{name}` — set `{arg}` to exactly: {tg!r} "
                f"(copied from the task; verify before use)"
            )
        else:
            lines.append(
                f"{i}. Call tool `{name}` — `{arg}` comes from a previous tool "
                f"result or is not literal in the task; YOU must resolve it"
            )
    numbered = "\n".join(lines)
    return (
        "\n\n## SUGGESTED TOOL SEQUENCE (local NODUS + slot-fill)\n"
        "This is a SUGGESTION. Verify each step fits the task. "
        "You MAY skip, reorder, or replace tools. "
        "When a target is given, prefer that exact value for the primary argument; "
        "still fill any other required arguments yourself.\n"
        f"{numbered}\n"
    )
