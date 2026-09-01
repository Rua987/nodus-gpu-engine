#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ TEMPLE IAM - NODUS KNOWLEDGE
⚡ Pont mémoire : le cerveau qui AGIT retient ses découvertes réutilisables
🔥 Écrit en fin de tâche · rappelé par PERTINENCE · ré-injecté sur tâches voisines

Copyright © 2024 Temple IAM - All Rights Reserved

Idée :
    L'agent ReAct (qui a les outils) ne retenait rien de substantiel ; la mémoire
    riche vivait dans le swarm (sans outils). Une découverte faite en agissant
    était perdue. Ce module donne à l'agent un store de DÉCOUVERTES textuelles,
    rappelées par similarité (Jaccard de mots-clés), comme le playbook rappelle
    des CHEMINS d'outils. Différence avec .nodus_memory.md : la mémoire est un
    dump chronologique injecté en bloc ; ici on rappelle UNIQUEMENT les
    découvertes pertinentes pour la tâche courante.

    resolve_knowledge_path()        → chemin de .nodus_knowledge.md
    save_finding(path, task, find)  → ajoute une découverte datée (plafonnée)
    load_findings(path)             → découvertes persistées
    recall_findings(task, finds)    → les plus pertinentes (Jaccard décroissant)
    format_findings_for_prompt(...) → bloc injectable

    Approche Karpathy : fonctions pures, I/O isolée. task_signature réutilisé
    depuis nodus_playbook (DRY).
"""

from datetime import datetime
from pathlib import Path
from typing import List, NamedTuple, Optional

from nodus_playbook import task_signature

# ── Constantes ────────────────────────────────────────────────────────────────
KNOWLEDGE_FILE   = ".nodus_knowledge.md"
KNOWLEDGE_HEADER = "# 🧠 NODUS Knowledge (reusable findings)"
ENTRY_SEPARATOR  = "\n---\n"
MAX_FINDINGS     = 30      # plafond du store (les plus récentes gagnent)
MAX_FINDING_CHARS = 400    # troncature d'une découverte
MATCH_THRESHOLD  = 0.12    # similarité Jaccard minimale pour rappeler


# ── Découverte ──────────────────────────────────────────────────────────────

class Finding(NamedTuple):
    """Une découverte réutilisable : son texte, ses mots-clés, son horodatage."""
    finding: str       # l'insight distillé (une ligne)
    keywords: tuple    # mots-clés signature (pour le matching)
    timestamp: str     # horodatage ISO


# ── Résolution du chemin ──────────────────────────────────────────────────────

def resolve_knowledge_path(
    cwd: Optional[str] = None,
    knowledge_path: Optional[str] = None,
) -> Path:
    """
    Résout le chemin du fichier de découvertes.

    Priorité : knowledge_path explicite > cwd/.nodus_knowledge.md >
    ./.nodus_knowledge.md. Fonction pure.

    Args:
        cwd:            Répertoire de travail
        knowledge_path: Chemin explicite (prioritaire)

    Returns:
        Path absolu vers le store.

    Example:
        >>> resolve_knowledge_path(knowledge_path="/tmp/k.md").name
        'k.md'
    """
    if knowledge_path:
        return Path(knowledge_path).resolve()
    if cwd:
        return (Path(cwd) / KNOWLEDGE_FILE).resolve()
    return (Path.cwd() / KNOWLEDGE_FILE).resolve()


# ── Similarité (réutilise la signature du playbook) ───────────────────────────

def _jaccard(a: set, b: set) -> float:
    """Similarité de Jaccard entre deux ensembles (0.0–1.0). Pure."""
    if not a or not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


# ── Lecture ───────────────────────────────────────────────────────────────────

def load_findings(path: Path) -> List[Finding]:
    """
    Charge les découvertes persistées.

    Args:
        path: Chemin du store

    Returns:
        Liste de Finding (vide si absent/illisible).

    Example:
        >>> load_findings(Path("/nonexistent/k.md"))
        []
    """
    try:
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    findings: List[Finding] = []
    ts = None
    keywords: tuple = ()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("### "):
            ts = stripped[4:].strip()
            keywords = ()
        elif stripped.startswith("keywords:") and ts is not None:
            keywords = tuple(
                w.strip() for w in stripped[len("keywords:"):].split(",") if w.strip()
            )
        elif stripped.startswith("finding:") and ts is not None:
            finding = stripped[len("finding:"):].strip()
            if finding:
                findings.append(Finding(finding, keywords, ts))
            ts = None
    return findings


def format_findings_for_prompt(findings: List[Finding]) -> str:
    """
    Formate des découvertes en bloc injectable dans le system prompt.

    Fonction pure — chaîne vide si aucune découverte.

    Args:
        findings: Découvertes pertinentes (de recall_findings)

    Returns:
        Bloc formaté (vide si findings vide).

    Example:
        >>> format_findings_for_prompt([])
        ''
        >>> "PAST FINDINGS" in format_findings_for_prompt(
        ...     [Finding("x resolves to y", ("a",), "2026-01-01")])
        True
    """
    if not findings:
        return ""
    lines = "\n".join(f"- {f.finding}" for f in findings)
    return (
        "\n\n## KNOWLEDGE FROM PAST FINDINGS (reusable, relevance-matched)\n"
        "On similar past tasks you recorded these findings. Reuse them if they "
        "fit — but they are notes, not law: re-verify before relying on one.\n"
        f"{lines}\n"
    )


# ── Statistiques ───────────────────────────────────────────────────────────────

def knowledge_stats(findings: list) -> dict:
    """
    Résume un ensemble de découvertes.

    Fonction pure : compte les découvertes et collecte tous les mots-clés
    distincts (triés) à travers l'ensemble des découvertes.

    Args:
        findings: Liste de Finding (chacun ayant un attribut .keywords).

    Returns:
        Dict {'count': int, 'keywords': list trié des mots-clés distincts}.

    Example:
        >>> a = Finding("x", ("ssrf", "redirect"), "2026-01-01")
        >>> b = Finding("y", ("redirect", "fetch"), "2026-01-02")
        >>> knowledge_stats([a, b])
        {'count': 2, 'keywords': ['fetch', 'redirect', 'ssrf']}
    """
    keywords = set()
    for f in findings:
        keywords.update(f.keywords)
    return {'count': len(findings), 'keywords': sorted(keywords)}


# ── Rappel par pertinence ─────────────────────────────────────────────────────

def recall_findings(
    task: str,
    findings: List[Finding],
    top_k: int = 2,
) -> List[Finding]:
    """
    Sélectionne les découvertes les plus pertinentes pour une tâche.

    Score = Jaccard(signature de la tâche, mots-clés de la découverte). On
    garde celles au-dessus de MATCH_THRESHOLD, triées par score décroissant,
    top_k max. Fonction pure.

    Args:
        task:     Tâche courante
        findings: Découvertes connues
        top_k:    Nombre max retourné

    Returns:
        Liste de découvertes pertinentes (peut être vide).

    Example:
        >>> f = Finding("redirect SSRF bypass: revalidate each hop",
        ...             ("ssrf", "redirect", "fetch"), "2026-01-01")
        >>> [x.finding for x in recall_findings("fix ssrf redirect in fetch", [f])]
        ['redirect SSRF bypass: revalidate each hop']
    """
    sig = task_signature(task)
    scored = []
    for f in findings:
        score = _jaccard(sig, set(f.keywords))
        if score >= MATCH_THRESHOLD:
            scored.append((score, f))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [f for _score, f in scored[:top_k]]


# ── Écriture ──────────────────────────────────────────────────────────────────

def save_finding(
    path: Path,
    task: str,
    finding: str,
    timestamp: Optional[str] = None,
    max_findings: int = MAX_FINDINGS,
) -> bool:
    """
    Ajoute une découverte au store et plafonne aux N plus récentes.

    Ne stocke RIEN si la découverte ou les mots-clés de la tâche sont vides
    (pas de signal réutilisable). La découverte est collapsée sur une ligne et
    tronquée. Déduplique sur le texte (une même découverte n'est pas répétée).

    Args:
        path:         Chemin du store
        task:         Tâche d'où vient la découverte (→ mots-clés de rappel)
        finding:      Texte de la découverte
        timestamp:    Horodatage (défaut: maintenant)
        max_findings: Plafond du store

    Returns:
        True si une découverte a été écrite, False sinon.

    Example:
        >>> import tempfile, os
        >>> p = Path(tempfile.gettempdir()) / "_test_know.md"
        >>> save_finding(p, "fix ssrf redirect", "revalidate each redirect hop")
        True
        >>> "revalidate" in load_findings(p)[0].finding
        True
        >>> os.remove(p)
    """
    finding_line = " ".join(finding.strip().split())[:MAX_FINDING_CHARS]
    keywords = tuple(sorted(task_signature(task)))
    if not finding_line or not keywords:
        return False

    ts = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    existing = load_findings(path)
    # Dédup sur le texte de la découverte (garde la plus récente)
    kept = [f for f in existing if f.finding != finding_line]
    kept.append(Finding(finding_line, keywords, ts))
    if len(kept) > max_findings:
        kept = kept[-max_findings:]

    blocks = [
        f"### {f.timestamp}\nkeywords: {', '.join(f.keywords)}\nfinding: {f.finding}\n"
        for f in kept
    ]
    content = KNOWLEDGE_HEADER + "\n\n" + ENTRY_SEPARATOR.join(blocks)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return True
    except OSError:
        return False
