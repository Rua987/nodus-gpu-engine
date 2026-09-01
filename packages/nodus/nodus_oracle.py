#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ TEMPLE IAM - NODUS ORACLE
⚡ Vérification SÉMANTIQUE : des tests avec des DENTS, pas du théâtre
🔥 « Les tests passent » est gameable ; un test qui ne peut JAMAIS échouer ne prouve RIEN

Copyright © 2024 Temple IAM - All Rights Reserved

Le problème (la frontière butée toute la session) :
    `verify_commands` re-lance les tests et exige exit 0. Mais un modèle peut
    écrire des tests VACUEUX (`assert True`, aucune assertion sur le comportement)
    qui passent quoi qu'il arrive. exit 0 ≠ justesse. Le faux succès revient par
    la fenêtre : au lieu de mentir « j'ai créé le fichier », le modèle ment
    « mes tests prouvent que c'est correct ».

L'idée (mutation testing) :
    Un test ne CERTIFIE la justesse que s'il REJETTE une implémentation cassée.
    On casse délibérément le code (mutants : on échange `<`→`>=`, `+`→`-`, on
    décale une constante, on neutralise un `return`…) et on re-lance les tests :
        - mutant TUÉ (tests échouent)  → le test a des dents sur ce point.
        - mutant SURVIT (tests passent)→ le test est AVEUGLE sur ce comportement.
    Score de mutation = tués / évalués. Score faible ⇒ suite vacueuse ⇒ le
    « PASS » ne prouve rien ⇒ verdict HONNÊTE « non vérifié ».

    Couronnement de « le chemin, la vérité, pas le résultat » : la vérité d'un
    test, c'est sa capacité à échouer sur du faux. On l'ancre dans le CODE.

API :
    generate_mutants(source)                    → [(description, source_muté)]
    mutation_score(target, test_cmd, cwd)       → {mutants, killed, survived, score}
    oracle_verdict(target, test_cmd, cwd)       → {ok, reason, score, survived, ...}
    oracle_challenge(verdict)                    → message de relance forcée
    plan_pytest_vacuity_checks(...)              → fichiers test sans paire mutation
    evaluate_pytest_vacuity_checks(files, cwd)   → 1er verdict vacueux ou None
    pytest_vacuity_challenge(verdict)            → relance forcée (tests sans dents)
"""

import ast
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── Seuils ──────────────────────────────────────────────────────────────────
DEFAULT_MIN_SCORE = 0.5    # < 50% de mutants tués ⇒ suite jugée vacueuse
DEFAULT_MUTANT_LIMIT = 20  # borne le nombre de runs de tests (coût maîtrisé)

# Échanges d'opérateurs : chaque mutation CHANGE le comportement observable.
_CMP_SWAP = {
    ast.Lt: ast.GtE, ast.GtE: ast.Lt,
    ast.Gt: ast.LtE, ast.LtE: ast.Gt,
    ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
    ast.Is: ast.IsNot, ast.IsNot: ast.Is,
    ast.In: ast.NotIn, ast.NotIn: ast.In,
}
_BIN_SWAP = {
    ast.Add: ast.Sub, ast.Sub: ast.Add,
    ast.Mult: ast.Div, ast.Div: ast.Mult,
    ast.FloorDiv: ast.Mult,
    ast.Mod: ast.Sub,
}


# ── Génération des mutants (fonction pure) ──────────────────────────────────

def _eligible(tree: ast.AST) -> List[Tuple[int, str, Optional[int]]]:
    """
    Repère les sites mutables et leur indice dans l'ordre de ``ast.walk``.

    Retourne une liste de (index_walk, kind, detail). ``detail`` n'est utilisé
    que pour les comparaisons (indice de l'opérateur dans ``Compare.ops``).
    """
    plans: List[Tuple[int, str, Optional[int]]] = []
    for idx, node in enumerate(ast.walk(tree)):
        if isinstance(node, ast.Compare):
            for opi, op in enumerate(node.ops):
                if type(op) in _CMP_SWAP:
                    plans.append((idx, "cmp", opi))
        elif isinstance(node, ast.BoolOp):
            plans.append((idx, "bool", None))
        elif isinstance(node, ast.BinOp) and type(node.op) in _BIN_SWAP:
            plans.append((idx, "bin", None))
        elif isinstance(node, ast.Constant):
            # bool AVANT int : isinstance(True, int) est True en Python.
            if isinstance(node.value, bool):
                plans.append((idx, "constbool", None))
            elif isinstance(node.value, (int, float)) and not isinstance(
                node.value, complex
            ):
                plans.append((idx, "constnum", None))
        elif isinstance(node, ast.Return) and node.value is not None and not (
            isinstance(node.value, ast.Constant) and node.value.value is None
        ):
            plans.append((idx, "return", None))
    return plans


def _apply_plan(tree: ast.AST, idx: int, kind: str, detail: Optional[int]) -> str:
    """
    Applique UNE mutation au nœud d'indice ``idx`` ; retourne sa description.

    L'arbre passé doit provenir du MÊME source que celui analysé par
    ``_eligible`` (ordre de ``ast.walk`` identique → l'indice s'aligne).
    """
    for i, node in enumerate(ast.walk(tree)):
        if i != idx:
            continue
        if kind == "cmp":
            old = node.ops[detail]
            new_cls = _CMP_SWAP[type(old)]
            node.ops[detail] = new_cls()
            return f"comparison {type(old).__name__} -> {new_cls.__name__}"
        if kind == "bool":
            if isinstance(node.op, ast.And):
                node.op = ast.Or()
                return "boolean And -> Or"
            node.op = ast.And()
            return "boolean Or -> And"
        if kind == "bin":
            old = node.op
            new_cls = _BIN_SWAP[type(old)]
            node.op = new_cls()
            return f"arithmetic {type(old).__name__} -> {new_cls.__name__}"
        if kind == "constbool":
            node.value = not node.value
            return f"constant {not node.value} -> {node.value}"
        if kind == "constnum":
            old = node.value
            node.value = old + 1
            return f"constant {old!r} -> {node.value!r}"
        # kind == "return"
        node.value = ast.Constant(value=None)
        return "return value -> None"
    raise AssertionError("plan index not found")  # pragma: no cover


def generate_mutants(source: str, limit: int = 50) -> List[Tuple[str, str]]:
    """
    Génère des variantes CASSÉES du source (une mutation chacune).

    Fonction pure. Un source non parsable retourne ``[]``.

    Args:
        source: Code Python original.
        limit:  Nombre maximum de mutants retournés (borne le coût aval).

    Returns:
        Liste de (description, source_muté), au plus ``limit`` éléments.

    Example:
        >>> muts = generate_mutants("def f(a, b):\\n    return a < b\\n")
        >>> any("comparison Lt" in d for d, _ in muts)
        True
        >>> generate_mutants("def (:")
        []
    """
    try:
        base = ast.parse(source)
    except SyntaxError:
        return []

    mutants: List[Tuple[str, str]] = []
    for idx, kind, detail in _eligible(base):
        tree = ast.parse(source)  # re-parse → ordre de walk identique à base
        desc = _apply_plan(tree, idx, kind, detail)
        ast.fix_missing_locations(tree)
        mutants.append((desc, ast.unparse(tree)))
        if len(mutants) >= limit:
            break
    return mutants


# ── Score de mutation (re-exécution réelle des tests) ───────────────────────

def _run(test_command: str, cwd: Optional[str]) -> int:
    """Exécute la commande de test ; retourne le code de sortie."""
    proc = subprocess.run(
        test_command,
        shell=True,
        cwd=cwd or None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode


def _resolve_target_path(target_file: str, cwd: Optional[str] = None) -> Path:
    """Résout le chemin impl (relatif à cwd si besoin)."""
    path = Path(target_file)
    if not path.is_absolute() and cwd:
        path = Path(cwd) / target_file
    return path


def _is_test_module(filename: str) -> bool:
    """True si le basename ressemble à un module pytest (pas une impl à muter)."""
    name = Path(filename).name.lower()
    return name.startswith("test_") or name.endswith("_test.py")


def mutation_score(
    target_file: str,
    test_command: str,
    cwd: Optional[str] = None,
    mutant_limit: int = DEFAULT_MUTANT_LIMIT,
) -> Dict:
    """
    Mesure la proportion de mutants TUÉS par la suite de tests.

    Pour chaque mutant : on l'écrit dans ``target_file``, on relance
    ``test_command``, et le mutant est « tué » si les tests ÉCHOUENT (exit≠0).
    Le fichier original est TOUJOURS restauré (``finally``).

    Args:
        target_file:  Fichier d'implémentation à muter (sera réécrit puis restauré).
        test_command: Commande qui lance la suite de tests.
        cwd:          Répertoire d'exécution.
        mutant_limit: Borne du nombre de mutants évalués.

    Returns:
        {"mutants": n, "killed": k, "survived": [desc...], "score": k/n}.
        ``score`` vaut 0.0 quand aucun mutant n'est généré.
    """
    path = _resolve_target_path(target_file, cwd)
    if not path.is_file():
        return {"mutants": 0, "killed": 0, "survived": [], "score": 0.0}

    original = path.read_text(encoding="utf-8")
    mutants = generate_mutants(original, limit=mutant_limit)
    if not mutants:
        return {"mutants": 0, "killed": 0, "survived": [], "score": 0.0}

    killed = 0
    survived: List[str] = []
    try:
        for desc, code in mutants:
            path.write_text(code, encoding="utf-8")
            if _run(test_command, cwd) != 0:
                killed += 1
            else:
                survived.append(desc)
    finally:
        path.write_text(original, encoding="utf-8")

    return {
        "mutants": len(mutants),
        "killed": killed,
        "survived": survived,
        "score": killed / len(mutants),
    }


def oracle_verdict(
    target_file: str,
    test_command: str,
    cwd: Optional[str] = None,
    min_score: float = DEFAULT_MIN_SCORE,
    mutant_limit: int = DEFAULT_MUTANT_LIMIT,
) -> Dict:
    """
    Verdict sémantique : les tests passent-ils ET ont-ils des dents ?

    Deux conditions, dans l'ordre :
        1. baseline — les tests passent sur le code ORIGINAL (sinon rien à certifier).
        2. dents    — le score de mutation atteint ``min_score`` (sinon vacueux).

    Args:
        target_file:  Implémentation à éprouver.
        test_command: Suite de tests.
        cwd:          Répertoire d'exécution.
        min_score:    Score de mutation minimal pour parler de « dents ».
        mutant_limit: Borne du nombre de mutants.

    Returns:
        {"ok": bool, "reason": str, "score": float, "survived": [...],
         "killed": int, "mutants": int}.
        ``reason`` ∈ {"missing_target", "baseline_fail", "no_mutants", "vacuous", "teeth"}.
    """
    if not _resolve_target_path(target_file, cwd).is_file():
        return {
            "ok": False, "reason": "missing_target", "score": 0.0,
            "survived": [], "killed": 0, "mutants": 0,
        }

    if _run(test_command, cwd) != 0:
        return {
            "ok": False, "reason": "baseline_fail", "score": 0.0,
            "survived": [], "killed": 0, "mutants": 0,
        }

    result = mutation_score(target_file, test_command, cwd, mutant_limit)
    if result["mutants"] == 0:
        result["ok"] = False
        result["reason"] = "no_mutants"
    elif result["score"] < min_score:
        result["ok"] = False
        result["reason"] = "vacuous"
    else:
        result["ok"] = True
        result["reason"] = "teeth"
    return result


def plan_oracle_checks(
    expected_files: List[str], expected_commands: List[str]
) -> List[Tuple[str, str]]:
    """
    Apparie chaque commande de test à SON fichier-implémentation, sans ambiguïté.

    Pour une commande donnée (ex. ``python test_lru.py``), le fichier-impl est
    un fichier attendu dont le nom N'apparaît PAS dans la commande (donc pas le
    script de test lui-même). On ne forme une paire que si EXACTEMENT un candidat
    subsiste — sinon on s'abstient (pas de verdict fabriqué sur une cible incertaine).

    Le rapprochement se fait par NOM DE FICHIER ENTIER (pas sous-chaîne : sinon
    ``lru.py`` matcherait ``test_lru.py``) : on extrait les scripts cités dans la
    commande et on en exclut les fichiers attendus homonymes.

    Fonction pure.

    Example:
        >>> plan_oracle_checks(["lru.py", "test_lru.py"], ["python test_lru.py"])
        [('lru.py', 'python test_lru.py')]
        >>> plan_oracle_checks(["a.py", "b.py"], ["python test_lru.py"])
        []
    """
    pairs: List[Tuple[str, str]] = []
    for cmd in expected_commands:
        scripts = {
            Path(tok).name
            for tok in cmd.split()
            if tok.lower().endswith((".py", ".ps1"))
        }
        impls = [
            f for f in expected_files
            if Path(f).name not in scripts and not _is_test_module(f)
        ]
        if len(impls) == 1:
            pairs.append((impls[0], cmd))
    return pairs


# ── Vacuité pytest (sans fichier-impl) ──────────────────────────────────────

def _is_trivial_assert(node: ast.Assert) -> bool:
    """True si l'assertion ne peut jamais échouer (assert True, assert 1==1…)."""
    test = node.test
    if isinstance(test, ast.Constant) and test.value is True:
        return True
    if isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(
        test.ops[0], ast.Eq
    ):
        left, right = test.left, test.comparators[0]
        if isinstance(left, ast.Constant) and isinstance(right, ast.Constant):
            return left.value == right.value
    return False


def _iter_test_functions(tree: ast.Module):
    """Fonctions test_* au niveau module ou dans une classe."""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            yield node
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name.startswith("test_"):
                    yield item


def analyze_pytest_vacuity(source: str) -> Dict:
    """
    Détecte une suite pytest sans assertion significative (fonction pure).

    Returns:
        {vacuous, reason, meaningful_asserts, trivial_asserts, test_functions}
    """
    result = {
        "vacuous": True,
        "reason": "no_test_functions",
        "meaningful_asserts": 0,
        "trivial_asserts": 0,
        "test_functions": 0,
    }
    try:
        tree = ast.parse(source)
    except SyntaxError:
        result["reason"] = "syntax_error"
        return result

    funcs = list(_iter_test_functions(tree))
    result["test_functions"] = len(funcs)
    if not funcs:
        return result

    meaningful = 0
    trivial = 0
    for func in funcs:
        asserts = [n for n in ast.walk(func) if isinstance(n, ast.Assert)]
        if not asserts:
            continue
        for a in asserts:
            if _is_trivial_assert(a):
                trivial += 1
            else:
                meaningful += 1

    result["meaningful_asserts"] = meaningful
    result["trivial_asserts"] = trivial
    if meaningful > 0:
        result["vacuous"] = False
        result["reason"] = "ok"
    else:
        result["vacuous"] = True
        result["reason"] = (
            "no_assertions" if trivial == 0 else "only_trivial_assertions"
        )
    return result


def _pytest_script_names(cmd: str) -> List[str]:
    """Noms de fichiers .py cités dans une commande pytest."""
    return [
        Path(tok).name
        for tok in cmd.split()
        if tok.lower().endswith(".py") and not tok.startswith("-")
    ]


def plan_pytest_vacuity_checks(
    expected_files: List[str],
    expected_commands: List[str],
    mutation_pairs: Optional[List[Tuple[str, str]]] = None,
) -> List[str]:
    """
    Fichiers de test pytest sans paire mutation (impl, test) identifiable.

    Quand ``plan_oracle_checks`` ne peut pas apparier un impl, on exige quand
    même des assertions non triviales dans le fichier de test nommé.
    Fonction pure.

    Example:
        >>> plan_pytest_vacuity_checks([], ["python -m pytest test_evil.py"], [])
        ['test_evil.py']
    """
    covered_cmds = {cmd for _, cmd in (mutation_pairs or [])}
    files: List[str] = []
    seen = set()
    for cmd in expected_commands:
        if "pytest" not in cmd.lower():
            continue
        if cmd in covered_cmds:
            continue
        for name in _pytest_script_names(cmd):
            if name not in seen:
                seen.add(name)
                files.append(name)
    return files


def evaluate_pytest_vacuity_checks(
    test_files: List[str],
    cwd: Optional[str] = None,
) -> Optional[Dict]:
    """
    Retourne le 1er verdict non-ok parmi les fichiers test (vacuité AST).

    Enrichi de ``target`` (nom du fichier test fautif).
    """
    base = Path(cwd) if cwd else Path.cwd()
    for fname in test_files:
        path = Path(fname)
        if not path.is_absolute():
            path = base / fname
        if not path.is_file():
            continue
        analysis = analyze_pytest_vacuity(
            path.read_text(encoding="utf-8", errors="replace")
        )
        if analysis["vacuous"]:
            verdict = dict(analysis)
            verdict["ok"] = False
            verdict["reason"] = "vacuous_pytest"
            verdict["target"] = fname
            return verdict
    return None


def pytest_vacuity_challenge(verdict: Dict) -> str:
    """Relance forcée quand la suite pytest est vacueuse (fonction pure)."""
    target = verdict.get("target", "the test file")
    detail = verdict.get("reason", "vacuous_pytest")
    if detail == "no_test_functions":
        hint = "Add test functions that assert real expected behavior."
    elif detail == "no_assertions":
        hint = "Your test functions have no assertions — add asserts on outcomes."
    else:
        hint = (
            "Replace trivial asserts (`assert True`, `assert 1==1`) with checks "
            "on actual behavior or return values."
        )
    return (
        f"Pytest suite in {target} is vacuous ({detail}). "
        f"{hint} Tests must fail when the code is wrong."
    )


def evaluate_oracle_checks(
    checks: List[Tuple[str, str]],
    cwd: Optional[str] = None,
    min_score: float = DEFAULT_MIN_SCORE,
    mutant_limit: int = DEFAULT_MUTANT_LIMIT,
) -> Optional[Dict]:
    """
    Évalue chaque paire (impl, test) ; retourne le 1er verdict non-« teeth ».

    Retourne ``None`` si toutes les paires sont certifiées (dents). Le verdict
    renvoyé est enrichi de la clé ``target`` (le fichier-impl fautif).
    """
    for target_file, test_command in checks:
        verdict = oracle_verdict(
            target_file, test_command, cwd, min_score, mutant_limit
        )
        if not verdict["ok"]:
            verdict = dict(verdict)
            verdict["target"] = target_file
            return verdict
    return None


def oracle_challenge(verdict: Dict) -> str:
    """
    Construit la relance forcée quand le verdict sémantique n'est pas « teeth ».

    Fonction pure.

    Example:
        >>> "do not pass" in oracle_challenge({"reason": "baseline_fail"}).lower()
        True
    """
    reason = verdict.get("reason")
    if reason == "baseline_fail":
        return (
            "Your own tests do NOT pass on your code (non-zero exit). "
            "Fix the implementation (or the tests) and make the suite green "
            "before claiming correctness."
        )
    if reason == "missing_target":
        target = verdict.get("target", "implementation file")
        return (
            f"The implementation file {target} is missing on disk. "
            f"Create it with write_file before claiming the task is done."
        )
    if reason == "no_mutants":
        return (
            "No verifiable behavior was found to mutate — the implementation has "
            "no branches/operators/returns to challenge. Add real logic and "
            "tests that assert its behavior."
        )
    # reason == "vacuous"
    survivors = ", ".join(verdict.get("survived", [])[:5]) or "several mutations"
    score = verdict.get("score", 0.0)
    return (
        f"Your tests PASS even when the code is deliberately broken "
        f"(mutation score {score:.0%}; survived: {survivors}). "
        f"The tests are vacuous — they do not constrain behavior. "
        f"Strengthen them to assert the actual expected results, then re-run."
    )
