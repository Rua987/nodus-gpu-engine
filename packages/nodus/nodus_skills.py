#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ TEMPLE IAM - NODUS SKILLS
⚡ Compétences TRANSFÉRÉES : le maître (Claude) méta-code NODUS de l'intérieur
🔥 Savoir curé, autoritaire, présent dès le 1er tour — pas appris après échec

Copyright © 2024 Temple IAM - All Rights Reserved

Idée :
    La réflexion (nodus_reflect) apprend LENTEMENT des échecs observés.
    Les skills, elles, sont du savoir CURÉ par le maître et injecté en autorité
    AVANT que NODUS n'échoue. C'est la transmission directe de compétence :
    "son esprit reçoit le savoir dès le départ".

    Chaque skill = un savoir-faire concret, déclenché par mots-clés, formaté
    en bloc autoritaire ("ALWAYS / NEVER"). Fonctions PURES, données immuables.

    select_skills(task)          → skills pertinentes pour la tâche
    format_skills_for_prompt()   → bloc injectable (autorité)
    list_skills()                → noms disponibles
"""

from typing import List, NamedTuple

# ── Skill ─────────────────────────────────────────────────────────────────────

class Skill(NamedTuple):
    """Une compétence transmise par le maître."""
    name: str            # identifiant court
    triggers: tuple      # mots-clés (minuscules, FR+EN) qui rendent la skill pertinente
    guidance: str        # le savoir-faire concret (impératif: ALWAYS / NEVER)


# ── Bibliothèque curée (écrite par le maître) ─────────────────────────────────
# Chaque guidance distille ce qu'on a appris EMPIRIQUEMENT (tests E2E réels) :
# bash échoue sur Windows, granite hallucine les écritures, etc.

_SKILLS: tuple = (
    Skill(
        name="write_file",
        triggers=(
            "write", "create", "save", "écris", "écrire", "créer", "crée",
            "generate a file", "output to", "store in", ".txt", ".md", ".json",
        ),
        guidance=(
            "To create or write a file: ALWAYS call the write_file tool with "
            "file_path (absolute) and content. NEVER write files via bash "
            "(echo, tee, '>' redirects) — that is unreliable and hallucination-prone. "
            "After writing, you MAY read_file to confirm."
        ),
    ),
    Skill(
        name="read_file",
        triggers=("read", "open", "show", "display", "lis", "lire", "affiche", "contenu"),
        guidance=(
            "To read a file's contents: ALWAYS call read_file with an absolute "
            "file_path. NEVER use bash cat. Use the actual returned content — "
            "do NOT invent or summarize from memory."
        ),
    ),
    Skill(
        name="count",
        triggers=("count", "how many", "number of", "compte", "combien", "nombre de"),
        guidance=(
            "To count occurrences in ONE file: bash grep -c \"PATTERN\" file. "
            "Report the EXACT integer returned by the tool — NEVER guess or "
            "round. If you did not run the count, you do not know it."
        ),
    ),
    Skill(
        name="search",
        triggers=("find", "search", "locate", "where is", "cherche", "trouve", "où est"),
        guidance=(
            "To find files by name: use the glob tool (pattern='**/*.py'). "
            "To search text across files: use the grep tool (pattern, path). "
            "NEVER use bash find / ls -R / grep -r on Windows — they fail."
        ),
    ),
    Skill(
        name="run_tests",
        triggers=("test", "pytest", "run the tests", "coverage", "teste", "tests"),
        guidance=(
            "To run tests: bash python -m pytest PATH -q. Report the EXACT "
            "summary line (e.g. '162 passed'). A '%' in pytest output is the "
            "progress bar, NOT a score — do not confuse them."
        ),
    ),
    Skill(
        name="windows_shell",
        triggers=("bash", "command", "shell", "run", "exécute", "lance", "commande"),
        guidance=(
            "This machine runs PowerShell. WORKS: grep on a single file, "
            "python -m pytest, python -c, git, echo, pwd, date. FAILS: ls, "
            "grep -r, find, wc, tail. For multi-file ops use the glob/grep tools."
        ),
    ),
    Skill(
        name="multi_step",
        triggers=("then", "puis", "ensuite", "step", "étape", "1.", "2.", "first", "after"),
        guidance=(
            "For a multi-step task: do ONE tool call per step, in order. Do NOT "
            "answer until EVERY step has a real tool result. Claiming a step is "
            "done without calling its tool is a lie — the path must be real."
        ),
    ),
)

# Index nom → Skill
_BY_NAME = {s.name: s for s in _SKILLS}


# ── API ───────────────────────────────────────────────────────────────────────

def list_skills() -> List[str]:
    """
    Retourne les noms des skills disponibles, triés.

    Returns:
        Liste triée des noms.

    Example:
        >>> "write_file" in list_skills()
        True
    """
    return sorted(_BY_NAME.keys())


def get_skill(name: str) -> Skill:
    """
    Retourne une skill par nom (insensible à la casse), ou KeyError.

    Args:
        name: Nom de la skill

    Returns:
        La Skill.

    Raises:
        KeyError: si le nom est inconnu.

    Example:
        >>> get_skill("count").name
        'count'
    """
    return _BY_NAME[(name or "").strip().lower()]


def select_skills(task: str) -> List[Skill]:
    """
    Sélectionne les skills pertinentes pour une tâche (match par mots-clés).

    Fonction pure. L'ordre de retour suit l'ordre de la bibliothèque (stable),
    pour un prompt déterministe.

    Args:
        task: Texte de la tâche

    Returns:
        Liste des skills dont au moins un trigger apparaît dans la tâche.
        Vide si la tâche est vide ou ne matche rien.

    Example:
        >>> names = [s.name for s in select_skills("write a file with the count")]
        >>> "write_file" in names and "count" in names
        True
        >>> select_skills("")
        []
    """
    if not task or not task.strip():
        return []
    task_lower = task.lower()
    selected = []
    for skill in _SKILLS:
        if any(trigger in task_lower for trigger in skill.triggers):
            selected.append(skill)
    return selected


def format_skills_for_prompt(skills: List[Skill]) -> str:
    """
    Formate une liste de skills en bloc autoritaire pour le system prompt.

    Fonction pure — chaîne vide si aucune skill.

    Args:
        skills: Skills sélectionnées

    Returns:
        Bloc formaté (vide si skills vide).

    Example:
        >>> format_skills_for_prompt([])
        ''
        >>> "SKILLS" in format_skills_for_prompt(select_skills("write a file"))
        True
    """
    if not skills:
        return ""
    lines = "\n".join(f"- [{s.name}] {s.guidance}" for s in skills)
    return (
        "\n\n## SKILLS (authoritative know-how — follow exactly)\n"
        "These are proven rules. They override your habits:\n"
        f"{lines}\n"
    )
