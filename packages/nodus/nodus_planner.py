#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ TEMPLE IAM - NODUS PLANNER
⚡ Couche de planification : un plan explicite avant l'exécution
🔥 Tâche complexe → plan N étapes → exécution guidée

Copyright © 2024 Temple IAM - All Rights Reserved

Architecture:
    Fonctions PURES uniquement (pas d'appel LLM ici) pour rester
    100% testables. C'est run_agent() qui orchestre l'appel au modèle.

    needs_planning(task)          → faut-il planifier ? (heuristique)
    build_plan_prompt(task)       → prompt demandant un plan au LLM
    parse_plan(text)              → extrait la liste d'étapes du texte
    format_plan_for_prompt(steps) → bloc injectable dans le system prompt
"""

import re
from typing import List

# ── Constantes ────────────────────────────────────────────────────────────────
# Une tâche est "complexe" si elle dépasse ce nombre de mots,
# ou contient des connecteurs séquentiels, ou est déjà numérotée.
PLANNING_WORD_THRESHOLD = 12
_SEQ_CONNECTORS = (
    " puis ", " ensuite ", " then ", " after that ", " and then ",
    " enfin ", " finally ", " d'abord ", " first ", " étape ", " step ",
)
# Connecteurs qui separent des etapes (pour compter N) — sans "first"/"d'abord"
# qui ouvrent plutot qu'ils separent.
_STEP_SEPARATORS = (
    " puis ", " ensuite ", " then ", " after that ", " and then ",
    " finally ", " enfin ", ", then ", "; then ", ". then ",
)
_NUMBERED_RE = re.compile(
    r'(?:^|\n)\s*[1-9]\d*\s*[.):\-]\s+\S',
    re.MULTILINE,
)
# Lignes de plan : "1. ...", "- ...", "* ...", "Step 1: ..."
_PLAN_LINE_RE = re.compile(
    r'^\s*(?:[1-9]\d*\s*[.):\-]|[-*•]|step\s+[1-9]\d*\s*[:.\-])\s*(.+)$',
    re.IGNORECASE,
)
MAX_PLAN_STEPS = 12


# ── Détection ─────────────────────────────────────────────────────────────────

def estimate_task_steps(task: str) -> int:
    """
    Estime le nombre d'etapes via connecteurs sequentiels (then/puis/…).

    Fonction pure. "A then B then C" → 3. Tache sans connecteur → 1.
    Plafond MAX_PLAN_STEPS. Ne remplace pas le comptage numerote
    (_count_task_steps cote agent) : on prend le max des deux.

    Example:
        >>> estimate_task_steps("read X then edit Y then write Z")
        3
        >>> estimate_task_steps("list files")
        1
    """
    if not task or not task.strip():
        return 1
    # Normalise : remplace les separateurs (plus longs d'abord) par un marqueur
    # unique pour eviter le double-comptage (", then " vs " then ").
    text = f" {task.lower()} "
    seps = sorted(_STEP_SEPARATORS, key=len, reverse=True)
    for sep in seps:
        text = text.replace(sep, " || ")
    n_sep = text.count(" || ")
    return min(max(n_sep + 1, 1), MAX_PLAN_STEPS)


def needs_planning(task: str) -> bool:
    """
    Détermine si une tâche mérite une phase de planification.

    Heuristique (fonction pure) — vrai si AU MOINS une condition :
        - la tâche contient un connecteur séquentiel (puis, then, ensuite…)
        - la tâche est déjà numérotée (1. … 2. …)
        - la tâche dépasse PLANNING_WORD_THRESHOLD mots

    Args:
        task: Texte de la tâche

    Returns:
        True si planification recommandée.

    Example:
        >>> needs_planning("liste les fichiers")
        False
        >>> needs_planning("lis le fichier puis compte les lignes")
        True
    """
    if not task or not task.strip():
        return False

    lowered = f" {task.lower()} "
    if any(c in lowered for c in _SEQ_CONNECTORS):
        return True

    if _NUMBERED_RE.search(task):
        return True

    word_count = len(task.split())
    return word_count > PLANNING_WORD_THRESHOLD


# ── Construction du prompt de plan ────────────────────────────────────────────

def build_plan_prompt(task: str) -> str:
    """
    Construit le prompt qui demande un plan au modèle.

    Fonction pure.

    Args:
        task: La tâche à planifier

    Returns:
        Prompt à envoyer au LLM (rôle user).

    Example:
        >>> "PLAN" in build_plan_prompt("do X").upper()
        True
    """
    return (
        "Break the following task into a short ordered PLAN of concrete steps.\n"
        "Rules:\n"
        "- One step per line, numbered: 1. 2. 3. ...\n"
        "- Each step = ONE tool action (bash, read_file, write_file, grep, glob).\n"
        "- Be concrete: name files, commands. No explanations, no prose.\n"
        "- Maximum 10 steps.\n\n"
        f"TASK:\n{task.strip()}\n\n"
        "PLAN:"
    )


# ── Parsing du plan ───────────────────────────────────────────────────────────

def parse_plan(text: str, max_steps: int = MAX_PLAN_STEPS) -> List[str]:
    """
    Extrait la liste d'étapes d'un texte de plan généré par le LLM.

    Reconnaît les lignes numérotées (1. 2.), à puces (- * •) ou "Step N:".
    Fonction pure.

    Args:
        text:      Texte brut du plan
        max_steps: Nombre max d'étapes conservées

    Returns:
        Liste des étapes (texte nettoyé), vide si rien trouvé.

    Example:
        >>> parse_plan("1. read file\\n2. count lines")
        ['read file', 'count lines']
        >>> parse_plan("no steps here")
        []
    """
    if not text or not text.strip():
        return []

    steps: List[str] = []
    for line in text.splitlines():
        match = _PLAN_LINE_RE.match(line)
        if match:
            step = match.group(1).strip()
            if step:
                steps.append(step)
        if len(steps) >= max_steps:
            break

    return steps


def format_plan_for_prompt(steps: List[str]) -> str:
    """
    Formate une liste d'étapes en bloc injectable dans le system prompt.

    Fonction pure — chaîne vide si aucune étape.

    Args:
        steps: Liste des étapes du plan

    Returns:
        Bloc formaté (vide si steps vide).

    Example:
        >>> format_plan_for_prompt([])
        ''
        >>> "PLAN" in format_plan_for_prompt(["a", "b"])
        True
    """
    if not steps:
        return ""

    numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(steps, start=1))
    return (
        "\n\n## EXECUTION PLAN (follow it step by step)\n"
        "Execute these steps IN ORDER, one tool call per step. "
        "Do NOT answer until every step is done:\n"
        f"{numbered}\n"
    )
