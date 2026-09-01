#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ TEMPLE IAM - NODUS FALSIFY
⚡ Reverse-NODUS : chercher un CONTRE-EXEMPLE exécuté, pas faire confiance à des cas fixes
🔥 Comble l'angle mort prouvé : des cas/tests fixes partagent les angles morts du modèle

Copyright © 2024 Temple IAM - All Rights Reserved

Le trou que ça comble (prouvé au sol) :
    Les gates (acceptation/mutation) ne vérifient QUE ce qu'on leur donne. Si les
    cas humains ET les tests du modèle partagent le même angle mort (ex. n'essayer
    que des listes IMPAIRES pour une `median`), un bug sur les listes PAIRES passe
    « teeth 100% + acceptance pass » — un FAUX PASS. Aucun jeu de cas FIXE ne le
    rattrape.

L'idée (property-based / fuzzing, l'inverse de l'amplification) :
    Au lieu de chercher un artefact CORRECT (best_of_n), on cherche une ENTRÉE qui
    VIOLE un invariant. L'humain énonce des propriétés une fois (ex. « pour n pair,
    2*median == somme des deux milieux ») ; on les éprouve sur N entrées aléatoires.
    Le fuzzer touche fatalement le cas que les cas fixes rataient.

    Asymétrie HONNÊTE (comme pass@k) : un contre-exemple TROUVÉ est une vérité dure
    (il s'exécute, reproductible) ; AUCUN trouvé en N essais n'est PAS une preuve de
    correction — juste une absence bornée. On ne ment jamais sur ce qu'on n'a pas vu.

API :
    falsify(target, properties, generate, n) → FalsifyResult (contre-exemple ou rien)
"""

import json
import os
import random
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# Une propriété : (nom, prédicat) où prédicat(entrée, sortie) -> bool (True = tient).
Property = Tuple[str, Callable[[Any, Any], bool]]


@dataclass
class FalsifyResult:
    """Résultat d'une recherche de contre-exemple."""
    falsified: bool            # un contre-exemple a-t-il été trouvé ?
    counterexample: Any        # l'entrée fautive (ou None)
    property: Optional[str]    # la propriété violée (ou la cause)
    detail: str                # sortie observée / exception
    checked: int               # nombre d'entrées éprouvées


def falsify(
    target: Callable[[Any], Any],
    properties: List[Property],
    generate: Callable[[random.Random], Any],
    n: int = 200,
    seed: int = 0,
) -> FalsifyResult:
    """
    Cherche une entrée qui FAIT ÉCHOUER ``target`` sur une propriété — au sol.

    Pour chaque entrée tirée par ``generate`` :
      - si ``target`` LÈVE une exception → contre-exemple (crash) ;
      - si une propriété renvoie False → contre-exemple (invariant violé) ;
      - si une propriété LÈVE en s'évaluant → contre-exemple (on ne peut vérifier).
    Retourne le PREMIER contre-exemple, sinon ``falsified=False`` (absence bornée,
    PAS une preuve). Déterministe à ``seed`` donné (reproductible).

    Args:
        target:     fonction à éprouver (entrée -> sortie).
        properties: liste de (nom, prédicat(entrée, sortie) -> bool).
        generate:   ``generate(rng)`` -> une entrée aléatoire.
        n:          nombre d'entrées à éprouver.
        seed:       graine RNG (reproductibilité).

    Returns:
        FalsifyResult.

    Example:
        >>> import random
        >>> r = falsify(lambda x: x*x, [("nonneg", lambda i,o: o >= 0)],
        ...             lambda rng: rng.randint(-9, 9), n=50)
        >>> r.falsified
        False
        >>> bad = falsify(lambda x: x+1, [("identity", lambda i,o: o == i)],
        ...               lambda rng: rng.randint(0, 9), n=50)
        >>> bad.falsified
        True
    """
    rng = random.Random(seed)
    for i in range(n):
        inp = generate(rng)
        try:
            out = target(inp)
        except Exception as exc:  # noqa: BLE001 — un crash EST une falsification
            return FalsifyResult(True, inp, "<raised>",
                                 f"{type(exc).__name__}: {exc}", i + 1)
        for name, pred in properties:
            try:
                holds = pred(inp, out)
            except Exception as exc:  # noqa: BLE001 — propriété invérifiable = défaut
                return FalsifyResult(True, inp, name,
                                     f"property error: {type(exc).__name__}: {exc}",
                                     i + 1)
            if not holds:
                return FalsifyResult(True, inp, name, f"output={out!r}", i + 1)
    return FalsifyResult(False, None, None, "", n)


# ── Câblage en gate (opt-in) : fichier de propriétés fourni par l'humain ──────
# Convention : la tâche NOMME un module `*_props.py` (ou `*properties.py`) que
# l'humain écrit ; il importe l'impl produite et expose TARGET, PROPERTIES, generate.
_PROPS_RE = re.compile(r'\b((?:[\w\-]+[/\\])*[\w\-]*(?:_props|properties)\.py)\b',
                       re.IGNORECASE)


def plan_falsify_check(task: str) -> Optional[str]:
    """
    Repère le fichier de propriétés nommé dans la tâche (convention `*_props.py`).

    Fonction pure. Retourne le 1er fichier-propriétés mentionné, sinon None.

    Example:
        >>> plan_falsify_check("implement median; falsify against median_props.py")
        'median_props.py'
        >>> plan_falsify_check("just write code") is None
        True
    """
    if not task:
        return None
    m = _PROPS_RE.search(task)
    return m.group(1) if m else None


def _build_falsify_runner(modname: str, moddir: str, falsify_dir: str,
                          n: int, seed: int) -> str:
    """Source d'un script qui lance falsify via le module de propriétés humain."""
    return "\n".join([
        "import json, sys",
        f"sys.path.insert(0, {falsify_dir!r})",
        f"sys.path.insert(0, {moddir!r})",
        "from nodus_falsify import falsify",
        f"import {modname} as P",
        f"r = falsify(P.TARGET, P.PROPERTIES, P.generate, n={n}, seed={seed})",
        "print('FALSIFY=' + json.dumps({'falsified': r.falsified, "
        "'counterexample': repr(r.counterexample), 'property': r.property, "
        "'detail': r.detail, 'checked': r.checked}))",
    ])


def evaluate_falsify(props_file: str, cwd: Optional[str] = None,
                     n: int = 200, seed: int = 0) -> Optional[Dict]:
    """
    Lance falsify via un fichier de propriétés humain ; retourne un dict si un
    contre-exemple est trouvé (ou si le runner échoue), sinon None.

    Le runner s'exécute en sous-processus isolé ; on injecte le dossier de
    `nodus_falsify` dans le sys.path pour qu'il soit importable.
    """
    path = Path(props_file)
    if not path.is_absolute() and cwd:
        path = Path(cwd) / props_file
    falsify_dir = os.path.dirname(os.path.abspath(__file__))
    runner = _build_falsify_runner(path.stem, str(path.parent), falsify_dir, n, seed)
    proc = subprocess.run(
        [sys.executable, "-c", runner],
        cwd=cwd or None,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    for line in proc.stdout.splitlines():
        if line.startswith("FALSIFY="):
            try:
                data = json.loads(line[len("FALSIFY="):])
            except json.JSONDecodeError:
                break
            return data if data.get("falsified") else None
    # Le runner n'a rien émis (props cassé / interface manquante) → à corriger.
    return {"falsified": True, "property": "<runner-error>",
            "counterexample": "?", "detail": proc.stdout[-300:], "checked": 0}


def falsify_challenge(result: Dict) -> str:
    """
    Relance forcée quand falsify a trouvé un contre-exemple.

    Fonction pure.

    Example:
        >>> "counterexample" in falsify_challenge(
        ...     {"property": "p", "counterexample": "[1,2]", "detail": "x"}).lower()
        True
    """
    if result.get("property") == "<runner-error>":
        return (
            "The falsification check could not run (the properties file is broken "
            "or missing TARGET/PROPERTIES/generate). Fix it so the invariants can "
            f"be checked. Detail: {result.get('detail', '')[:200]}"
        )
    return (
        f"FALSIFIED: a counterexample violates the property '{result.get('property')}': "
        f"input={result.get('counterexample')} ({result.get('detail')}). "
        "Your code is wrong on this input — fix it so the invariant holds, then continue."
    )
