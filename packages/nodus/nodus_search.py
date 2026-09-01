#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ TEMPLE IAM - NODUS SEARCH
⚡ AMPLIFICATION : transformer le vérificateur en signal de recherche
🔥 pass@1 → pass@k — récolter ce que le modèle réussit PARFOIS, certifié au sol

Copyright © 2024 Temple IAM - All Rights Reserved

L'idée (le seul amplificateur qui marche vraiment) :
    Un modèle a un pass@1 (réussir du 1er coup) et un pass@k (≥1 essai sur k
    correct) ; sur le dur, pass@k ≫ pass@1. Un vérificateur À DENTS (zéro faux
    positif) permet de RÉCOLTER pass@k : on génère plusieurs candidats et on
    garde le PREMIER que le vérificateur certifie. C'est best-of-N / le principe
    d'AlphaCode.

    PRÉCONDITION ABSOLUE : le vérificateur doit être SAIN. Un seul faux positif
    et la recherche converge vers une réponse FAUSSE certifiée. C'est pourquoi
    toute la couche d'oracles (dents, no-false-positive) est le SOCLE de
    l'amplification, pas son alternative.

    BORNE HONNÊTE : l'amplification est plafonnée par pass@k. Si le modèle a une
    proba ~0 de produire la bonne réponse, aucune recherche n'aide — le
    vérificateur confirme juste l'échec, honnêtement. On amplifie le « dur mais
    atteignable », pas l'« impossible pour ce modèle ».

API :
    best_of_n(generate, verify, n)  → SearchResult (1er candidat certifié)
    expected_success(p, n)          → 1-(1-p)^n (borne théorique, pour mesurer)
"""

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class SearchResult:
    """Résultat d'une recherche best-of-N."""
    ok: bool                 # un candidat a-t-il été certifié ?
    candidate: Any           # le candidat certifié (ou le dernier essayé si échec)
    attempts: int            # nombre de candidats générés
    index: Optional[int]     # indice (0-based) du candidat certifié, sinon None


def best_of_n(
    generate: Callable[[int], Any],
    verify: Callable[[Any], bool],
    n: int,
    on_attempt: Optional[Callable[[int, Any], None]] = None,
) -> SearchResult:
    """
    Génère jusqu'à ``n`` candidats ; retourne le PREMIER que ``verify`` certifie.

    Cœur de l'amplification : la valeur du résultat ne vaut QUE la solidité de
    ``verify`` (un faux positif = amplification vers du faux).

    Args:
        generate:   ``generate(i)`` → candidat i (peut varier : température, seed…).
        verify:     ``verify(candidat)`` → True si certifié au sol.
        n:          budget maximum de candidats.
        on_attempt: callback optionnel ``(i, candidat)`` observé à chaque essai.

    Returns:
        SearchResult. ``ok=False`` si aucun candidat n'est certifié (ou n<=0).

    Example:
        >>> r = best_of_n(lambda i: i, lambda c: c == 3, 5)
        >>> (r.ok, r.candidate, r.attempts, r.index)
        (True, 3, 4, 3)
        >>> best_of_n(lambda i: i, lambda c: False, 2).ok
        False
    """
    last: Any = None
    for i in range(n):
        candidate = generate(i)
        last = candidate
        if on_attempt is not None:
            on_attempt(i, candidate)
        if verify(candidate):
            return SearchResult(ok=True, candidate=candidate, attempts=i + 1, index=i)
    return SearchResult(ok=False, candidate=last, attempts=max(n, 0), index=None)


def expected_success(p: float, n: int) -> float:
    """
    Probabilité théorique de succès d'un best-of-N : ``1 - (1-p)^n``.

    ``p`` = pass@1 du générateur (avec un vérificateur SAIN). Sert à confronter
    la mesure empirique à la borne.

    Example:
        >>> round(expected_success(0.5, 5), 4)
        0.9688
        >>> expected_success(0.0, 10)
        0.0
    """
    return 1.0 - (1.0 - p) ** n
