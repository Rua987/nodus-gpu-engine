#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ TEMPLE IAM - NODUS AMPLIFY
⚡ Amplification OPT-IN : best-of-N de run_agent, gardé par les oracles au sol
🔥 Récolte pass@k — N tentatives fraîches, on garde la 1re CERTIFIÉE

Copyright © 2024 Temple IAM - All Rights Reserved

Câble `nodus_search.best_of_n` sur l'agent réel :
    generate(i) = un run_agent COMPLET dans une tentative fraîche (isolée).
    verify(dir) = les oracles (acceptation / mutation / perceptuel) sur l'artefact.

Le 1er artefact certifié est PROMU dans le cwd ; sinon on promeut la dernière
tentative et on rend verified=False (honnête : amplification épuisée).

PRÉCONDITION : il faut un signal vérifiable (au moins un oracle activable par la
tâche), sinon best-of-N ne peut RIEN sélectionner → on ne fait qu'UNE tentative
(pas de gaspillage). Et le verdict ne vaut que la solidité des oracles (un faux
positif = amplification vers du faux — cf. [[nodus-semantic-oracle]]).

COÛT : N tentatives = coût/latence × N. D'où l'opt-in (`--amplify N`, défaut 1).

API :
    amplified_run(task, cwd, n, ...) → AmplifyResult
"""

import os
import shutil
import tempfile
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from nodus_acceptance import acceptance_verdict, plan_acceptance_check
from nodus_oracle import evaluate_oracle_checks, plan_oracle_checks
from nodus_perceptual import evaluate_perceptual_checks, extract_perceptual_checks
from nodus_search import best_of_n
from nodus_verify import extract_expected_commands, extract_expected_files


@dataclass
class AmplifyResult:
    """Résultat d'un run amplifié."""
    verified: bool            # un artefact a-t-il été certifié au sol ?
    attempts: int             # nombre de tentatives effectuées
    index: Optional[int]      # indice de la tentative gagnante (sinon None)
    result: Any               # l'AgentResult de la tentative promue


def _build_checks(task: str, cwd: Optional[str]) -> Dict:
    """Calcule les oracles activables par la tâche (une fois)."""
    files = extract_expected_files(task)
    commands = extract_expected_commands(task)
    return {
        "acceptance": plan_acceptance_check(task, files),
        "oracle": plan_oracle_checks(files, commands),
        "perceptual": extract_perceptual_checks(task),
    }


def _verify_dir(checks: Dict, attempt_dir: str) -> bool:
    """
    Un répertoire-tentative est-il certifié par TOUS les oracles activables ?

    Retourne False si aucun oracle n'est activable (rien à certifier → best-of-N
    ne doit pas « réussir » sur du vide).
    """
    has_signal = False

    acc = checks["acceptance"]
    if acc is not None:
        has_signal = True
        if not acceptance_verdict(acc[0], acc[1], cwd=attempt_dir)["ok"]:
            return False

    orc = checks["oracle"]
    if orc:
        has_signal = True
        if evaluate_oracle_checks(orc, cwd=attempt_dir) is not None:
            return False

    per = checks["perceptual"]
    if per:
        has_signal = True
        if evaluate_perceptual_checks(per, cwd=attempt_dir) is not None:
            return False

    return has_signal


def _promote(src_dir: str, cwd: str) -> None:
    """Copie les fichiers (niveau racine) de la tentative gagnante vers le cwd."""
    for name in os.listdir(src_dir):
        src = os.path.join(src_dir, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(cwd, name))


def amplified_run(
    task: str,
    cwd: str,
    n: int,
    run: Optional[Callable] = None,
    verbose: bool = False,
    **run_kwargs: Any,
) -> AmplifyResult:
    """
    best-of-N : jusqu'à ``n`` runs frais ; promeut le 1er artefact certifié.

    Args:
        task:       la tâche.
        cwd:        répertoire de travail final (recevra l'artefact gagnant).
        n:          budget de tentatives (amplification).
        run:        runner injectable (défaut: nodus_agent.run_agent) ; signature
                    ``run(task, cwd=..., verify=True, oracle=True, **run_kwargs)``.
        verbose:    journalise chaque tentative et le verdict.
        run_kwargs: options passées au runner (model, profile, max_rounds…).

    Returns:
        AmplifyResult (verified, attempts, index, result).
    """
    runner = run if run is not None else _default_runner
    os.makedirs(cwd, exist_ok=True)
    checks = _build_checks(task, cwd)
    attempt_dirs: list = []
    results: Dict[str, Any] = {}

    def generate(i: int) -> str:
        adir = tempfile.mkdtemp(prefix=f"amplify{i}_")
        attempt_dirs.append(adir)
        results[adir] = runner(
            task, cwd=adir, verify=True, oracle=True, **run_kwargs
        )
        return adir

    def verify(adir: str) -> bool:
        ok = _verify_dir(checks, adir)
        if verbose:
            print(f"[amplify] attempt {adir}: {'CERTIFIED' if ok else 'rejected'}")
        return ok

    # Sans signal vérifiable, best-of-N ne peut rien sélectionner → 1 tentative
    # (l'amplification est vaine sans oracle ; on ne gaspille pas N runs).
    has_signal = bool(checks["acceptance"]) or bool(checks["oracle"]) or bool(
        checks["perceptual"]
    )
    search = best_of_n(generate, verify, n if has_signal else 1)
    chosen = search.candidate
    if chosen is not None:
        _promote(chosen, cwd)
    for adir in attempt_dirs:
        shutil.rmtree(adir, ignore_errors=True)

    if verbose:
        print(f"[amplify] verified={search.ok} after {search.attempts} attempt(s)")
    return AmplifyResult(
        verified=search.ok,
        attempts=search.attempts,
        index=search.index,
        result=results.get(chosen),
    )


def _default_runner(task: str, **kwargs: Any) -> Any:
    """Runner par défaut : run_agent (import paresseux → pas de cycle)."""
    import nodus_agent  # noqa: PLC0415
    return nodus_agent.run_agent(task, **kwargs)
