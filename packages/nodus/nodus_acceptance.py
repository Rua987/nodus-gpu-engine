#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ TEMPLE IAM - NODUS ACCEPTANCE ORACLE
⚡ Conformité à l'INTENTION : l'artefact fait-il ce que l'HUMAIN a demandé ?
🔥 Le verdict externe bat le verdict de soi — des exemples que le modèle n'a PAS écrits.

Copyright © 2024 Temple IAM - All Rights Reserved

Le trou que ça comble (le plafond de vérification suivant) :
    mutation testing prouve « tes tests ont des dents » — mais sur TON impl. Un
    modèle peut être confidemment, cohéremment FAUX : il a mal compris la demande,
    écrit code faux ET tests faux dans le même sens. Mutation = 100%, gate verte,
    et c'est faux. Aucune garde interne n'attrape ça.

L'idée (oracle d'acceptation, AVEC dents) :
    L'humain fournit des cas `assert f(entrée) == sortie` — sa vérité au sol, que
    le modèle n'a PAS rédigée. On les exécute contre l'artefact (verdict externe).
    Self-test de dents identique aux autres oracles : les cas doivent ÉCHOUER quand
    l'implémentation est ABSENTE (module vidé). S'ils passent quand même, ils ne
    dépendent pas de l'artefact → vacueux → on refuse de certifier.

    En code : muter l'impl, exiger l'échec des tests.
    En média : perturber la référence, exiger l'échec de la comparaison.
    En acceptation : vider l'impl, exiger l'échec des cas.
    Même vérité : un contrôle qui ne peut pas échouer ne prouve rien.

API :
    extract_acceptance_cases(task)            → ['assert ...', ...] (vérité humaine)
    acceptance_verdict(module, cases, cwd)    → {ok, reason, failures}
    acceptance_challenge(verdict)             → message de relance forcée
"""

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Convention : un cas d'acceptation est une instruction `assert <expr>` dans la
# tâche (s'arrête à un saut de ligne ou un `;` → plusieurs cas par ligne).
_ASSERT_RE = re.compile(r'assert\s+[^\n;]+')
# Fichier de test (à exclure du choix de l'IMPL à éprouver).
_TESTFILE_RE = re.compile(
    r'(?:^|[/\\])(?:test_[\w\-]+|[\w\-]+_test)\.py$', re.IGNORECASE
)


def extract_acceptance_cases(task: str) -> List[str]:
    """
    Extrait les cas d'acceptation (`assert ...`) fournis par l'humain dans la tâche.

    Fonction pure. Déduplique en préservant l'ordre ; retire un point de fin de
    phrase éventuel (prose) sans toucher aux décimales.

    Example:
        >>> extract_acceptance_cases("impl f; it must satisfy assert f(2) == 4.")
        ['assert f(2) == 4']
        >>> extract_acceptance_cases("just read config.json")
        []
    """
    if not task:
        return []
    cases: List[str] = []
    seen = set()
    for match in _ASSERT_RE.finditer(task):
        case = match.group(0).strip()
        # Retirer UN point final de phrase ("== 4." → "== 4", "3.5." → "3.5").
        if case.endswith("."):
            case = case[:-1].rstrip()
        if case and case not in seen:
            seen.add(case)
            cases.append(case)
    return cases


def plan_acceptance_check(
    task: str, expected_files: List[str]
) -> Optional[Tuple[str, List[str]]]:
    """
    Apparie les cas d'acceptation de la tâche au fichier-IMPL à éprouver.

    L'impl = un fichier `.py` attendu qui N'est PAS un fichier de test. On ne
    forme un check que s'il y a des cas ET exactement un candidat impl (sinon on
    s'abstient — pas de verdict sur une cible incertaine). Fonction pure.

    Example:
        >>> plan_acceptance_check("assert f(2)==4", ["f.py", "test_f.py"])
        ('f.py', ['assert f(2)==4'])
        >>> plan_acceptance_check("no cases here", ["f.py"])
    """
    cases = extract_acceptance_cases(task)
    if not cases:
        return None
    impls = [
        f for f in expected_files
        if f.lower().endswith(".py") and not _TESTFILE_RE.search(f)
    ]
    if len(impls) == 1:
        return impls[0], cases
    return None


def _resolve(module_file: str, cwd: Optional[str]) -> Path:
    p = Path(module_file)
    if not p.is_absolute() and cwd:
        p = Path(cwd) / module_file
    return p


def _build_runner(modname: str, moddir: str, cases: List[str]) -> str:
    """Source d'un script qui importe le module et exécute chaque cas isolément."""
    lines = [
        "import json, sys",
        f"sys.path.insert(0, {moddir!r})",
        "__fails = []",
        "try:",
        f"    from {modname} import *",
        "except Exception as __e:",
        "    print('ACCEPT_FAILS=' + json.dumps(['import: ' + repr(__e)])); "
        "sys.exit(0)",
    ]
    for case in cases:
        lines += [
            "try:",
            f"    {case}",
            "except Exception as __e:",
            f"    __fails.append({case!r} + ' -> ' + repr(__e))",
        ]
    lines.append("print('ACCEPT_FAILS=' + json.dumps(__fails))")
    return "\n".join(lines)


def _run_cases(module_file: str, cases: List[str], cwd: Optional[str]) -> List[str]:
    """Exécute les cas contre le module ; retourne la liste des cas en échec."""
    path = _resolve(module_file, cwd)
    runner = _build_runner(path.stem, str(path.parent), cases)
    proc = subprocess.run(
        [sys.executable, "-c", runner],
        cwd=cwd or None,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    for line in proc.stdout.splitlines():
        if line.startswith("ACCEPT_FAILS="):
            try:
                return json.loads(line[len("ACCEPT_FAILS="):])
            except json.JSONDecodeError:
                break
    # Le runner n'a rien émis (crash inattendu) → on ne peut pas certifier.
    return list(cases)


def acceptance_verdict(
    module_file: str,
    cases: List[str],
    cwd: Optional[str] = None,
) -> Dict:
    """
    L'artefact satisfait-il les cas humains — ET ces cas ont-ils des dents ?

    Conditions :
        1. contrainte — au moins un cas (sinon ``no_constraints``).
        2. existence — le module est présent (sinon ``missing``).
        3. dents — les cas ÉCHOUENT quand l'impl est vidée (sinon ``vacuous`` :
           ils ne dépendent pas de l'artefact).
        4. conformité — les cas passent sur l'impl réelle.

    Returns:
        {"ok": bool, "reason": str, "failures": list}.
        ``reason`` ∈ {"no_constraints", "missing", "vacuous", "fail", "pass"}.
    """
    if not cases:
        return {"ok": False, "reason": "no_constraints", "failures": []}
    path = _resolve(module_file, cwd)
    if not path.exists():
        return {"ok": False, "reason": "missing", "failures": []}

    # Dents : vider l'impl, les cas doivent casser (ils dépendent de l'artefact).
    original = path.read_text(encoding="utf-8")
    try:
        path.write_text("", encoding="utf-8")
        fails_blank = _run_cases(module_file, cases, cwd)
    finally:
        path.write_text(original, encoding="utf-8")
    if not fails_blank:
        return {"ok": False, "reason": "vacuous", "failures": []}

    fails_real = _run_cases(module_file, cases, cwd)
    if fails_real:
        return {"ok": False, "reason": "fail", "failures": fails_real}
    return {"ok": True, "reason": "pass", "failures": []}


def acceptance_challenge(verdict: Dict) -> str:
    """
    Relance forcée quand le verdict d'acceptation n'est pas « pass ».

    Fonction pure.

    Example:
        >>> "acceptance" in acceptance_challenge({"reason": "fail"}).lower()
        True
    """
    reason = verdict.get("reason")
    if reason == "no_constraints":
        return (
            "No acceptance cases were given — nothing pins the intended behavior. "
            "Provide `assert f(input) == expected` examples so correctness can be "
            "checked against YOUR ground truth, not the model's own tests."
        )
    if reason == "missing":
        return (
            "The implementation file does not exist yet. Create it, then it will "
            "be checked against the acceptance cases."
        )
    if reason == "vacuous":
        return (
            "The acceptance cases PASS even with the implementation removed — they "
            "do not actually exercise the artifact. Write cases that call the "
            "produced function(s) and assert real outputs."
        )
    fails = "; ".join(verdict.get("failures", [])[:5]) or "some cases failed"
    return (
        f"The implementation FAILS the acceptance cases ({fails}). "
        "It does not do what was asked — fix it to satisfy every case, then re-run."
    )
