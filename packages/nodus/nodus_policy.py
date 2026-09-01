#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ TEMPLE IAM - NODUS POLICY
⚡ Régime de comportement ADAPTÉ AU BACKEND : local lâche, cloud serré
🔥 Le faible boucle par besoin (gratuit, on tolère) ; le fort boucle par
   évitement de décision (payant, on l'INTERDIT)

Copyright © 2024 Temple IAM - All Rights Reserved

Idée (analogie cerveau/main de l'utilisateur, poussée à sa conclusion) :
    Un modèle LOCAL (Ollama) est faible : il relit parce qu'il perd le fil,
    hallucine, oublie. La boucle est longue par NÉCESSITÉ — et comme c'est
    gratuit, on la tolère. Un modèle CLOUD (Opus & co) a compris dès le 2e
    round : sa re-lecture n'est pas un besoin mais un ÉVITEMENT de la décision
    — et chaque token coûte. Paradoxe : le modèle le PLUS fort gaspille le PLUS
    sans discipline. Donc le sas de transition est PLUS nécessaire au cloud.

    policy_for(model)            → BackendPolicy (local vs cloud)
    transition_gate_prompt()     → bloc système injecté en régime cloud
    should_force_write(...)      → faut-il forcer la 1re écriture ?
    force_write_message()        → relance injectée pour stopper la lecture
"""

import re
from typing import List, NamedTuple, Optional

from nodus_backends import detect_backend

# ── Outils classés lecture / écriture ─────────────────────────────────────────
READ_TOOLS  = frozenset({"read_file", "glob", "grep"})
# gcs_upload : outil de LIVRAISON (déposer l'artefact produit sur Cloud Storage)
# — il "écrit" dans l'univers du harnais, donc compté comme action/écriture.
WRITE_TOOLS = frozenset({"write_file", "edit_file", "gcs_upload"})
# Outils d'analyse sans livraison : comptent dans le read_budget cloud.
# bash inclus : les modèles sondent via python -c au lieu d'écrire (observé JSON phase 2).
ANALYSIS_TOOLS = READ_TOOLS | frozenset({"bash"})
# Outils qui peuvent MUTER le système de fichiers (write/edit + bash + upload).
# Sert au détecteur anti-thrash : un round "actif" est un round qui a appelé
# l'un d'eux. (bash inclus car un modèle peut écrire/éditer/dumper via shell,
# hors WRITE_TOOLS.)
MUTATING_TOOLS = WRITE_TOOLS | frozenset({"bash"})

# Plafond de relances "force l'écriture" par tâche (anti-spam).
MAX_FORCE_WRITES = 3

# Plafond de relances "recentrage anti-thrash" par tâche (anti-spam).
MAX_REFOCUS = 3

# Plafond de relances "grep multi-hits → choisis le fichier DEFINISSANT".
MAX_MULTI_HIT = 2

# Ligne content-mode de tool_grep : "rel/path.py:12: code…"
_GREP_CONTENT_HIT = re.compile(r"^(?P<path>.+?):(?P<lineno>\d+):\s")


# ── Politique de backend ──────────────────────────────────────────────────────

class BackendPolicy(NamedTuple):
    """
    Régime de comportement selon le backend.

    Attributes:
        label:        "local" ou "cloud"
        read_budget:  nombre de lectures consécutives SANS écriture tolérées
                      avant de forcer une écriture. 0 = désactivé (local).
        gate:         injecter le sas de transition dans le system prompt ?
        rec_max_rounds: plafond de rounds RECOMMANDÉ (indicatif pour l'appelant).
        thrash_budget: nombre d'écritures HORS CIBLE (pas un artefact attendu)
                      tolérées tant que les attendus manquent, avant de recentrer.
                      0 = désactivé.
    """
    label: str
    read_budget: int
    gate: bool
    rec_max_rounds: int
    thrash_budget: int


# Cloud : serré. Le modèle est capable → il n'a pas besoin de relire ; on coupe
# la boucle tôt (budget de lecture) et on injecte le sas « décide vite, écris ».
# Le thrash (écrire du bruit sans livrer) coûte des tokens → recentrage tôt.
CLOUD_POLICY = BackendPolicy(label="cloud", read_budget=2, gate=True,
                             rec_max_rounds=30, thrash_budget=3)

# Local : lâche. Le modèle est faible → relire est légitime ; gratuit → on tolère.
# Mais la NON-LIVRAISON reste un échec, indépendamment du coût : thrash actif,
# plus permissif (les écritures intermédiaires d'un faible sont plus fréquentes).
LOCAL_POLICY = BackendPolicy(label="local", read_budget=0, gate=False,
                             rec_max_rounds=35, thrash_budget=5)


# Profils LOURDS EN LECTURE : auditer/rechercher = lire BEAUCOUP avant d'écrire.
# Leur budget de lecture est relâché pour ne pas couper une collecte légitime
# (sinon la garde anti-paralysie tue un audit multi-fichiers, cf. usage réel).
READ_HEAVY_PROFILES = frozenset({"security", "research"})
READ_HEAVY_BUDGET = 12


def policy_for(model: str, profile: Optional[str] = None) -> BackendPolicy:
    """
    Retourne la politique de comportement pour un modèle (et son profil).

    Cloud (backend API : anthropic/deepseek/openrouter) → régime serré.
    Local (Ollama) → régime lâche. Profil LOURD EN LECTURE (security/research)
    → budget de lecture relâché (lire avant d'écrire est légitime). Fonction pure.

    Args:
        model:   Identifiant du modèle (ex: "openrouter/anthropic/claude-opus-4.8"
                 ou "qwen3.5:2b").
        profile: Profil résolu (security/research/code/...) ou None.

    Returns:
        BackendPolicy adaptée.

    Example:
        >>> policy_for("qwen3.5:2b").label
        'local'
        >>> policy_for("openrouter/anthropic/claude-opus-4.8").label
        'cloud'
        >>> policy_for("openrouter/x", "security").read_budget
        12
        >>> policy_for("openrouter/x", "code").read_budget
        2
    """
    base = LOCAL_POLICY if detect_backend(model) == "ollama" else CLOUD_POLICY
    # Profil read-heavy + budget actif (cloud) → on relâche le budget de lecture.
    if (profile or "").lower() in READ_HEAVY_PROFILES and base.read_budget > 0:
        return base._replace(read_budget=READ_HEAVY_BUDGET)
    return base


def relax_read_budget(policy: BackendPolicy) -> BackendPolicy:
    """
    Relâche le budget de lecture pour une tâche ITÉRATIVE (média OU code).

    Pourquoi : `bash` compte comme une lecture (ANALYSIS_TOOLS), mais dans les
    workflows itératifs il est l'outil d'ACTION/debug — piloter Blender/ffmpeg,
    ou lancer/relancer un programme et ses tests pour les corriger. Le régime
    cloud serré (budget 2 + force-write + read-paralysis) étrangle alors un
    travail légitime AVANT livraison (mesuré : run média ET run de code coupés
    en pleine progression). On traite ces tâches comme read-heavy, comme les
    profils security/research.

    Idempotent. Ne touche pas le régime local (budget 0). Fonction pure.

    Example:
        >>> relax_read_budget(CLOUD_POLICY).read_budget
        12
        >>> relax_read_budget(LOCAL_POLICY).read_budget
        0
    """
    if policy.read_budget > 0:
        return policy._replace(read_budget=max(policy.read_budget, READ_HEAVY_BUDGET))
    return policy


def transition_gate_prompt() -> str:
    """
    Bloc système injecté en régime CLOUD : décide vite, agis, ne relis pas.

    Fonction pure.

    Returns:
        Texte du sas de transition.

    Example:
        >>> "DECIDE FAST" in transition_gate_prompt()
        True
    """
    return (
        "\n\n## DECIDE FAST, THEN ACT (cloud-budget discipline)\n"
        "You run on a strong model — you do NOT need to re-read files you have "
        "already read; you understood them the first time. After a brief look, "
        "COMMIT: create or edit a file. A first imperfect change beats endless "
        "analysis. NEVER read the same file twice. If you catch yourself gathering "
        "more context instead of acting, STOP and make your edit now."
    )


def should_force_write(
    reads_since_write: int,
    policy: BackendPolicy,
    force_sent: int,
) -> bool:
    """
    Décide s'il faut forcer la première écriture (anti-paralysie cloud).

    Vrai si : le budget de lecture est actif (cloud), le nombre de lectures
    consécutives sans écriture atteint le budget, et on n'a pas épuisé le
    plafond de relances. Fonction pure.

    Args:
        reads_since_write: lectures consécutives depuis la dernière écriture
        policy:            politique du backend
        force_sent:        relances "force écriture" déjà injectées

    Returns:
        True s'il faut injecter une relance d'écriture.

    Example:
        >>> should_force_write(4, CLOUD_POLICY, 0)
        True
        >>> should_force_write(4, LOCAL_POLICY, 0)
        False
        >>> should_force_write(1, CLOUD_POLICY, 0)
        False
    """
    return (
        policy.read_budget > 0
        and reads_since_write >= policy.read_budget
        and force_sent < MAX_FORCE_WRITES
    )


def duplicate_read_message(path: str) -> str:
    """
    Erreur injectée quand read_file retente un fichier déjà lu (cloud).

    Fonction pure.
    """
    return (
        f"Blocked: you already read {path}. Do NOT read it again — you have the "
        f"content in this session. Use edit_file or write_file NOW to deliver."
    )


def should_stop_read_paralysis(
    reads_since_write: int,
    policy: BackendPolicy,
    force_sent: int,
) -> bool:
    """
    Arrêt dur : budget FORCE-WRITE épuisé et l'agent relit encore sans écrire.

    Fonction pure.
    """
    return (
        policy.gate
        and force_sent >= MAX_FORCE_WRITES
        and reads_since_write >= policy.read_budget
    )


def read_paralysis_message() -> str:
    """Message de fin quand l'agent reste bloqué en lecture après 3 FORCE-WRITE."""
    return (
        "READ PARALYSIS: you exhausted the read budget and all force-write relances "
        "without delivering. Stop reading — write or edit the deliverable, or admit "
        "the blocker."
    )


def force_write_message() -> str:
    """
    Relance injectée pour stopper la lecture en boucle et forcer l'action.

    Fonction pure.

    Returns:
        Message utilisateur de forçage.

    Example:
        >>> "Stop reading" in force_write_message()
        True
    """
    return (
        "Stop reading and probing. You have gathered enough context — make your FIRST "
        "concrete change NOW: call write_file or edit_file this round. You can refine "
        "it afterwards. Do not read more files or run more bash probes before you "
        "have written one."
    )


def should_refocus(
    stalled_rounds: int,
    missing_expected,
    refocus_sent: int,
    policy: BackendPolicy,
) -> bool:
    """
    Décide s'il faut recentrer l'agent (anti-thrash, signal OUTCOME).

    Le critère est le RÉSULTAT, pas le symptôme : un "round bloqué" est un round
    ACTIF (write/edit/bash, cf. MUTATING_TOOLS) qui n'a PAS réduit l'ensemble des
    attendus manquants. Inviolable — peu importe comment l'agent gaspille (bruit
    write, dump bash, édition in-place, fichier transitoire), s'il n'a rien livré
    le round compte. Vrai si : des attendus manquent encore, le thrash est actif
    pour ce backend, les rounds bloqués atteignent le budget, et on n'a pas épuisé
    le plafond de recentrage. Fonction pure.

    (Issu de 3 runs live : pourchasser le symptôme — écriture hors cible, création
    de fichier hors cible — était une course aux armements ; V4-pro évadait par
    édition in-place via bash. Le seul signal robuste est l'ABSENCE DE PROGRÈS.)

    Args:
        stalled_rounds:   rounds actifs consécutifs sans livrer d'attendu manquant
        missing_expected: artefacts attendus encore absents
        refocus_sent:     recentrages déjà injectés
        policy:           politique du backend

    Returns:
        True s'il faut injecter un message de recentrage.

    Example:
        >>> should_refocus(3, ["doc.md"], 0, CLOUD_POLICY)
        True
        >>> should_refocus(3, [], 0, CLOUD_POLICY)
        False
        >>> should_refocus(2, ["doc.md"], 0, CLOUD_POLICY)
        False
    """
    return (
        bool(missing_expected)
        and policy.thrash_budget > 0
        and stalled_rounds >= policy.thrash_budget
        and refocus_sent < MAX_REFOCUS
    )


def refocus_message(missing_expected) -> str:
    """
    Relance injectée pour stopper le thrash et forcer la livraison attendue.

    Fonction pure.

    Args:
        missing_expected: artefacts attendus encore absents (noms).

    Returns:
        Message utilisateur de recentrage, nommant les artefacts manquants.

    Example:
        >>> "doc.md" in refocus_message(["doc.md"])
        True
        >>> "noise" in refocus_message(["doc.md"]).lower()
        True
    """
    files = ", ".join(str(f) for f in missing_expected)
    return (
        "You are writing noise — files that are NOT the requested deliverable. "
        f"The task still requires these MISSING artifact(s): {files}. Stop "
        "creating other files or scratch copies; create EXACTLY the expected "
        "artifact(s), with their exact names, THIS round."
    )


def extract_grep_hit_files(output: str) -> List[str]:
    """
    Extraire les chemins uniques d'une sortie tool_grep (ordre conserve).

    Accepte files_with_matches (un chemin par ligne) et content
    (`path:lineno: …`). Ignore `(no matches)` et les lignes vides.
    Fonction pure.

    Example:
        >>> extract_grep_hit_files("a.py\\nb.py\\na.py")
        ['a.py', 'b.py']
        >>> extract_grep_hit_files("a.py:3: def f():\\nb.py:1: import a")
        ['a.py', 'b.py']
        >>> extract_grep_hit_files("(no matches)")
        []
    """
    if not output or not output.strip() or output.strip() == "(no matches)":
        return []
    found: List[str] = []
    seen: set[str] = set()
    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _GREP_CONTENT_HIT.match(line)
        path = m.group("path") if m else line
        key = path.replace("\\", "/").lower()
        if key in seen:
            continue
        seen.add(key)
        found.append(path)
    return found


def should_multi_hit_challenge(hit_files: List[str], multi_hit_sent: int) -> bool:
    """
    Vrai si grep a touche >=2 fichiers et le plafond n'est pas epuise.

    Fonction pure.

    Example:
        >>> should_multi_hit_challenge(["a.py", "b.py"], 0)
        True
        >>> should_multi_hit_challenge(["a.py"], 0)
        False
        >>> should_multi_hit_challenge(["a.py", "b.py"], MAX_MULTI_HIT)
        False
    """
    return len(hit_files) >= 2 and multi_hit_sent < MAX_MULTI_HIT


def multi_hit_grep_challenge(pattern: str, files: List[str]) -> str:
    """
    Relance apres un grep ambigu : forcer read_file sur le fichier DEFINISSANT.

    Fonction pure. Ne choisit PAS le fichier a la place du modele — exige
    le critere (def/class), pas le premier hit alphabetique.

    Example:
        >>> msg = multi_hit_grep_challenge("foo", ["a.py", "b.py"])
        >>> "MULTI-HIT" in msg and "read_file" in msg and "a.py" in msg
        True
    """
    listed = "\n".join(f"  {i}. {f}" for i, f in enumerate(files, 1))
    return (
        f"MULTI-HIT SEARCH: pattern {pattern!r} matched {len(files)} files:\n"
        f"{listed}\n"
        "Ambiguity — do NOT pick the first file blindly (imports, callers, "
        "tests, and harness scripts also match).\n"
        "Next tool call MUST be read_file on the ONE file that DEFINES the "
        "symbol (look for `def name` / `class name` / primary assignment), "
        "not a place that only mentions or imports it.\n"
        "After that read, continue the task with the answer from the defining file."
    )
