#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ TEMPLE IAM - NODUS PERCEPTUAL ORACLE
⚡ Vérification du MÉDIA : une image rendue est-elle la bonne — au sol ?
🔥 Même épistémologie que le mutation testing : un seuil ne certifie que s'il
   REJETTE une image fausse. On perturbe la référence ; la comparaison DOIT chuter.

Copyright © 2024 Temple IAM - All Rights Reserved

Le problème (frontière du média) :
    L'agent rend une image (Blender, ffmpeg…). `verify` prouve que le fichier
    EXISTE, jamais qu'il est CORRECT. « le rendu est bon » est un jugement
    visuel — historiquement réservé au maître. On veut l'ancrer dans le code.

L'idée (régression perceptuelle AVEC dents) :
    Comparer le rendu produit à une RÉFÉRENCE via SSIM (similarité structurelle).
    Mais un seuil trop lâche accepte n'importe quoi — vacueux, comme un test
    `assert True`. Donc on AUTO-TESTE le seuil : on PERTURBE la référence
    (décalage + bloc inversé) et on exige que la similarité chute SOUS le seuil.
    Si une image cassée passe encore, le seuil/la métrique ne prouve rien → on
    refuse de certifier (verdict honnête).

    En code : muter l'impl, exiger l'échec des tests.
    En média : perturber la référence, exiger l'échec de la comparaison.
    Même vérité : un contrôle qui ne peut pas échouer ne prouve rien.

API :
    image_similarity(a, b)                  → SSIM moyen par blocs ∈ [-1, 1]
    perceptual_verdict(produced, reference) → {ok, reason, similarity, teeth_*}
    perceptual_challenge(verdict)           → message de relance forcée
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

# ── Seuils ──────────────────────────────────────────────────────────────────
DEFAULT_THRESHOLD = 0.98   # SSIM minimal pour parler de « match »
_SSIM_BLOCKS = 8           # grille d'analyse locale (sensibilité aux détails)
_C1 = (0.01 * 255) ** 2
_C2 = (0.03 * 255) ** 2

# Activation de la gate perceptuelle sur LANGAGE NATUREL :
#   "<produite> ... <mot-de-similarité> ... <référence>"
# La 1re image est celle que l'agent doit RENDRE ; la 2e est la référence-oracle.
# Mots de similarité : matching/matches/match, looks like, identical to, same as,
# resembles, vs, against, like. L'écart entre images est borné ET ne peut PAS
# contenir une AUTRE image (lookahead négatif) → on n'apparie jamais la mauvaise
# (ex. "save a.png and render b.png matching ref.png" → (b.png, ref.png), pas a.png).
_IMG = r'(?:[A-Za-z]:)?[\w\-./\\]+\.(?:png|jpe?g|bmp|gif|tiff?|webp)'
_SIM_KW = (
    r'\b(?:match(?:es|ing)?|looks?\s+like|identical\s+to|same\s+as'
    r'|resembl\w+|vs\.?|against|like)'
)
_GAP_BEFORE = rf'(?:(?!{_IMG})[^.\n]){{0,40}}?'
_GAP_AFTER = rf'(?:(?!{_IMG})[^.\n]){{0,30}}?'
_PERCEPTUAL_RE = re.compile(
    rf'({_IMG}){_GAP_BEFORE}{_SIM_KW}{_GAP_AFTER}({_IMG})',
    re.IGNORECASE,
)


def load_gray(path: str) -> np.ndarray:
    """Charge une image en niveaux de gris (tableau 2D float64)."""
    return np.asarray(Image.open(path).convert("L"), dtype=np.float64)


def _block_ssim(a: np.ndarray, b: np.ndarray) -> float:
    """SSIM global d'un bloc (moyennes/variances/covariance)."""
    mu_a, mu_b = a.mean(), b.mean()
    va, vb = a.var(), b.var()
    cov = ((a - mu_a) * (b - mu_b)).mean()
    num = (2 * mu_a * mu_b + _C1) * (2 * cov + _C2)
    den = (mu_a ** 2 + mu_b ** 2 + _C1) * (va + vb + _C2)
    return float(num / den)


def mean_ssim(a: np.ndarray, b: np.ndarray, blocks: int = _SSIM_BLOCKS) -> float:
    """
    SSIM moyen par blocs — sensible aux différences LOCALES (≠ SSIM global qui
    noie une petite zone fausse dans les statistiques d'ensemble).

    Les deux images doivent avoir la même forme.

    Example:
        >>> import numpy as np
        >>> img = np.tile(np.arange(64, dtype=float), (64, 1))
        >>> round(mean_ssim(img, img), 6)
        1.0
    """
    h, w = a.shape
    bh, bw = max(1, h // blocks), max(1, w // blocks)
    scores = []
    for i in range(0, h, bh):
        for j in range(0, w, bw):
            scores.append(_block_ssim(a[i:i + bh, j:j + bw], b[i:i + bh, j:j + bw]))
    return float(np.mean(scores))


def perturb(img: np.ndarray) -> np.ndarray:
    """
    Casse une image de façon DÉTERMINISTE (décalage + bloc inversé).

    Sert au self-test du seuil : une référence perturbée DOIT être jugée
    dissemblable, sinon la comparaison est aveugle.
    """
    out = img.copy()
    h, w = out.shape
    out = np.roll(out, max(1, h // 10), axis=0)
    out = np.roll(out, max(1, w // 10), axis=1)
    bh, bw = max(1, h // 3), max(1, w // 3)
    out[:bh, :bw] = 255.0 - out[:bh, :bw]
    return out


def image_similarity(path_a: str, path_b: str) -> float:
    """
    Similarité SSIM entre deux fichiers image.

    Des dimensions différentes ⇒ 0.0 (taille fausse = déjà un échec, pas de
    redimensionnement silencieux qui maquillerait l'erreur).
    """
    a, b = load_gray(path_a), load_gray(path_b)
    if a.shape != b.shape:
        return 0.0
    return mean_ssim(a, b)


def perceptual_verdict(
    produced: str,
    reference: str,
    threshold: float = DEFAULT_THRESHOLD,
) -> Dict:
    """
    Le rendu produit correspond-il à la référence — ET le seuil a-t-il des dents ?

    Deux conditions :
        1. dents — la référence PERTURBÉE tombe sous le seuil (sinon vacueux :
           le seuil accepterait une image cassée).
        2. match — la similarité produit↔référence atteint le seuil.

    Returns:
        {"ok": bool, "reason": str, "similarity": float, "teeth_similarity": float}.
        ``reason`` ∈ {"vacuous_threshold", "mismatch", "match"}.
    """
    ref = load_gray(reference)
    teeth_similarity = mean_ssim(ref, perturb(ref))
    similarity = image_similarity(produced, reference)

    if teeth_similarity >= threshold:
        reason, ok = "vacuous_threshold", False
    elif similarity < threshold:
        reason, ok = "mismatch", False
    else:
        reason, ok = "match", True

    return {
        "ok": ok,
        "reason": reason,
        "similarity": similarity,
        "teeth_similarity": teeth_similarity,
    }


def extract_perceptual_checks(task: str) -> List[Tuple[str, str]]:
    """
    Extrait les paires (image_produite, image_référence) de la tâche.

    Convention : ``<produit> matching <référence>`` (ou matches/match/vs/against).
    Fonction pure. Déduplique en préservant l'ordre.

    Example:
        >>> extract_perceptual_checks("render out.png matching ref.png")
        [('out.png', 'ref.png')]
        >>> extract_perceptual_checks("just read config.json")
        []
    """
    if not task:
        return []
    pairs: List[Tuple[str, str]] = []
    seen = set()
    for produced, reference in _PERCEPTUAL_RE.findall(task):
        key = (produced, reference)
        if key not in seen:
            seen.add(key)
            pairs.append(key)
    return pairs


def _resolve(path: str, cwd: Optional[str]) -> Path:
    """Résout un chemin relatif contre cwd (sinon tel quel)."""
    p = Path(path)
    if not p.is_absolute() and cwd:
        p = Path(cwd) / path
    return p


def evaluate_perceptual_checks(
    checks: List[Tuple[str, str]],
    cwd: Optional[str] = None,
    threshold: float = DEFAULT_THRESHOLD,
) -> Optional[Dict]:
    """
    Évalue chaque paire (produit, référence) ; retourne le 1er verdict non-« match ».

    - Référence absente ⇒ pas d'oracle ⇒ on s'abstient (skip, pas de verdict fabriqué).
    - Image produite absente ⇒ échec « missing » (l'agent doit la rendre).
    - Sinon ⇒ ``perceptual_verdict``.

    Retourne ``None`` si toutes les paires vérifiables sont « match ». Le verdict
    renvoyé est enrichi de la clé ``target`` (l'image produite fautive).
    """
    for produced, reference in checks:
        ref_path = _resolve(reference, cwd)
        if not ref_path.exists():
            continue  # pas de référence-oracle → rien à certifier
        prod_path = _resolve(produced, cwd)
        if not prod_path.exists():
            return {
                "ok": False, "reason": "missing", "similarity": 0.0,
                "teeth_similarity": 0.0, "target": produced,
            }
        verdict = perceptual_verdict(str(prod_path), str(ref_path), threshold)
        if not verdict["ok"]:
            verdict = dict(verdict)
            verdict["target"] = produced
            return verdict
    return None


def perceptual_challenge(verdict: Dict) -> str:
    """
    Relance forcée quand le verdict perceptuel n'est pas « match ».

    Fonction pure.

    Example:
        >>> "reference" in perceptual_challenge(
        ...     {"reason": "mismatch", "similarity": 0.4, "teeth_similarity": 0.1}
        ... ).lower()
        True
    """
    reason = verdict.get("reason")
    if reason == "missing":
        return (
            f"The expected image was not produced: {verdict.get('target')}. "
            "Render it (it must match the reference), then re-run."
        )
    if reason == "vacuous_threshold":
        return (
            "The similarity threshold is too loose: even a deliberately broken "
            f"reference scores {verdict.get('teeth_similarity', 0.0):.3f} (>= threshold). "
            "The check cannot reject a wrong image — tighten the threshold or use "
            "a more discriminating reference."
        )
    return (
        f"The produced image does NOT match the reference "
        f"(SSIM {verdict.get('similarity', 0.0):.3f} < threshold). "
        "Fix the rendering until it matches the expected reference, then re-run."
    )
