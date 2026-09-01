#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ TEMPLE IAM - NODUS VERIFY
⚡ Vérification de POST-CONDITION : la réalité, pas la promesse
🔥 Le modèle prétend "j'ai écrit le fichier" → on VÉRIFIE qu'il existe

Copyright © 2024 Temple IAM - All Rights Reserved

Idée :
    Tant que NODUS fait confiance à la CLAIM du modèle, un modèle faible ou
    menteur passe (granite fabrique l'écriture, qwen dérive). La vérification
    force le réel : si la tâche dit "créer result.txt", on ne lâche pas tant
    que result.txt n'existe pas vraiment sur le disque.

    Couronnement de "le chemin, la vérité, pas le résultat" : on vérifie LA VÉRITÉ.

    extract_expected_files(task)   → fichiers que la tâche demande de créer
    verify_files(expected, cwd)    → ceux qui MANQUENT réellement
    verification_challenge(missing)→ message de relance forcée
"""

import json
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

# ── Seuils ────────────────────────────────────────────────────────────────────
MAX_VERIFY_RETRIES = 3   # relances de vérification max par tâche

# Verbes d'écriture (FR + EN) : une ligne qui les contient peut désigner un
# fichier à créer.
_WRITE_VERBS = (
    "write", "create", "save", "generate", "output", "produce",
    "update", "extend", "append", "add", "modify", "patch",
    # Gap A (auto-introspection filtrée) : verbes de PRODUCTION ratés — on a buté
    # sur "render" (Blender). Bas risque : il faut quand même un nom de fichier.
    "render", "export", "build", "compile", "draw", "dump", "emit",
    "écris", "écrire", "crée", "créer", "sauvegarde", "génère", "enregistre",
    "ajoute", "ajouter", "mets à jour", "mettre à jour", "modifie", "modifier",
    "étend", "étendre", "mets a jour", "mettre a jour", "rends", "exporte",
    "write_file", "edit_file",
)

_EXEC_VERBS = (
    "bash", "run", "execute", "executer", "exécuter", "executer",
    "lance", "lancer", "prouver", "prove", "valider", "verify",
)

_EXIT_ZERO_RE = re.compile(r"\bexit\s*(?:code\s*)?0\b", re.IGNORECASE)
_PYTHON_CMD_RE = re.compile(
    r'\bpython(?:\.exe)?\s+(?:-\S+\s+)*'
    r'(?:"((?:[A-Za-z]:)?[^"]+\.py)"|((?:[A-Za-z]:)?[\w\-./\\]+\.py))',
    re.IGNORECASE,
)
_SCRIPT_CMD_RE = re.compile(
    r'\b((?:[A-Za-z]:)?(?:[\w\-./\\]+/)?(?:scripts/|test_)[\w\-./\\]*\.(?:py|ps1))\b',
    re.IGNORECASE,
)

# Intention de TEST exprimée naturellement (sans le motif littéral "exit 0") :
# "run pytest", "run the tests", "unittest", "make sure the tests pass"…
# Élargit l'activation de la gate au langage réel (un dev ne tape pas "exit 0").
# `pytest`/`unittest` doivent être des TOKENS autonomes, pas des fragments de
# chemin (ex. "pytest-of-admin", "mini_pytest.py" ne déclenchent PAS).
_RUN_TESTS_RE = re.compile(
    r'(?<![\w/\\.\-])pytest(?![\w\-])'
    r'|(?<![\w/\\.\-])unittest(?![\w\-])'
    r'|\b(?:run|execute|exécut\w*|lance[rz]?)\b[^.\n]{0,30}\btests?\b'
    r'|\btests?\b[^.\n]{0,20}\b(?:pass(?:es)?|succeed|green)\b'
    r'|\b(?:make sure|ensure|verify|check)\b[^.\n]{0,30}\btests?\b',
    re.IGNORECASE,
)
# Fichier de test nommé : test_*.py ou *_test.py (chemin optionnel).
_TESTFILE_RE = re.compile(
    r'\b((?:[\w\-]+[/\\])*(?:test_[\w\-]+|[\w\-]+_test)\.py)\b',
    re.IGNORECASE,
)

# Extensions de fichiers reconnues (whitelist → évite les faux positifs comme
# "e.g" ou les numéros de version "2.0"). Élargie après red-team : un fichier
# `.conf`/`.env`/`.sql` échappait à la détection → verify ne le surveillait
# pas → l'agent pouvait "réussir" sans le créer. On couvre désormais la
# surface réaliste config/code/data/docs. Reste une LIMITE inhérente : une
# extension exotique (`.xyz`) non whitelistée échappe encore — frontière
# heuristique assumée (détecter tout `mot.mot` ferait de faux positifs sur
# "version 2.0", "Node.js", etc.).
_FILE_EXTS = (
    # texte / docs
    "txt", "md", "rst", "log", "pdf",
    # config
    "json", "jsonl", "yaml", "yml", "toml", "ini", "cfg", "conf", "env",
    "properties", "lock", "gitignore", "dockerfile", "makefile",
    # données
    "csv", "tsv", "xml", "sql", "ndjson", "parquet",
    # code
    "py", "js", "ts", "tsx", "jsx", "mjs", "cjs", "vue", "html", "css", "scss",
    "sh", "bash", "bat", "ps1", "go", "rs", "rb", "php", "java", "kt", "swift",
    "scala", "c", "cpp", "cc", "h", "hpp", "cs", "lua", "r", "jl", "dart",
    "ipynb", "proto", "graphql", "gql", "svg",
    # média / 3D (Gap A : pilotage Blender/ffmpeg — "render out.png", "export mesh.stl")
    "png", "jpg", "jpeg", "gif", "bmp", "webp", "tiff", "ico",
    "mp4", "mov", "avi", "mkv", "webm", "wav", "mp3", "flac", "ogg",
    "stl", "obj", "fbx", "glb", "gltf", "ply", "blend",
)
_FILENAME_RE = re.compile(
    r'\b((?:[A-Za-z]:)?[\w\-./\\]+\.(?:' + "|".join(_FILE_EXTS) + r'))\b',
    re.IGNORECASE,
)


# ── Garde-fous de plan (niveaux noms) ─────────────────────────────────────────
# Normalisation déterministe des NOMS d'outils produits par le planificateur NODUS
# (probe v2b : 81/100, 19 échecs edit↔bash / skip-read / brave→fetch). Le plan reste
# une SUGGESTION ; ces règles corrigent la SÉQUENCE avant le slot-fill.

# Séparateur d'étapes : "then / and then / puis" ou virgule.
_STEP_CONNECTOR_RE = re.compile(r"\bthen\b|\band then\b|\bpuis\b|,", re.IGNORECASE)

# Verbes de LECTURE (1re étape = read_file). Regex MOTS-ENTIERS : une sous-chaîne
# ("cat" dans "locate") ne doit pas déclencher le prédicat (ex. "Locate console.log" = grep).
_READ_VERB_RE = re.compile(
    r"\b(?:open|read|inspect|look at|view|show|display|print|examine|cat|review|"
    r"ouvre|lis|lire|regarde)\b",
    re.IGNORECASE,
)

# Verbes de LISTE de fichiers (1re étape = glob) — distincts de la recherche de chaîne.
_LIST_VERB_RE = re.compile(
    r"\b(?:list|find|enumerate|locate|gather|collect|give me a list|which|lister|énumère)\b",
    re.IGNORECASE,
)

# Verbes de RECHERCHE de chaîne/symbole (1re étape = grep)
_SEARCH_VERB_RE = re.compile(
    r"\b(?:search|grep|hunt|track down|scan|locate|cherche|recherche)\b",
    re.IGNORECASE,
)

# Catégorie de FICHIERS au pluriel → glob ("the benchmark scripts" / "*.ini configs"),
# vs une CHAÎNE ("console.log", "TODO") → grep.
_FILE_CATEGORY_RE = re.compile(
    r"\b(files|scripts|modules|configs|configurations|docs|documents|notebooks|"
    r"migrations|dependencies|deps|tests|logs)\b",
    re.IGNORECASE,
)

# Intention de MODIFICATION d'un fichier existant (edit_file) — PAS de création.
_EDIT_INTENT_RE = re.compile(
    r"\b(change|modify|fix|correct|edit|update|bump|flip|toggle|raise|lower|"
    r"move|delete|remove|replace|swap|patch|append|extend|adjust|clean up|"
    r"enable|disable|increase|decrease|reword|offset)\b",
    re.IGNORECASE,
)

# Clause finale EXEC → NE PAS convertir le bash final en edit_file (tâche "run/test/commit…").
_FINAL_EXEC_RE = re.compile(
    r"\b(run|execute|invoke|reload|restart|launch|apply|migrate|build|lint|"
    r"start|stop|deploy|commit|push|test|validate|verify|check|make|pytest|"
    r"npm|poetry|psql)\b",
    re.IGNORECASE,
)

# Clause EXEC en 1re position → le bash de tete est LEGITIME (ne pas le retirer).
# "make a/the ... file" = creation, PAS un exec make (lookahead).
_EXEC_FIRST_RE = re.compile(
    r"\b(?:run|execute|invoke|launch|bash|test|commit|push|build|lint|start|"
    r"stop|pytest|npm|poetry|git|pip|yarn|dotnet|cmake|"
    r"make(?!\s+(?:a|an|the)\s+(?:fresh\s+|new\s+)?file))\b",
    re.IGNORECASE,
)


# Vérification d'usage (y14 : "verify nothing else already uses that name") → grep.
_VERIFY_USAGE_RE = re.compile(
    r"\b(verify|confirm|check|ensure|make sure)\b.{0,40}"
    r"\b(nothing|no other|already|anywhere|uses|used|references|imports)\b",
    re.IGNORECASE,
)

# Intention WEB (brave_search) et FETCH après recherche (p15/y19).
_WEB_INTENT_RE = re.compile(
    r"\b(online|web|internet|tutorial|docs|page|url|urls|google|"
    r"search the web|search the internet)\b",
    re.IGNORECASE,
)
_WEB_FETCH_INTENT_RE = re.compile(
    r"\b(open one of the result urls|fetch|pull down|download the page|"
    r"page you find|result urls|fetch it|that page)\b",
    re.IGNORECASE,
)

# Cible anaphorique → edit du découvert (y10 : "the first one / the newest / that file").
# PAS "them" : "search them for X" vise les fichiers découverts, pas une cible d'écriture
# (z07/z16 gardent write_file — ils nomment un fichier de sortie neuf).
_ANAPHORIC_TARGET_RE = re.compile(
    r"\b(the first one|the first|the newest|the matching one|that file|the file)\b",
    re.IGNORECASE,
)

# Fichiers de build SANS extension reconnue par _FILENAME_RE (Makefile, Dockerfile…).
_BUILD_FILE_RE = re.compile(
    r"\b(Makefile|Dockerfile|Rakefile|Gemfile|Procfile|Vagrantfile|"
    r"requirements\.txt|package-lock\.json|Cargo\.toml)\b",
    re.IGNORECASE,
)

# Cible NEUVE nommée (write_file garde son sens : "create/write a new file/module/script").
_WRITE_NEW_FILE_RE = re.compile(
    r"\b(create|make|write|draft|compose|save|generate|new|fresh)\b"
    r".{0,40}\b(file|module|script)\b",
    re.IGNORECASE,
)

# Intention de CREATION d'un fichier nomme ("make a fresh file ...") — complete
# task_requests_write qui ratait x07 (verbe "make" hors liste, "called X" sans write).
_CREATE_FILE_RE = re.compile(
    r"\b(?:make|create|write|generate|produce|add|draft|compose)\b"
    r"[^.\n]{0,40}\b(?:file|fichier)\b",
    re.IGNORECASE,
)


# ── Détection des fichiers attendus ───────────────────────────────────────────

def extract_expected_files(task: str) -> List[str]:
    """
    Extrait les noms de fichiers que la tâche demande de créer/écrire.

    Fonction pure. Ne considère que les lignes contenant un verbe d'écriture,
    pour éviter d'inclure les fichiers seulement LUS (ex: 'sample.py' dans un
    grep). Déduplique en préservant l'ordre d'apparition.

    Args:
        task: Texte de la tâche

    Returns:
        Liste ordonnée et dédupliquée des fichiers attendus (vide si aucun).

    Example:
        >>> extract_expected_files('1. grep sample.py\\n2. write result.txt')
        ['result.txt']
        >>> extract_expected_files('just read config.json')
        []
    """
    if not task or not task.strip():
        return []

    found: List[str] = []
    seen = set()
    for line in task.splitlines():
        # Une seule ligne utilisateur contient souvent "Crée a.py ... ; Lance
        # python b.py". On vérifie par segment pour ne pas transformer un fichier
        # seulement exécuté en post-condition de création.
        segments = re.split(r"[;\n]|\bthen\b|\bpuis\b", line, flags=re.IGNORECASE)
        for segment in segments:
            # Frontiere de MOT, pas sous-chaine : "compile" dans le chemin
            # D:\\repos\\compiler\\... ne doit PAS activer le verbe d'ecriture
            # (meme classe que "cat" dans "locate" pour _READ_VERB_RE).
            if not any(
                re.search(r"\b" + re.escape(v) + r"\b", segment, re.IGNORECASE)
                for v in _WRITE_VERBS
            ):
                continue
            for match in _FILENAME_RE.finditer(segment):
                fname = match.group(1)
                before = segment[:match.start()].lower()
                # Fichier seulement LU dans le meme segment (avant le verbe write) :
                # "read a.py then write b.txt" est deja coupe ; ici "write b.txt from a.py"
                # peut encore citer a.py — on ignore les noms precedes d'un verbe de lecture.
                if re.search(
                    r"\b(read|open|grep|search|lit|lire|lis)\b[\w\s\-./\\]*$",
                    before,
                ):
                    continue
                if re.search(r"\b(python|py)\s+(?:[\"']?)?(?:[a-z]:)?[\w\-./\\]*$", before):
                    continue
                if fname not in seen:
                    seen.add(fname)
                    found.append(fname)
    return found


def detect_create_file(task: str) -> bool:
    """
    Vrai si la tache CREE un fichier nomme ("make a fresh file ...").

    Fonction pure. Complete task_requests_write pour les creations sans verbe
    write ni nom de fichier extrait (echec x07 du probe v5 : pred ['bash'] au
    lieu de ['write_file']).

    Example:
        >>> detect_create_file("Make a fresh file called deploy_notes.txt")
        True
        >>> detect_create_file("Run the unit tests with pytest")
        False
    """
    return bool(_CREATE_FILE_RE.search(task or ""))


def task_requests_write(task: str) -> bool:
    """
    Vrai si la tache demande clairement une creation/ecriture de fichier.

    Utilise pour completer un plan NODUS qui a omis write_file.
    Fonction pure.
    """
    if not task or not task.strip():
        return False
    if extract_expected_files(task):
        return True
    if detect_create_file(task):
        return True
    low = task.lower()
    return any(v in low for v in (
        "write ", "write_", "create ", "save ", "écris", "ecris", "crée", "cree ",
        "write_file", "edit_file",
    ))


def ensure_plan_has_write(names: Optional[List[str]], task: str) -> List[str]:
    """
    Si le plan n'a ni write_file ni edit_file mais la tache demande d'ecrire,
    append `write_file`. Fonction pure.

    Example:
        >>> ensure_plan_has_write(["read_file", "grep"], "read a.py then write out.txt")
        ['read_file', 'grep', 'write_file']
        >>> ensure_plan_has_write(["grep", "write_file"], "write out.txt")
        ['grep', 'write_file']
    """
    if not names:
        return list(names or [])
    out = list(names)
    if any(n in ("write_file", "edit_file") for n in out):
        return out
    if task_requests_write(task):
        out.append("write_file")
    return out


# Tache type p0b : "primary argument name used for the bash tool"
_PRIMARY_ARG_TOOL_RE = re.compile(
    r"primary\s+argument\s+name\s+used\s+for\s+the\s+(\w+)\s+tool",
    re.IGNORECASE,
)


def detect_primary_arg_tool(task: str) -> Optional[str]:
    """
    Si la tache demande le nom d'argument primaire d'un outil, retourne cet outil.

    Fonction pure. Ne revele PAS la valeur (ex. command) — seulement le nom d'outil.

    Example:
        >>> detect_primary_arg_tool(
        ...     "write x.txt with the primary argument name used for the bash tool"
        ... )
        'bash'
        >>> detect_primary_arg_tool("just write hello") is None
        True
    """
    if not task:
        return None
    m = _PRIMARY_ARG_TOOL_RE.search(task)
    return m.group(1).lower() if m else None


def ensure_plan_primary_arg_lookup(
    names: Optional[List[str]],
    task: str,
) -> List[str]:
    """
    Pour une tache primary-arg : garantir grep (pattern PRIMARY_ARG) avant write.

    Fonction pure. Complete aussi write_file via ensure_plan_has_write.

    Example:
        >>> ensure_plan_primary_arg_lookup(
        ...     ["read_file"],
        ...     "read f.py then write x.txt with primary argument name used for the bash tool",
        ... )
        ['read_file', 'grep', 'write_file']
    """
    out = ensure_plan_has_write(names, task)
    tool = detect_primary_arg_tool(task)
    if not tool:
        return out
    if "grep" in out:
        return out
    if out and out[0] == "read_file":
        return [out[0], "grep", *out[1:]]
    return ["grep", *out]


def primary_arg_lookup_hint(task: str) -> Optional[str]:
    """
    Hint system : greper la cle outil (ex. \"bash\") pour voir la ligne VALUE.

    Fonction pure. Ne revele PAS la valeur (ex. command).
    """
    tool = detect_primary_arg_tool(task)
    if not tool:
        return None
    # Motif avec guillemets : matche la ligne '"bash": "…"' du dict, pas seulement
    # le symbole PRIMARY_ARG (qui ne contient pas la VALUE).
    pat = f'"{tool}"'
    return (
        f"LOOKUP RULE: the task asks for the primary argument name of the `{tool}` tool. "
        f"After reading the source file, call grep with pattern {pat} (same file). "
        f"The matching line is a KEY→VALUE pair in PRIMARY_ARG. "
        f"`{tool}` is the KEY — write_file EXACTLY the one-word VALUE on the "
        f"right-hand side of that line (NOT the key `{tool}`; no quotes, no sentence)."
    )


def force_primary_arg_plan_targets(
    names: List[str],
    targets: List[Optional[str]],
    task: str,
) -> List[Optional[str]]:
    """
    Tache primary-arg : forcer les cibles slot-fill (ecrase les mauvaises).

    - tout `grep` → pattern `\"<outil>\"` (ex. `\"bash\"`) pour hit la ligne KEY→VALUE
      (PAS `PRIMARY_ARG`, qui ne montre pas la VALUE)
    - tout `write_file` → fichier attendu (preferer un nom avec `primary`)

    Fonction pure. Ne revele pas la valeur (ex. command).

    Example:
        >>> force_primary_arg_plan_targets(
        ...     ["read_file", "grep", "write_file"],
        ...     [None, "pattern", None],
        ...     "read f.py then write out.txt with primary argument name used for the bash tool",
        ... )
        [None, '"bash"', 'out.txt']
    """
    tool = detect_primary_arg_tool(task)
    if not tool or not names:
        return list(targets)
    out = list(targets)
    while len(out) < len(names):
        out.append(None)
    expected = extract_expected_files(task)
    write_target: Optional[str] = None
    if expected:
        for e in expected:
            if "primary" in e.lower():
                write_target = e
                break
        if write_target is None:
            write_target = expected[0]
    grep_pat = f'"{tool}"'
    for i, n in enumerate(names):
        if n == "grep":
            out[i] = grep_pat
        elif n == "write_file" and write_target:
            out[i] = write_target
    return out[: len(names)]


# Alias historique (imports agent / tests)
force_primary_arg_grep_targets = force_primary_arg_plan_targets


# Tache type y04/y10/z-serie : "read/glob X, then edit_file Y" — le chemin de la
# cible edit/write est celui du read/glob qui le precede. Slot-fill renvoie
# souvent None (anaphore "that file / the first one") ; on reporte la cible.
_PRODUCERS_CARRY = ("read_file", "glob", "write_file")


def carry_previous_path_targets(
    names: List[str],
    targets: List[Optional[str]],
    task: str,
) -> List[Optional[str]]:
    """
    Reporte le chemin d'un producteur (read_file/glob/write_file) vers la cible
    edit_file/write_file suivante quand slot-fill a laisse None.

    Garde-fou deterministe, pure, idempotente, len conserve.
    Ne PAS ecraser quand la tache vise un fichier NEUF different
    (extract_expected_files) : on ne porte la cible que si elle matche un fichier
    attendu ou s'il n'y a aucun fichier attendu extractible.

    Example:
        >>> carry_previous_path_targets(
        ...     ["read_file", "edit_file"],
        ...     ["server.py", None],
        ...     "read server.py, then change the port from 8080 to 3000",
        ... )
        ['server.py', 'server.py']
        >>> carry_previous_path_targets(
        ...     ["read_file", "write_file"],
        ...     ["a.py", None],
        ...     "read a.py, then write b.txt",
        ... )
        ['a.py', None]
    """
    if not names:
        return list(names or [])
    out = list(targets)
    while len(out) < len(names):
        out.append(None)
    expected = extract_expected_files(task)
    expected_basenames = {Path(e).name.lower() for e in expected}
    carried: Optional[str] = None
    for i, name in enumerate(names):
        t = out[i]
        if name in _PRODUCERS_CARRY and t:
            carried = t
        elif name in ("edit_file", "write_file") and t is None and carried:
            carried_base = Path(carried).name.lower()
            # La tache designe un fichier neuf distinct (ex. "write b.txt" apres
            # un read de a.py) : ne pas coller a.py comme cible du write.
            if expected_basenames and carried_base not in expected_basenames:
                continue
            out[i] = carried
    return out[: len(names)]


# ── Garde-fous de plan : prédicats d'intention (purs, avec doctests) ───────────

def _first_clause(task: str) -> str:
    """Texte avant le 1er connecteur/virgule (1re étape de la tâche). Fonction pure."""
    return _STEP_CONNECTOR_RE.split(task or "", maxsplit=1)[0].strip()


def _last_clause(task: str) -> str:
    """Texte après le dernier connecteur/virgule (dernière étape de la tâche)."""
    parts = [p.strip() for p in _STEP_CONNECTOR_RE.split(task or "") if p.strip()]
    return parts[-1] if parts else (task or "")


def detect_edit_intent(task: str) -> bool:
    """Vrai si la tache MODIFIE un fichier existant (edit), pas une creation.

    Fonction pure.
    >>> detect_edit_intent("Open server.py, then change the port to 3000")
    True
    >>> detect_edit_intent("Run the unit tests with pytest")
    False
    """
    return bool(_EDIT_INTENT_RE.search(task or ""))


def detect_read_first(task: str) -> bool:
    """Vrai si la 1re clause OUVRE/LIT un fichier nomme.

    Fonction pure.
    >>> detect_read_first("Inspect nginx.conf first, then bump workers to 2048")
    True
    >>> detect_read_first("Run git status, then open the first modified file")
    False
    """
    first = _first_clause(task).lower()
    if not _READ_VERB_RE.search(first):
        return False
    return bool(
        _FILENAME_RE.search(first) or _BUILD_FILE_RE.search(first)
        or re.search(r"\bfile\b", first, re.I)
    )


def detect_list_first(task: str) -> bool:
    """Vrai si la 1re clause LISTE une categorie de fichiers (glob).

    Fonction pure.
    >>> detect_list_first("Enumerate the .ini configs, read logging.ini")
    True
    >>> detect_list_first("Find the hardcoded API key in the sources")
    False
    """
    first = _first_clause(task).lower()
    if not _LIST_VERB_RE.search(first):
        return False
    if _FILE_CATEGORY_RE.search(first):
        return True
    return bool(re.search(r"\*\*?/|\.env|\.[a-z]{1,8}\b", first))


def detect_search_first(task: str) -> bool:
    """Vrai si la 1re clause cherche une CHAINE (grep), pas des fichiers.

    Fonction pure.
    >>> detect_search_first("Locate every console.log left in production code")
    True
    >>> detect_search_first("Locate the benchmark scripts")
    False
    """
    first = _first_clause(task).lower()
    if not _SEARCH_VERB_RE.search(first):
        return False
    return not _FILE_CATEGORY_RE.search(first)


def detect_final_exec(task: str) -> bool:
    """Vrai si la DERNIERE clause est un exec (ne pas convertir le bash final).

    Fonction pure.
    >>> detect_final_exec("Open the cron file, then reload the scheduler from the shell")
    True
    >>> detect_final_exec("Look at settings.ini, then flip verbose to off")
    False
    """
    return bool(_FINAL_EXEC_RE.search(_last_clause(task)))


def detect_exec_first(task: str) -> bool:
    """Vrai si la 1re clause EXECUTE une commande (le bash de tete est legitime).

    Fonction pure. "make a/the ... file" = creation, PAS un exec.
    >>> detect_exec_first("Run git status, then open the first modified file")
    True
    >>> detect_exec_first("In docker-compose.yml, swap restart: always")
    False
    """
    return bool(_EXEC_FIRST_RE.search(_first_clause(task)))


def detect_verify_usage(task: str) -> bool:
    """Vrai si la tache verifie qu'un nom/module n'est pas deja utilise.

    Fonction pure.
    >>> detect_verify_usage("Add orbit_tracker.py, then verify nothing else uses that name")
    True
    >>> detect_verify_usage("Look at settings.ini, then flip verbose to off")
    False
    """
    return bool(_VERIFY_USAGE_RE.search(task or ""))


# ── Garde-fous de plan : transformations de noms (pures, idempotentes) ─────────

def fix_first_step_bash(names, task):
    """bash en tete -> read_file (lit un fichier) ou glob (liste des fichiers).

    Fonction pure. Ne touche pas les plans < 2 étapes.
    >>> fix_first_step_bash(["bash", "edit_file"],
    ...     "Open server.py, then change the port from 8080 to 3000.")
    ['read_file', 'edit_file']
    >>> fix_first_step_bash(["bash", "bash"],
    ...     "Read Makefile first, then invoke make test.")
    ['read_file', 'bash']
    >>> fix_first_step_bash(["bash", "read_file"],
    ...     "Run git status, then open the first modified file you care about.")
    ['bash', 'read_file']
    """
    if not names or names[0] != "bash" or len(names) < 2:
        return list(names or [])
    if detect_read_first(task):
        return ["read_file", *names[1:]]
    if detect_list_first(task):
        return ["glob", *names[1:]]
    return list(names)


def fix_first_step_grep_to_glob(names, task):
    """grep en tete mais 1re clause liste une categorie de fichiers -> glob (z11).

    Fonction pure. Garde len>=2.
    >>> fix_first_step_grep_to_glob(["grep", "read_file", "bash"],
    ...     "Locate the benchmark scripts, read the io-heavy one, then execute it.")
    ['glob', 'read_file', 'bash']
    >>> fix_first_step_grep_to_glob(["grep", "read_file"],
    ...     "Locate every console.log left in production code, then read the file.")
    ['grep', 'read_file']
    """
    if not names or names[0] != "grep" or len(names) < 2:
        return list(names or [])
    if detect_list_first(task) and not detect_search_first(task):
        return ["glob", *names[1:]]
    return list(names)


def fix_trailing_bash(names, task):
    """Dernier bash -> grep (verify-usage), edit_file (modif) ou retire un parasite.

    Fonction pure.
    >>> fix_trailing_bash(["grep", "read_file", "bash"],
    ...     "Find where the timezone bug lives, read that module, then correct the offset.")
    ['grep', 'read_file', 'edit_file']
    >>> fix_trailing_bash(["glob", "bash"],
    ...     "Find the changelog files, then append an Unreleased section to the newest.")
    ['glob', 'edit_file']
    >>> fix_trailing_bash(["edit_file", "bash"],
    ...     "Look at settings.ini, then flip verbose to off.")
    ['edit_file']
    >>> fix_trailing_bash(["write_file", "bash"],
    ...     "Add a module orbit_tracker.py, then verify nothing else already uses that name.")
    ['write_file', 'grep']
    >>> fix_trailing_bash(["read_file", "bash"],
    ...     "Read Makefile first, then invoke make test.")
    ['read_file', 'bash']
    """
    if not names or names[-1] != "bash":
        return list(names or [])
    out = list(names)
    if detect_verify_usage(task):
        return [*out[:-1], "grep"]
    if detect_edit_intent(task) and not detect_final_exec(task):
        if "edit_file" in out and "write_file" not in out:
            return out[:-1]                  # bash parasite (y18)
        if "edit_file" not in out and "write_file" not in out:
            return [*out[:-1], "edit_file"]  # z02/z06/y26/…
    return out


def fix_write_to_edit(names, task):
    """write_file sur un fichier DECOUVERT + cible anaphorique -> edit_file.

    Fonction pure. Ne convertit PAS une cible neuve nommee (create/write a new file).
    >>> fix_write_to_edit(["glob", "write_file"],
    ...     "Find the .env.example files, then add a DATABASE_URL line to the first one.")
    ['glob', 'edit_file']
    >>> fix_write_to_edit(["write_file", "glob"],
    ...     "Create a new README.md, then verify it exists by listing *.md files.")
    ['write_file', 'glob']
    """
    if "write_file" not in names:
        return list(names or [])
    out = list(names)
    if not any(n in ("glob", "grep", "read_file") for n in out):
        return out
    if not _ANAPHORIC_TARGET_RE.search(task or ""):
        return out
    if _WRITE_NEW_FILE_RE.search(task or ""):
        return out                            # cible neuve nommee -> write_file garde
    for i, n in enumerate(out):
        if n == "write_file":
            out[i] = "edit_file"
            break
    return out


def fix_web_sequence(names, task):
    """brave->fetch, grep+web_fetch -> brave, tronque write apres fetch.

    Fonction pure.
    >>> fix_web_sequence(["brave_search", "read_file"],
    ...     "Search online for duckdb vs sqlite 2026, then open one of the result URLs.")
    ['brave_search', 'web_fetch']
    >>> fix_web_sequence(["grep", "web_fetch"],
    ...     "Search for the official tokio tutorial, then pull down that page.")
    ['brave_search', 'web_fetch']
    >>> fix_web_sequence(["brave_search", "web_fetch", "write_file"],
    ...     "Find the URL of the pnpm migration guide online, then fetch it.")
    ['brave_search', 'web_fetch']
    """
    out = list(names)
    if out[:2] == ["grep", "web_fetch"] and _WEB_INTENT_RE.search(task or ""):
        out[0] = "brave_search"
    if "brave_search" in out:
        i = out.index("brave_search")
        if i + 1 < len(out) and out[i + 1] != "web_fetch" and _WEB_FETCH_INTENT_RE.search(task or ""):
            out[i + 1] = "web_fetch"
    if (
        len(out) >= 2 and out[-2] == "web_fetch" and out[-1] == "write_file"
        and not task_requests_write(task)
    ):
        out = out[:-1]
    return out


def fix_duplicate_read_before_exec(names, task):
    """[read_file, read_file, bash] sur read->edit->exec -> [read, edit, bash].

    Fonction pure.
    >>> fix_duplicate_read_before_exec(["read_file", "read_file", "bash"],
    ...     "Open the cron schedule file, move the nightly job to 02:30, then reload the scheduler.")
    ['read_file', 'edit_file', 'bash']
    """
    if (
        len(names) >= 3 and names[0] == "read_file" and names[1] == "read_file"
        and names[2] == "bash" and detect_edit_intent(task) and detect_final_exec(task)
    ):
        out = list(names)
        out[1] = "edit_file"
        return out
    return list(names or [])


def ensure_discovery_before_edit(names, task, max_len=None):
    """Insere read_file/grep/glob avant le 1er edit_file si aucune decouverte ne precede.

    Fonction pure. max_len plafonne les insertions (anti-sur-longueur).
    >>> ensure_discovery_before_edit(["edit_file"],
    ...     "Inspect nginx.conf first, then bump worker_connections to 2048.", max_len=2)
    ['read_file', 'edit_file']
    >>> ensure_discovery_before_edit(["read_file", "edit_file"],
    ...     "Open server.py, then change the port to 3000.", max_len=2)
    ['read_file', 'edit_file']
    """
    if "edit_file" not in names:
        return list(names or [])
    out = list(names)
    i = out.index("edit_file")
    if any(n in ("read_file", "glob", "grep") for n in out[:i]):
        return out
    if max_len is not None and len(out) >= max_len:
        return out
    if detect_read_first(task):
        return ["read_file", *out]
    if detect_search_first(task):
        return ["grep", *out]
    if detect_list_first(task):
        return ["glob", *out]
    return out


def fix_superfluous_grep_before_read(names, task):
    """grep de tete superflu devant read_file sur une tache de LECTURE (x02).

    Fonction pure. Ne touche pas aux taches search/list (grep legitime) :
    "Search for X, then read" garde grep.

    >>> fix_superfluous_grep_before_read(["grep", "read_file"],
    ...     "Print the source of D:\\\\studio\\\\melody\\\\composer.rb so I can review it.")
    ['read_file']
    >>> fix_superfluous_grep_before_read(["grep", "read_file"],
    ...     "Search for the function parse_invoice, then read the file that defines it.")
    ['grep', 'read_file']
    """
    if len(names) >= 2 and names[0] == "grep" and names[1] == "read_file":
        if detect_read_first(task) and not detect_search_first(task) and not detect_list_first(task):
            return names[1:]
    return list(names or [])


def fix_bash_before_edit(names, task):
    """bash de tete superflu devant edit_file sur une tache de MODIF pure (x08).

    Fonction pure. "Run the linter, then fix" garde son bash (exec_first).

    >>> fix_bash_before_edit(["bash", "edit_file"],
    ...     "In docker-compose.yml, swap restart: always for restart: unless-stopped.")
    ['edit_file']
    >>> fix_bash_before_edit(["bash", "edit_file"],
    ...     "Run the type checker, open the file it flags, then fix the annotation.")
    ['bash', 'edit_file']
    """
    if len(names) >= 2 and names[0] == "bash" and names[1] == "edit_file":
        if detect_edit_intent(task) and not detect_exec_first(task):
            return names[1:]
    return list(names or [])


def fix_bash_write_to_write(names, task):
    """[bash, write_file] sur une creation pure -> [write_file] (x07).

    Fonction pure. Ne convertit pas si la 1re clause exec (run ... puis write).

    >>> fix_bash_write_to_write(["bash", "write_file"],
    ...     "Make a fresh file called deploy_notes.txt with the word pending inside.")
    ['write_file']
    >>> fix_bash_write_to_write(["bash", "write_file"],
    ...     "Run the build, then write the summary to out.txt")
    ['bash', 'write_file']
    """
    if names == ["bash", "write_file"]:
        if detect_create_file(task) and not detect_exec_first(task):
            return ["write_file"]
    return list(names or [])


def normalize_plan_names(names, task, max_len=None):
    """Garde-fous deterministes de niveau NOMS (pure, idempotente, ne leve jamais).

    Applique les corrections dans un ordre fixe. max_len plafonne les INSERTIONS ;
    les conversions/retraits sont libres. Retourne toujours une liste.

    Exemples (echecs reels du probe v2b, n=100) :
        >>> normalize_plan_names(["bash", "edit_file"],
        ...     "Open server.py, then change the port from 8080 to 3000.")
        ['read_file', 'edit_file']
        >>> normalize_plan_names(["edit_file"],
        ...     "Inspect nginx.conf first, then bump worker_connections to 2048.", max_len=2)
        ['read_file', 'edit_file']
        >>> normalize_plan_names(["glob", "bash"],
        ...     "Find the changelog files, then append an Unreleased section to the newest.")
        ['glob', 'edit_file']
        >>> normalize_plan_names(["bash", "bash"],
        ...     "Read Makefile first, then invoke make test.")
        ['read_file', 'bash']
        >>> normalize_plan_names(["write_file", "bash"],
        ...     "Add a module orbit_tracker.py, then verify nothing else already uses that name.")
        ['write_file', 'grep']
        >>> normalize_plan_names(["glob", "write_file"],
        ...     "Find the .env.example files, then add a DATABASE_URL line to the first one.")
        ['glob', 'edit_file']
        >>> normalize_plan_names(["brave_search", "read_file"],
        ...     "Search online for duckdb vs sqlite 2026, then open one of the result URLs.")
        ['brave_search', 'web_fetch']
        >>> x = ["bash", "read_file", "bash"]
        >>> once = normalize_plan_names(x,
        ...     "Open the cron schedule file, move the job, then reload the scheduler.")
        >>> normalize_plan_names(once,
        ...     "Open the cron schedule file, move the job, then reload the scheduler.") == once
        True
    """
    if not names:
        return list(names or [])
    out = list(names)
    out = fix_first_step_bash(out, task)
    out = fix_first_step_grep_to_glob(out, task)
    out = fix_superfluous_grep_before_read(out, task)
    out = fix_web_sequence(out, task)
    out = fix_write_to_edit(out, task)
    out = fix_trailing_bash(out, task)
    out = fix_duplicate_read_before_exec(out, task)
    out = ensure_discovery_before_edit(out, task, max_len=max_len)
    out = fix_bash_before_edit(out, task)
    out = fix_bash_write_to_write(out, task)
    return out


# Tache type p0a : "Search ... for the function estimate_task_steps, then write … basename"
_FIND_SYMBOL_RE = re.compile(
    r"\b(?:for|of)\s+(?:the\s+)?(?P<kind>function|class|method|def)\s+(?P<name>\w+)",
    re.IGNORECASE,
)
_FIND_SYMBOL_LOOSE_RE = re.compile(
    r"\b(?:search|find|locate|grep)\b.{0,80}?\b(?P<kind>function|class|method)\s+(?P<name>\w+)",
    re.IGNORECASE,
)


def detect_find_symbol(task: str) -> Optional[tuple]:
    """
    Si la tache demande de trouver une function/class, retourne (kind, name).

    Fonction pure. kind normalise : 'function' | 'class' | 'method'.
    >>> detect_find_symbol(
    ...     "Search for the function estimate_task_steps, then write found.txt"
    ... )
    ('function', 'estimate_task_steps')
    >>> detect_find_symbol("write hello.txt") is None
    True
    """
    if not task:
        return None
    m = _FIND_SYMBOL_RE.search(task) or _FIND_SYMBOL_LOOSE_RE.search(task)
    if not m:
        return None
    kind = m.group("kind").lower()
    if kind == "def":
        kind = "function"
    return kind, m.group("name")


def find_symbol_grep_pattern(task: str) -> Optional[str]:
    """
    Pattern grep precis pour le symbole (def/class), sans reveler le fichier.

    Fonction pure.
    >>> find_symbol_grep_pattern("Search for the function foo, write x.txt")
    'def foo'
    """
    hit = detect_find_symbol(task)
    if not hit:
        return None
    kind, name = hit
    if kind == "class":
        return f"class {name}"
    return f"def {name}"


def find_symbol_lookup_hint(task: str) -> Optional[str]:
    """Hint : greper def/class Name, ecrire basename du fichier DEFINISSANT."""
    pat = find_symbol_grep_pattern(task)
    if not pat:
        return None
    return (
        f"LOOKUP RULE: call grep with pattern {pat!r} (codebase search). "
        f"If several files match, read the one that DEFINES the symbol "
        f"(def/class line), not a caller/import/test. "
        f"Then write_file with EXACTLY that file's basename only "
        f"(shape: name.py — one token, no path, no sentence, no quotes)."
    )


def force_find_symbol_plan_targets(
    names: List[str],
    targets: List[Optional[str]],
    task: str,
) -> List[Optional[str]]:
    """
    Tache find-symbol (p0a) : forcer grep→`def Name` et write→fichier attendu.

    Ne touche pas les taches primary-arg. Fonction pure.
    >>> force_find_symbol_plan_targets(
    ...     ["grep", "write_file"],
    ...     ["_p0_scratch/found.txt", None],
    ...     "Search for the function estimate_task_steps, then write found.txt",
    ... )
    ['def estimate_task_steps', 'found.txt']
    """
    if detect_primary_arg_tool(task):
        return list(targets)
    pat = find_symbol_grep_pattern(task)
    if not pat or not names:
        return list(targets)
    out = list(targets)
    while len(out) < len(names):
        out.append(None)
    expected = extract_expected_files(task)
    write_target = expected[0] if expected else None
    for i, n in enumerate(names):
        if n == "grep":
            out[i] = pat
        elif n == "write_file" and write_target:
            out[i] = write_target
    return out[: len(names)]


def extract_expected_commands(task: str) -> List[str]:
    """
    Extrait les commandes shell dont exit 0 est exigé (post-condition).

    Actif si la tâche mentionne « exit 0 / exit code 0 » OU exprime une intention
    de TEST naturelle (« run pytest », « tests pass », « unittest »…). Dans ce
    second cas, un fichier de test nommé (test_*.py / *_test.py) donne la
    commande `python -m pytest <fichier>` (exit 0 = les tests passent) — la gate
    n'exige plus le jargon « exit 0 ». Fonction pure.

    Example:
        >>> extract_expected_commands("add tests in test_x.py then run pytest")
        ['python -m pytest test_x.py']
        >>> extract_expected_commands("just read config.json")
        []
    """
    if not task or not task.strip():
        return []
    has_exit_zero = bool(_EXIT_ZERO_RE.search(task))
    has_test_intent = bool(_RUN_TESTS_RE.search(task))
    if not (has_exit_zero or has_test_intent):
        return []

    found: List[str] = []
    seen = set()

    def _add(cmd: str) -> None:
        cmd = cmd.strip()
        if cmd and cmd not in seen:
            seen.add(cmd)
            found.append(cmd)

    # Intention de test + fichier de test nommé → lancer la suite (exit 0 = pass).
    pytest_files = set()
    if has_test_intent:
        for match in _TESTFILE_RE.finditer(task):
            fname = match.group(1)
            pytest_files.add(fname)
            _add(f"python -m pytest {fname}")

    for line in task.splitlines():
        segments = re.split(r"[;\n]", line)
        for segment in segments:
            seg_lower = segment.lower()
            has_exec = any(v in seg_lower for v in _EXEC_VERBS)
            has_python = "python" in seg_lower
            if not has_exec and not has_python:
                continue
            for match in _PYTHON_CMD_RE.finditer(segment):
                script = match.group(1) or match.group(2)
                if script in pytest_files:   # déjà couvert via pytest
                    continue
                _add(f"python {script}")
            if has_exec:
                for match in _SCRIPT_CMD_RE.finditer(segment):
                    script = match.group(1)
                    if script in pytest_files:
                        continue
                    if script.lower().endswith(".py"):
                        _add(f"python {script}")
                    elif script.lower().endswith(".ps1"):
                        _add(f"powershell -NoProfile -File {script}")
    return found


# ── Vérification disque ───────────────────────────────────────────────────────

def verify_files(expected: List[str], cwd: Optional[str] = None) -> List[str]:
    """
    Retourne les fichiers attendus qui MANQUENT (ou sont VIDES) sur le disque.

    Durci contre la tromperie au fichier vide (red-team) : un fichier qui existe
    mais dont la taille est 0 est traité comme manquant — créer "result.txt
    contenant 42" puis le laisser vide n'est pas une réussite. verify n'est plus
    seulement "existence-only".

    Les chemins relatifs sont résolus par rapport à cwd (ou au répertoire
    courant). Fonction quasi-pure : lit l'état du disque, n'écrit rien.

    Args:
        expected: Fichiers attendus (de extract_expected_files)
        cwd:      Répertoire de base pour les chemins relatifs

    Returns:
        Sous-liste des fichiers absents ou vides (vide si tous présents+remplis).

    Example:
        >>> verify_files([], cwd="/tmp")
        []
    """
    if not expected:
        return []

    base = Path(cwd) if cwd else Path.cwd()
    missing: List[str] = []
    for fname in expected:
        path = Path(fname)
        if not path.is_absolute():
            path = base / fname
        # Absent, OU présent mais vide (fichier de 0 octet) → non satisfait.
        if not path.exists() or (path.is_file() and path.stat().st_size == 0):
            missing.append(fname)
    return missing


def invalid_content_files(expected: List[str], cwd: Optional[str] = None) -> List[str]:
    """
    Retourne les fichiers qui EXISTENT mais dont le CONTENU est invalide.

    Va au-delà de l'existence (verify_files) : un `.py` qui ne compile pas ou un
    `.json` qui ne parse pas a bien été écrit, mais n'est PAS un livrable valide.
    Doit être appelée INDÉPENDAMMENT de filter_missing (qui blanchirait un fichier
    dès qu'un write_file a réussi — or un .py cassé a justement été écrit).

    Seuls `.py` (compilation) et `.json` (parsing) sont validés ; les autres
    extensions et les fichiers absents/vides sont ignorés (gérés par verify_files).
    Fonction quasi-pure : lit le disque, n'écrit rien.

    Args:
        expected: Fichiers attendus.
        cwd:      Répertoire de base pour les chemins relatifs.

    Returns:
        Sous-liste des fichiers présents mais au contenu invalide.

    Example:
        >>> invalid_content_files([], cwd="/tmp")
        []
    """
    if not expected:
        return []

    base = Path(cwd) if cwd else Path.cwd()
    invalid: List[str] = []
    for fname in expected:
        path = Path(fname)
        if not path.is_absolute():
            path = base / fname
        if not (path.is_file() and path.stat().st_size > 0):
            continue  # absence/vide → géré par verify_files, pas ici
        lower = fname.lower()
        if not lower.endswith((".py", ".json")):
            continue  # autres extensions (média, binaire…) : non validées ici
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeDecodeError):
            invalid.append(fname)  # un .py/.json illisible n'est pas un livrable
            continue
        if lower.endswith(".py"):
            try:
                compile(text, str(path), "exec")
            except SyntaxError:
                invalid.append(fname)
        else:  # .json
            try:
                json.loads(text)
            except json.JSONDecodeError:
                invalid.append(fname)
    return invalid


def content_challenge(invalid: List[str]) -> str:
    """
    Relance forcée quand un fichier existe mais a un contenu invalide.

    Fonction pure.

    Example:
        >>> "does not compile" in content_challenge(["a.py"]).lower() or \
            "not valid" in content_challenge(["a.py"]).lower()
        True
    """
    files = ", ".join(invalid)
    return (
        f"The file(s) exist but their CONTENT is not valid: {files}. "
        f"A Python file that does not compile or a JSON that does not parse is "
        f"NOT a deliverable. Fix the content so it is syntactically valid, then continue."
    )


_ONE_WORD_RE = re.compile(r"\bone\s+word\b", re.IGNORECASE)
_BASENAME_ONLY_RE = re.compile(
    r"\bbasename\s+only\b|\bfilename\s*\(\s*basename|\bbasename\s+of\b",
    re.IGNORECASE,
)
_BASENAME_PY_RE = re.compile(r"^[A-Za-z_][\w.-]*\.py$")


def is_primary_arg_key_as_value(text: str, task: str) -> bool:
    """
    True si le contenu ecrit est la CLE outil (ex. bash) au lieu de la VALUE mappee.

    Fonction pure. Ne revele pas la bonne reponse.
    >>> is_primary_arg_key_as_value(
    ...     "bash",
    ...     "write x.txt with the primary argument name used for the bash tool",
    ... )
    True
    >>> is_primary_arg_key_as_value(
    ...     "other",
    ...     "write x.txt with the primary argument name used for the bash tool",
    ... )
    False
    """
    tool = detect_primary_arg_tool(task)
    if not tool or not text:
        return False
    return text.strip().lower() == tool


def needs_basename_constraint(task: str) -> bool:
    """
    True si la tache exige un basename de fichier (ex. p0a).

    Fonction pure.
    >>> needs_basename_constraint(
    ...     "write found.txt with exactly the filename (basename only) that defines it"
    ... )
    True
    >>> needs_basename_constraint("write hello.txt")
    False
    """
    if not task:
        return False
    if _BASENAME_ONLY_RE.search(task):
        return True
    return detect_find_symbol(task) is not None and "filename" in task.lower()


def is_valid_basename_py(text: str) -> bool:
    """
    True si le texte est un basename Python simple (un token, *.py, pas de chemin).

    Fonction pure.
    >>> is_valid_basename_py("nodus_planner.py")
    True
    >>> is_valid_basename_py("Found 10 steps")
    False
    >>> is_valid_basename_py("src/foo.py")
    False
    """
    t = (text or "").strip().strip('"').strip("'")
    if not t or len(t.split()) != 1:
        return False
    if "/" in t or "\\" in t:
        return False
    return bool(_BASENAME_PY_RE.match(t))


def constraint_invalid_files(
    expected: List[str],
    task: str,
    cwd: Optional[str] = None,
) -> List[str]:
    """
    Fichiers presents dont le contenu viole une contrainte EXPLICITE de la tache.

    - « one word » → exactement un token
    - tache primary-arg → refuse si le contenu = la CLE outil (ex. bash)
    - basename / find-symbol → refuse si pas un `*.py` basename seul

    Fonction quasi-pure.
    """
    if not expected or not task:
        return []
    need_one_word = bool(_ONE_WORD_RE.search(task))
    tool = detect_primary_arg_tool(task)
    need_basename = needs_basename_constraint(task)
    if not need_one_word and not tool and not need_basename:
        return []
    base = Path(cwd) if cwd else Path.cwd()
    bad: List[str] = []
    for fname in expected:
        path = Path(fname)
        if not path.is_absolute():
            path = base / fname
        if not (path.is_file() and path.stat().st_size > 0):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if need_basename and not is_valid_basename_py(text):
            bad.append(fname)
            continue
        if need_one_word and len(text.split()) != 1:
            bad.append(fname)
            continue
        if is_primary_arg_key_as_value(text, task):
            bad.append(fname)
    return bad


def constraint_challenge(invalid: List[str], task: str = "") -> str:
    """Relance quand le contenu viole une contrainte de la tache (ex. one word)."""
    files = ", ".join(invalid)
    hint = ""
    tool = detect_primary_arg_tool(task or "")
    if needs_basename_constraint(task or ""):
        hint = (
            " The task requires EXACTLY the defining file's basename as one token "
            "(example shape: name.py — no path, no folder, no sentence, no quotes). "
            "Write ONLY that basename from the file that DEFINES the symbol."
        )
    elif tool:
        hint = (
            f" You wrote the PRIMARY_ARG dict KEY `{tool}`. "
            f"Write ONLY the one-word VALUE mapped to `{tool}` "
            f"(right-hand side of that entry), not the key itself."
        )
    elif _ONE_WORD_RE.search(task or ""):
        hint = (
            " The task requires EXACTLY one word (no spaces, no quotes, no sentence). "
            "Re-read the source file for the primary argument name, then write ONLY that word."
        )
    return (
        f"POST-CONDITION FAILED — file(s) exist but violate the task content rule: {files}."
        f"{hint} Call write_file again with the correct content NOW."
    )


class ReadPathTracker:
    """Bloque les re-lectures du même fichier en régime cloud."""

    def __init__(self, cwd: Optional[str] = None, enabled: bool = True):
        self._paths = ObservedFileFilter(cwd)
        self._read: set[str] = set()
        self.enabled = enabled

    def check_duplicate_read(self, args: Dict) -> Optional[str]:
        if not self.enabled:
            return None
        raw = args.get("file_path") or args.get("path") or args.get("target_file")
        resolved = self._paths.resolve_path(raw)
        if resolved and resolved in self._read:
            return raw or resolved
        return None

    def note_successful_read(self, args: Dict) -> None:
        raw = args.get("file_path") or args.get("path") or args.get("target_file")
        resolved = self._paths.resolve_path(raw)
        if resolved:
            self._read.add(resolved)


class ObservedFileFilter:
    """
    Filtre les faux « fichiers manquants » après qu'un read_file/write_file/edit_file
    a prouvé l'existence (y compris chemins tronqués type Users\\admin\\...\\file.py).
    """

    def __init__(self, cwd: Optional[str] = None):
        self._cwd = cwd
        self.observed: set[str] = set()

    def resolve_path(self, path_value: Optional[str]) -> Optional[str]:
        if not path_value:
            return None
        try:
            p = Path(path_value)
            if not p.is_absolute() and self._cwd:
                p = Path(self._cwd) / p
            return str(p.expanduser().resolve()).lower()
        except (OSError, ValueError, RuntimeError):
            return None

    def note_tool_success(self, tool_name: str, args: Dict) -> None:
        if tool_name not in ("read_file", "write_file", "edit_file"):
            return
        # write vide ≠ livrable (verify_files traite size 0 comme missing) —
        # ne pas blanchir le filtre, sinon VERIFY saute apres un write "".
        if tool_name == "write_file":
            content = args.get("content", "")
            if not isinstance(content, str) or not content.strip():
                return
        raw_path = (
            args.get("file_path")
            or args.get("path")
            or args.get("target_file")
        )
        resolved = self.resolve_path(raw_path)
        if resolved:
            self.observed.add(resolved)

    def filter_missing(self, missing: List[str]) -> List[str]:
        return [fname for fname in missing if not self._was_observed(fname)]

    def _was_observed(self, fname: str) -> bool:
        resolved = self.resolve_path(fname)
        if resolved and resolved in self.observed:
            return True
        normalized = fname.replace("/", "\\").lower().lstrip("\\")
        return any(path.endswith(normalized) for path in self.observed)


def verify_commands(commands: List[str], cwd: Optional[str] = None) -> List[str]:
    """
    Exécute les commandes attendues ; retourne celles dont exit != 0.

    Ré-exécution réelle (post-condition), comme verify_files sur disque.
    """
    if not commands:
        return []

    failed: List[str] = []
    for cmd in commands:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd or None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            failed.append(cmd)
    return failed


def execution_challenge(failed_commands: List[str]) -> str:
    """Relance quand une commande exigée n'a pas exit 0."""
    cmds = ", ".join(failed_commands)
    return (
        f"The task requires exit 0 but this command failed (non-zero exit): {cmds}. "
        f"Fix the code, then run it with bash and prove exit 0 before claiming done."
    )


def sibling_unexpected_files(
    missing: List[str],
    expected: List[str],
    cwd: Optional[str] = None,
) -> List[str]:
    """
    Fichiers presents dans le meme dossier qu'un manquant, mais hors expected.

    Utile pour le challenge : "tu as cree X.py mais il fallait found.txt".
    Fonction pure (lecture disque seulement). Deduplique, chemins relatifs a cwd
    si possible.
    """
    if not missing:
        return []
    base = Path(cwd).expanduser().resolve() if cwd else Path.cwd().resolve()
    expected_resolved: set[str] = set()
    for e in expected:
        try:
            expected_resolved.add(str((base / e).expanduser().resolve()).lower())
        except (OSError, ValueError, RuntimeError):
            continue

    found: List[str] = []
    seen: set[str] = set()
    for m in missing:
        try:
            parent = (base / m).expanduser().resolve().parent
        except (OSError, ValueError, RuntimeError):
            continue
        if not parent.is_dir():
            continue
        try:
            children = list(parent.iterdir())
        except OSError:
            continue
        for p in children:
            if not p.is_file():
                continue
            try:
                rp = str(p.resolve()).lower()
            except (OSError, ValueError, RuntimeError):
                continue
            if rp in expected_resolved or rp in seen:
                continue
            seen.add(rp)
            try:
                found.append(str(p.relative_to(base)).replace("\\", "/"))
            except ValueError:
                found.append(p.name)
    return found


def verification_challenge(
    missing: List[str],
    unexpected_siblings: Optional[List[str]] = None,
) -> str:
    """
    Construit le message de relance quand des fichiers attendus manquent.

    Directif : chemins EXACTS, interdit bash/echo et les noms inventes.
    unexpected_siblings : fichiers deja crees au mauvais nom (meme dossier).

    Example:
        >>> "result.txt" in verification_challenge(["result.txt"])
        True
        >>> "EXACTLY" in verification_challenge(["a.txt"])
        True
    """
    lines = [
        "POST-CONDITION FAILED — required file(s) still missing.",
        "Create EACH of these paths EXACTLY (character-for-character) with write_file:",
    ]
    for i, f in enumerate(missing, 1):
        lines.append(f"  {i}. file_path = {f!r}")
    lines += [
        "Rules (mandatory):",
        "- Use the write_file tool only (NOT bash, NOT echo, NOT redirection).",
        "- file_path must match the string above EXACTLY — do not invent another name.",
        "- Prefer the relative path string above (as written). "
        "Do NOT invent prefixes like _C: / _Cp0_ / doubled folders.",
        "- Put the content the task asked for.",
    ]
    if unexpected_siblings:
        wrong = ", ".join(repr(x) for x in unexpected_siblings)
        lines.append(
            f"WRONG files already present nearby (ignore/do not count them as done): {wrong}."
        )
    lines.append("Call write_file NOW for every missing path, then continue.")
    return "\n".join(lines)

