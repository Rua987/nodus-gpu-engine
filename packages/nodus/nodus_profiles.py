#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ TEMPLE IAM - NODUS PROFILES
⚡ Agents spécialisés : CODE · DEBUG · DOCS · TEST · RESEARCH · SECURITY · GENERAL
🔥 Un routeur choisit le bon profil selon la tâche

Copyright © 2024 Temple IAM - All Rights Reserved

Architecture:
    Fonctions PURES + données immuables (pas d'appel LLM ici).
    Chaque profil = un suffixe court ajouté au system prompt de base.

    route_task(task)        → choisit le profil (scoring par mots-clés)
    get_profile_prompt(name)→ suffixe de prompt du profil (vide si général)
    list_profiles()         → noms disponibles
"""

from typing import Dict, List, NamedTuple

# ── Profil ────────────────────────────────────────────────────────────────────

class Profile(NamedTuple):
    """Un profil d'agent spécialisé."""
    name: str
    description: str
    prompt: str          # suffixe ajouté au system prompt de base
    keywords: tuple      # mots-clés (minuscules) pour le routage


GENERAL = Profile(
    name="general",
    description="Agent polyvalent (défaut)",
    prompt="",  # aucun suffixe : comportement de base
    keywords=(),
)

CODE = Profile(
    name="code",
    description="Génération et écriture de code",
    prompt=(
        "\n\n## ROLE: CODE\n"
        "You write production code. After writing, ALWAYS read the file back "
        "to confirm. Follow the project's style. Keep functions small and pure."
    ),
    keywords=(
        "implement", "implémente", "write code", "écris le code", "code",
        "function", "fonction", "class", "classe", "refactor", "refactorise",
        "add a feature", "ajoute une fonctionnalité", "create a module",
    ),
)

DEBUG = Profile(
    name="debug",
    description="Analyse et correction d'erreurs",
    prompt=(
        "\n\n## ROLE: DEBUG\n"
        "You diagnose bugs. FIRST reproduce by running the failing command "
        "with bash. Read the real error. Find the root cause before changing "
        "anything. Verify the fix by re-running."
    ),
    keywords=(
        "debug", "bug", "error", "erreur", "fix", "corrige", "traceback",
        "crash", "exception", "fails", "échoue", "broken", "cassé", "why does",
        "pourquoi",
    ),
)

DOCS = Profile(
    name="docs",
    description="Rédaction de documentation",
    prompt=(
        "\n\n## ROLE: DOCS\n"
        "You write documentation. Read the actual code FIRST to document what "
        "it really does (not what you assume). Be concise and accurate. "
        "Use examples from the real code."
    ),
    keywords=(
        "document", "documente", "docs", "documentation", "readme", "docstring",
        "explain", "explique", "comment", "write a guide", "écris un guide",
    ),
)

TEST = Profile(
    name="test",
    description="Génération de tests",
    prompt=(
        "\n\n## ROLE: TEST\n"
        "You write tests. Read the code under test FIRST. Cover the happy path, "
        "edge cases, and errors. Use the project's test framework (pytest). "
        "Run the tests after writing them to confirm they pass."
    ),
    keywords=(
        "test", "tests", "teste", "unit test", "test unitaire", "coverage",
        "couverture", "pytest", "write tests", "écris les tests", "assert",
    ),
)

RESEARCH = Profile(
    name="research",
    description="Autoresearch : cherche → synthétise → code → teste",
    prompt=(
        "\n\n## ROLE: RESEARCH (autoresearch loop)\n"
        "Follow this loop strictly:\n"
        "1. SEARCH: use brave_search to find sources on the topic, then web_fetch "
        "the most relevant one(s) to read real content.\n"
        "2. SYNTHESIZE: base your understanding ONLY on what you fetched — NEVER "
        "on memory. If a fact is not in a fetched result, you do not know it.\n"
        "3. CODE: implement based on the findings (write_file).\n"
        "4. TEST: write tests and run them (bash python -m pytest) until they pass.\n"
        "Do not skip the search/fetch phase, even if you think you know the answer."
    ),
    keywords=(
        "research", "look up", "find out", "search the web", "latest", "how does",
        "documentation for", "recherche", "cherche", "renseigne", "trouve comment",
        "state of the art", "best practice", "best practices", "investigate",
    ),
)

SECURITY = Profile(
    name="security",
    description="Audit de sécurité : sinks ET failles d'absence/logique",
    prompt=(
        "\n\n## ROLE: SECURITY AUDIT\n"
        "You hunt REAL, exploitable vulnerabilities. Read the code first. Use TWO "
        "mindsets — and the second is the one most audits MISS:\n"
        "1. SINKS (tainted data reaches a dangerous call): command exec "
        "(os.system/os.popen/subprocess with shell), SQL built by string/f-string, "
        "eval/exec/pickle.loads, open()/path join with user input, unescaped HTML. "
        "Trace each from its SOURCE (user input — even across files or via the DB) "
        "to the SINK; name both.\n"
        "2. ABSENCE & WEAK GUARDS (the bug is what is MISSING, or what a check fails "
        "to cover) — look here EXPLICITLY:\n"
        "   - Access control: does a lookup-by-id verify OWNERSHIP? If not → IDOR/BOLA.\n"
        "   - SSRF: does a URL fetch validate the HOST, not just the scheme? "
        "scheme-only checks let internal/localhost/metadata IPs through → SSRF.\n"
        "   - Bypassable sanitizers: does a single-pass replace('../') or filter "
        "survive '....//', absolute paths, or encoding? If yes → traversal.\n"
        "   - AuthN/AuthZ: are sensitive endpoints reachable with NO auth?\n"
        "   - Secrets hardcoded in source; weak crypto (md5/sha1 for passwords, no salt).\n"
        "For EACH finding: file:line, class, SOURCE→SINK if it spans code, why it is "
        "exploitable, severity. Do NOT flag safe code (parameterized queries, "
        "subprocess with shell=False and a list of args). Distrust your own verdict: "
        "a vulnerability you cannot actually exploit is not a finding."
    ),
    keywords=(
        "security", "sécurité", "securite", "vulnerability", "vulnérabilité",
        "vuln", "vulns", "exploit", "faille", "failles", "audit", "audite",
        "pentest", "cve", "ssrf", "idor", "xss", "rce", "injection",
        "secure", "sécurise", "threat", "attack surface",
    ),
)

# Registre des profils (general en dernier = fallback)
_PROFILES: Dict[str, Profile] = {
    p.name: p for p in (CODE, DEBUG, DOCS, TEST, RESEARCH, SECURITY, GENERAL)
}


# ── API ───────────────────────────────────────────────────────────────────────

def list_profiles() -> List[str]:
    """
    Retourne la liste des noms de profils disponibles.

    Returns:
        Liste triée des noms.

    Example:
        >>> "code" in list_profiles()
        True
    """
    return sorted(_PROFILES.keys())


def get_profile(name: str) -> Profile:
    """
    Retourne un profil par son nom (insensible à la casse).

    Args:
        name: Nom du profil

    Returns:
        Le Profile correspondant, ou GENERAL si inconnu.

    Example:
        >>> get_profile("CODE").name
        'code'
        >>> get_profile("inexistant").name
        'general'
    """
    return _PROFILES.get((name or "").strip().lower(), GENERAL)


def get_profile_prompt(name: str) -> str:
    """
    Retourne le suffixe de prompt d'un profil.

    Args:
        name: Nom du profil

    Returns:
        Suffixe de prompt (chaîne vide pour general/inconnu).

    Example:
        >>> get_profile_prompt("general")
        ''
        >>> "DEBUG" in get_profile_prompt("debug")
        True
    """
    return get_profile(name).prompt


def _score_profile(task_lower: str, profile: Profile) -> int:
    """
    Compte combien de mots-clés du profil apparaissent dans la tâche.

    Args:
        task_lower: Tâche en minuscules
        profile:    Profil à scorer

    Returns:
        Nombre de mots-clés présents.
    """
    return sum(1 for kw in profile.keywords if kw in task_lower)


def route_task(task: str) -> str:
    """
    Choisit le profil le plus adapté à une tâche (scoring par mots-clés).

    Fonction pure. En cas d'égalité ou d'absence de match, retourne "general".
    Priorité en cas d'égalité : security, research, test, debug, docs, code.
    (security d'abord : un audit de failles ne doit pas être capté par "code"/"test".)

    Args:
        task: Texte de la tâche

    Returns:
        Nom du profil choisi.

    Example:
        >>> route_task("write unit tests for nodus_tools.py")
        'test'
        >>> route_task("audit this service for security vulnerabilities")
        'security'
        >>> route_task("just say hello")
        'general'
    """
    if not task or not task.strip():
        return "general"

    task_lower = task.lower()

    # Ordre de priorité pour départager les égalités (security gagne les ex-aequo)
    ordered = (SECURITY, RESEARCH, TEST, DEBUG, DOCS, CODE)

    best_name = "general"
    best_score = 0
    for profile in ordered:
        score = _score_profile(task_lower, profile)
        if score > best_score:
            best_score = score
            best_name = profile.name

    return best_name
