#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ TEMPLE IAM - NODUS TOOLS
⚡ Port des outils Claude Code (src/tools/) en Python pur pour Ollama
🔥 BashTool · FileReadTool · FileEditTool · FileWriteTool · GlobTool · GrepTool · WebFetchTool · BraveSearchTool

Copyright © 2024 Temple IAM - All Rights Reserved

Architecture:
    Chaque outil = une fonction pure tool_<name>() + son schéma JSON Schema.
    dispatch_tool() fait le routage nom → fonction.
    TOOL_SCHEMAS = liste OpenAI-compatible injectée dans /api/chat Ollama.
"""

import ipaddress
import os
import platform
import re
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urljoin, urlunparse

import requests

# ── GCS (Google Cloud Storage) — livraison d'artefacts (mock-first, léger) ────
from nodus_gcloud import gcs_from_env  # noqa: E402

# ── Brave Search — clé API lue depuis .brave_api_key (jamais hardcodée) ───────
_BRAVE_KEY_FILE = Path(__file__).parent / ".brave_api_key"
BRAVE_API_KEY: Optional[str] = (
    _BRAVE_KEY_FILE.read_text(encoding="utf-8").strip()
    if _BRAVE_KEY_FILE.exists()
    else os.environ.get("BRAVE_SEARCH_API_KEY")
)

# ── Constantes (portées depuis Claude Code limits.ts / file.ts) ───────────────
MAX_OUTPUT_CHARS = 50_000
DEFAULT_TIMEOUT  = 30
MAX_TIMEOUT      = 120
# Scripts CE×Godot MCP (~60–90s) : éviter timeout agent bash à 30s
_CE_LONG_RUN_MARKERS = ("ce_godot_coins_write", "ce_write_coins.py", "e2e_redteam20.py")
MAX_FILE_BYTES   = 256 * 1024   # 256 KB
MAX_FILE_LINES   = 2_000
MAX_GREP_RESULTS = 250
MAX_GLOB_RESULTS = 500
MAX_FETCH_CHARS  = 20_000
MAX_FETCH_REDIRECTS = 5               # plafond de sauts de redirection (anti-SSRF + anti-boucle)
MAX_FETCH_BYTES  = 5 * 1024 * 1024   # 5 MB : plafond DUR de téléchargement (anti-DoS)


# ── Résultat d'outil ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ToolResult:
    """Résultat d'un appel d'outil — succès ou échec. IMMUTABLE.

    frozen=True : personne ne peut muter success/output/error après création
    (évite corruption silencieuse dans la boucle ReAct / redaction). Pour
    « modifier », créer une nouvelle instance (ex. `_redact_result`).
    """
    success: bool
    output: str
    error: Optional[str] = None

    def to_str(self) -> str:
        if self.success:
            return self.output or "(no output)"
        return f"Error: {self.error}"


# ── Rédaction de secrets ────────────────────────────────────────────────────
# Défense en profondeur : tout résultat d'outil (fichier, stdout, page web)
# passe par `dispatch_tool`. Avant qu'il n'atteigne le contexte du modèle ou
# la mémoire persistante, on caviarde les secrets ÉVIDENTS. On vise la
# PRÉCISION : des préfixes/formats reconnaissables, pas des heuristiques
# d'entropie qui mutileraient du code ou de la prose normale.
_REDACTED = "[REDACTED-SECRET]"

# Chaque pattern capture le secret dans le groupe nommé "secret" (le reste —
# préfixe, nom de clé, guillemets — est préservé pour rester lisible).
_SECRET_PATTERNS = (
    # OpenRouter / OpenAI-style: sk-or-v1-..., sk-...
    re.compile(r"(?P<secret>sk-(?:or-)?(?:v\d-)?[A-Za-z0-9]{20,})"),
    # AWS access key id: AKIA / ASIA + 16 alphanum maj
    re.compile(r"(?P<secret>(?:AKIA|ASIA)[0-9A-Z]{16})"),
    # GitHub tokens: ghp_, gho_, ghu_, ghs_, ghr_, github_pat_
    re.compile(r"(?P<secret>gh[opusr]_[A-Za-z0-9]{20,})"),
    re.compile(r"(?P<secret>github_pat_[A-Za-z0-9_]{20,})"),
    # Slack tokens: xoxb-, xoxp-, xoxa-, xoxr-
    re.compile(r"(?P<secret>xox[baprs]-[A-Za-z0-9-]{10,})"),
    # Google API key: AIza + 35 chars
    re.compile(r"(?P<secret>AIza[0-9A-Za-z_-]{35})"),
    # Bearer <token> dans un header Authorization
    re.compile(r"(?i:bearer)\s+(?P<secret>[A-Za-z0-9._\-]{20,})"),
    # api_key=... / token=... / secret=... / password=... (= ou :, guillemets opt.)
    re.compile(
        r"(?i:(?:api[_-]?key|secret|token|password|passwd|access[_-]?token))"
        r"\s*[=:]\s*['\"]?(?P<secret>[A-Za-z0-9._\-/+]{12,})['\"]?"
    ),
    # Clé privée PEM (bloc entier)
    re.compile(
        r"(?P<secret>-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
        r".*?-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----)",
        re.DOTALL,
    ),
)


def redact_secrets(text: str) -> str:
    """Caviarde les secrets évidents dans un texte.

    Fonction pure. Remplace seulement la portion sensible (le groupe `secret`)
    par un marqueur, en préservant le contexte autour (nom de clé, préfixe
    `Bearer`, guillemets) pour que la sortie reste lisible et que les chemins
    de code/prose normaux ne soient pas mutilés.

    Args:
        text: Texte à inspecter (sortie d'outil : fichier, stdout, page web).

    Returns:
        Le texte avec chaque secret reconnu remplacé par ``[REDACTED-SECRET]``.
        Inchangé si aucun secret n'est détecté.

    Example:
        >>> redact_secrets("export KEY=sk-or-v1-" + "a" * 32)
        'export KEY=[REDACTED-SECRET]'
        >>> redact_secrets("def add(a, b): return a + b")
        'def add(a, b): return a + b'
    """
    if not text:
        return text

    def _sub(match: "re.Match") -> str:
        full = match.group(0)
        secret = match.group("secret")
        # Remplace uniquement la sous-chaîne secrète à l'intérieur du match.
        return full.replace(secret, _REDACTED)

    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(_sub, text)
    return text


def _redact_result(result: ToolResult) -> ToolResult:
    """Renvoie une copie de `result` dont output et error sont caviardés.

    Fonction pure. Point d'application unique de :func:`redact_secrets` sur les
    deux champs textuels d'un :class:`ToolResult`, juste avant qu'il ne quitte
    `dispatch_tool` vers le contexte du modèle.

    Args:
        result: Le résultat d'outil brut.

    Returns:
        Un nouveau :class:`ToolResult` avec les secrets caviardés.
    """
    return ToolResult(
        success=result.success,
        output=redact_secrets(result.output),
        error=redact_secrets(result.error) if result.error is not None else None,
    )


# ── 1. Bash Tool ──────────────────────────────────────────────────────────────

# Commandes Unix sans équivalent direct en PowerShell → hint pour le LLM
_UNIX_HINTS: dict = {
    r"\bwc\s+-l\b":    "Hint: wc -l fails on Windows. Use: python -c \"print(open('FILE').read().count(chr(10)))\"",
    r"\bfind\s+\.":    "Hint: find fails on Windows. Use the glob TOOL: glob(pattern='**/*.py')",
    r"\btail\b":       "Hint: tail fails on Windows. Use the read_file TOOL instead.",
    r"\bls\s+-":       "Hint: ls with flags fails on Windows. Use the glob TOOL.",
    r"\bgrep\s+-r\b":  "Hint: grep -r fails on Windows. Use the grep TOOL: grep(pattern='...', path='DIR')",
    r"\bgrep\s+-l\b":  "Hint: grep -l fails on Windows. Use the grep TOOL: grep(pattern='...', path='DIR')",
    r"\bgsutil\b":     "Hint: gsutil is not available here. To verify an uploaded file, use the read_file TOOL (it is in the task workspace) or trust the gcs_upload success message.",
    r"\bgcloud\s+storage\b": "Hint: gcloud storage is not available here (CLI not installed). To verify an uploaded file, use the read_file TOOL (it is in the task workspace) or trust the gcs_upload success message.",
    r"\s&&\s":         "Hint: && is invalid in PowerShell 5.x. Use ';' or run python with an absolute path.",
}

_BASH_PREFIX_RE = re.compile(r"^bash\s+", re.IGNORECASE)
_CD_D_RE = re.compile(r"\bcd\s+/d\s+", re.IGNORECASE)
_AND_AND_RE = re.compile(r"\s&&\s+")
# '||' = exécuter la suite SI la précédente a échoué. On capture le reste de la
# ligne (group 1) pour l'envelopper dans `if (-not $?) { ... }`.
_OR_OR_RE = re.compile(r"\s\|\|\s+(.+)$")
# python|py + script.py (relative path only)
_PY_SCRIPT_RE = re.compile(
    r"\b(python|py)\s+((?:[\w.-]+[/\\])*[\w.-]+\.py)\b",
    re.IGNORECASE,
)

# ── Denylist de commandes catastrophiques (garde-fou CODE, pas prompt) ─────────
# Red-team : le system prompt interdit déjà force-push & co, mais un prompt
# n'est qu'une suggestion. Ces patterns sont refusés AU NIVEAU DU CODE, peu
# importe ce que le modèle (ou une mémoire/leçon empoisonnée) lui souffle.
# On vise le CATASTROPHIQUE et IRRÉVERSIBLE, pas le `rm -rf ./build` légitime.
_DESTRUCTIVE_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        # rm -rf (ordre des flags libre) ciblant racine / home / glob nu / cwd.
        # La terminaison accepte fin, séparateur, commentaire (#) ou un flag qui
        # suit (- / --no-preserve-root) : sinon `rm -rf / --no-preserve-root` ou
        # `rm -rf /  # commentaire` contournaient la garde (round 19, GAP durci).
        r"\brm\s+-[a-z]*\b[^|;&]*\s(/|~|/\*|\*|\.|\$HOME|\$\{HOME\})\s*($|[|;&#]|-)",
        r"\bgit\s+push\b[^|;&]*(--force\b|\s-f\b)",          # push --force / -f
        r"\bgit\s+reset\s+--hard\b",                          # perte de travail
        r"\bgit\s+clean\s+-[a-z]*f[a-z]*d|\bgit\s+clean\s+-[a-z]*d[a-z]*f",
        r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",          # fork bomb
        r"\bmkfs\.",                                          # formatage FS
        r"\bdd\b[^|;&]*\bof=/dev/",                           # écrasement disque
        r">\s*/dev/(sd|hd|nvme)",                             # write sur device
        r"\bchmod\s+-R\s+0*777\s+/",                          # ouverture racine
        r"\bformat\s+[a-zA-Z]:",                              # format C: (Windows)
        r"\bRemove-Item\b[^|;&]*-Recurse\b[^|;&]*-Force\b",   # rm -rf PowerShell
    )
)


def _is_destructive(command: str) -> bool:
    """
    Détecte une commande manifestement destructrice et irréversible.

    Fonction pure. Vise les opérations catastrophiques (effacement racine,
    formatage, force-push, reset --hard, fork bomb) — PAS les nettoyages
    locaux légitimes comme `rm -rf ./build`.

    Args:
        command: Commande shell à inspecter

    Returns:
        True si la commande correspond à un pattern destructeur connu.

    Example:
        >>> _is_destructive("rm -rf /")
        True
        >>> _is_destructive("rm -rf ./build")
        False
        >>> _is_destructive("git push --force origin main")
        True
        >>> _is_destructive("pytest -q")
        False
    """
    return any(rx.search(command) for rx in _DESTRUCTIVE_PATTERNS)


def _normalize_command(command: str) -> str:
    """
    Normalise une commande pour Windows.

    Strip le préfixe 'bash ' que les LLMs ajoutent comme méta-label
    (ex: 'bash grep -c ...' → 'grep -c ...').

    Fonction pure — ne modifie aucun état.

    Args:
        command: Commande brute

    Returns:
        Commande nettoyée

    Example:
        >>> _normalize_command("bash grep -c def file.py")
        'grep -c def file.py'
        >>> _normalize_command("python -m pytest")
        'python -m pytest'
    """
    return _BASH_PREFIX_RE.sub("", command)


def _rewrite_windows_powershell(command: str, cwd: Optional[str] = None) -> str:
    """
    Réécrit les idiomes bash/CMD invalides sous PowerShell 5.x (Windows).

    Problème observé en prod : les LLMs envoient ``cd X && python script.py``
    (~64% des rounds gaspillés). ``&&`` n'existe pas en PS 5.x → ParserError
    exit 1, même quand le script Python est correct.

    Transformations (fonction pure) :
        - ``bash cmd`` → ``cmd``
        - ``cd /d PATH`` → ``Set-Location PATH``  (syntaxe CMD, pas PS)
        - ``a && b`` → ``a; b``
        - ``a || b`` → ``a; if (-not $?) { b }``  (approximation portable)
        - ``cd CWD; rest`` → ``rest`` si *cwd* correspond au répertoire tâche
        - ``python foo.py`` → ``python C:\\abs\\foo.py`` si *cwd* est défini

    Args:
        command: Commande brute (souvent style bash)
        cwd:     Répertoire de travail de la tâche NODUS

    Returns:
        Commande exécutable sous ``powershell -NonInteractive -Command``
    """
    command = _normalize_command(command)
    command = _CD_D_RE.sub("Set-Location ", command)
    command = _AND_AND_RE.sub("; ", command)

    def _or_repl(match: re.Match) -> str:
        return f"; if (-not $?) {{ {match.group(1).strip()} }}"

    command = _OR_OR_RE.sub(_or_repl, command)

    if not cwd:
        return command

    try:
        base = Path(cwd).expanduser().resolve()
    except (OSError, ValueError):
        return command

    cd_then_rest = re.match(
        r"^(?:Set-Location|cd)\s+(.+?)\s*;\s*(.+)$",
        command,
        re.IGNORECASE | re.DOTALL,
    )
    if cd_then_rest:
        loc = cd_then_rest.group(1).strip().strip("\"'")
        try:
            if Path(loc).expanduser().resolve() == base:
                command = cd_then_rest.group(2).strip()
        except (OSError, ValueError):
            pass

    def _abs_py(match: re.Match) -> str:
        launcher, script = match.group(1), match.group(2)
        # Garde défensive : _PY_SCRIPT_RE ne capture jamais un chemin absolu
        # (ni lecteur 'C:\\' ni UNC '\\\\'), donc cette branche est inatteignable
        # en l'état — conservée au cas où le regex s'élargirait.
        if re.match(r"^[A-Za-z]:\\|^\\\\", script):
            return match.group(0)  # pragma: no cover
        full = str((base / script.replace("/", os.sep)).resolve())
        return f"{launcher} {full}"

    return _PY_SCRIPT_RE.sub(_abs_py, command)


def _unix_hint(command: str) -> str:
    """
    Retourne un hint si la commande est un pattern Unix non portable.

    Args:
        command: Commande à inspecter

    Returns:
        Hint string (vide si aucun pattern trouvé)
    """
    for pattern, hint in _UNIX_HINTS.items():
        if re.search(pattern, command):
            return hint
    return ""


def tool_bash(command: str, timeout: int = DEFAULT_TIMEOUT,
              cwd: Optional[str] = None) -> ToolResult:
    """
    Exécute une commande shell.
    PowerShell -NonInteractive sur Windows, bash -c ailleurs.

    Sur Windows, le préfixe 'bash ' est automatiquement retiré de la commande
    (les LLMs l'utilisent comme méta-label ; ce n'est pas une vraie commande).

    Args:
        command: Commande à exécuter
        timeout: Timeout en secondes (max 120)
        cwd:     Répertoire de travail de la commande (défaut: cwd du process).
                 Garantit que les chemins relatifs ciblent le dossier de la tâche.
    """
    timeout = min(max(1, timeout), MAX_TIMEOUT)
    if timeout == DEFAULT_TIMEOUT and any(m in command for m in _CE_LONG_RUN_MARKERS):
        timeout = MAX_TIMEOUT

    # Garde-fou CODE : refuser les commandes catastrophiques avant exécution.
    if _is_destructive(command):
        return ToolResult(
            success=False, output="",
            error=("Blocked: this command is destructive/irreversible "
                   "(matches the safety denylist). Refused at the code level. "
                   "If you truly need it, the human must run it manually."),
        )

    try:
        if platform.system() == "Windows":
            command = _rewrite_windows_powershell(command, cwd=cwd)
            cmd = ["powershell", "-NonInteractive", "-Command", command]
        else:
            cmd = ["bash", "-c", command]

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
        )

        combined = proc.stdout or ""
        if proc.stderr and proc.stderr.strip():
            combined += f"\n[stderr]\n{proc.stderr}"
        combined = combined[:MAX_OUTPUT_CHARS]

        if proc.returncode != 0:
            hint = _unix_hint(command)
            error_msg = f"Exit code {proc.returncode}"
            if hint:
                error_msg += f"\n{hint}"
            return ToolResult(success=False, output=combined, error=error_msg)
        return ToolResult(success=True, output=combined or "(no output)")

    except subprocess.TimeoutExpired:
        return ToolResult(success=False, output="", error=f"Timeout after {timeout}s")
    except FileNotFoundError as e:
        return ToolResult(success=False, output="", error=f"Shell not found: {e}")
    except Exception as e:
        return ToolResult(success=False, output="", error=str(e))


# ── 2. Read File Tool ─────────────────────────────────────────────────────────

def tool_read_file(
    file_path: str,
    offset: int = 0,
    limit: Optional[int] = None,
) -> ToolResult:
    """
    Lit un fichier avec numéros de ligne (format cat -n, 1-indexé).

    Args:
        file_path: Chemin absolu du fichier
        offset:    Ligne de départ (0 = début)
        limit:     Nombre de lignes à lire (None = tout)
    """
    try:
        path = Path(file_path).expanduser().resolve()

        if not path.exists():
            similar = _find_similar(path)
            hint = f"\nDid you mean: {similar}" if similar else ""
            return ToolResult(success=False, output="",
                              error=f"File not found: {file_path}{hint}")

        if path.is_dir():
            entries = sorted(p.name for p in path.iterdir())[:100]
            return ToolResult(success=True, output="\n".join(entries))

        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            return ToolResult(success=False, output="",
                              error=(f"File too large ({size:,} bytes, "
                                     f"max {MAX_FILE_BYTES:,}). Use offset+limit."))

        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()

        start = max(0, offset)
        end = len(lines) if limit is None else min(start + limit, len(lines))
        chunk = lines[start:end][:MAX_FILE_LINES]

        numbered = "\n".join(f"{start + i + 1}\t{ln}" for i, ln in enumerate(chunk))
        return ToolResult(success=True, output=numbered)

    except Exception as e:
        return ToolResult(success=False, output="", error=str(e))


def _find_similar(path: Path) -> Optional[str]:
    parent = path.parent
    if not parent.is_dir():
        return None
    name = path.name.lower()
    for p in parent.iterdir():
        if p.name.lower() == name or p.stem.lower() == Path(name).stem:
            return str(p)
    return None


# ── 3. Edit File Tool ─────────────────────────────────────────────────────────

def tool_edit_file(
    file_path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> ToolResult:
    """
    Remplace une chaîne exacte dans un fichier.
    Port de FileEditTool/utils.ts findActualString + normalizeQuotes.

    Args:
        file_path:   Chemin absolu
        old_string:  Texte exact à remplacer
        new_string:  Texte de remplacement
        replace_all: Remplacer toutes les occurrences
    """
    try:
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            return ToolResult(success=False, output="",
                              error=f"File not found: {file_path}")

        content = path.read_text(encoding="utf-8", errors="replace")
        actual = _find_actual_string(content, old_string)

        if actual is None:
            return ToolResult(success=False, output="",
                              error=f"old_string not found in {file_path}")

        count = content.count(actual)
        if count > 1 and not replace_all:
            return ToolResult(
                success=False, output="",
                error=(f"old_string found {count} times. "
                       "Use replace_all=true or add more context to make it unique."),
            )

        if replace_all:
            new_content = content.replace(actual, new_string)
            replaced = count
        else:
            new_content = content.replace(actual, new_string, 1)
            replaced = 1

        path.write_text(new_content, encoding="utf-8")
        return ToolResult(success=True,
                          output=f"Edited {file_path}: {replaced} occurrence(s) replaced")

    except Exception as e:
        return ToolResult(success=False, output="", error=str(e))


def _normalize_quotes(s: str) -> str:
    return s.replace("‘", "'").replace("’", "'") \
             .replace("“", '"').replace("”", '"')


def _find_actual_string(content: str, search: str) -> Optional[str]:
    if search in content:
        return search
    norm = _normalize_quotes(search)
    if norm != search and norm in content:
        return norm
    return None


# ── 4. Write File Tool ────────────────────────────────────────────────────────

def tool_write_file(file_path: str, content: str) -> ToolResult:
    """
    Crée ou écrase un fichier.

    Args:
        file_path: Chemin absolu
        content:   Contenu à écrire
    """
    try:
        path = Path(file_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        lines = content.count("\n") + 1
        return ToolResult(success=True,
                          output=f"Written {file_path} ({lines} lines, {len(content):,} chars)")
    except Exception as e:
        return ToolResult(success=False, output="", error=str(e))


# ── 5. Glob Tool ──────────────────────────────────────────────────────────────

def tool_glob(pattern: str, path: Optional[str] = None) -> ToolResult:
    """
    Trouve des fichiers par pattern glob, triés par date de modification.

    Args:
        pattern: Pattern glob (ex: "**/*.py")
        path:    Répertoire de base (défaut: cwd)
    """
    try:
        _SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv", ".mypy_cache"}
        base = Path(path).resolve() if path else Path.cwd()
        matches = sorted(
            (
                p for p in base.glob(pattern)
                if p.is_file()
                and not any(part in _SKIP_DIRS for part in p.parts)
                and p.suffix not in {".pyc", ".pyo"}
            ),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        files = [str(p.relative_to(base)) for p in matches]

        if not files:
            return ToolResult(success=True, output="(no files found)")

        output = "\n".join(files[:MAX_GLOB_RESULTS])
        if len(files) > MAX_GLOB_RESULTS:
            output += f"\n... ({len(files) - MAX_GLOB_RESULTS} more)"
        return ToolResult(success=True, output=output)

    except Exception as e:
        return ToolResult(success=False, output="", error=str(e))


# ── 6. Grep Tool ──────────────────────────────────────────────────────────────

def tool_grep(
    pattern: str,
    path: Optional[str] = None,
    glob: Optional[str] = None,
    output_mode: str = "content",
    case_insensitive: bool = True,
) -> ToolResult:
    """
    Cherche un pattern regex dans les fichiers.

    Args:
        pattern:          Pattern regex
        path:             Fichier ou répertoire (défaut: cwd)
        glob:             Filtre fichiers (ex: "*.py")
        output_mode:      "content" = lignes | "files_with_matches" = chemins
        case_insensitive: Insensible à la casse (défaut True)
    """
    try:
        flags = re.IGNORECASE if case_insensitive else 0
        regex = re.compile(pattern, flags)

        _SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv", ".mypy_cache"}

        base = Path(path).resolve() if path else Path.cwd()
        if base.is_file():
            files_to_scan = [base]
        else:
            fp = glob or "**/*"
            files_to_scan = sorted(
                p for p in base.glob(fp)
                if p.is_file()
                and not any(part in _SKIP_DIRS for part in p.parts)
                and p.suffix not in {".pyc", ".pyo"}
            )

        results: list = []
        matched: list = []

        for fpath in files_to_scan[:2000]:
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            rel = str(fpath.relative_to(base)) if base.is_dir() else str(fpath)

            if output_mode == "files_with_matches":
                if regex.search(text):
                    matched.append(rel)
            else:
                for i, line in enumerate(text.splitlines(), 1):
                    if regex.search(line):
                        results.append(f"{rel}:{i}: {line}")
                        if len(results) >= MAX_GREP_RESULTS:
                            break
                if len(results) >= MAX_GREP_RESULTS:
                    break

        if output_mode == "files_with_matches":
            return ToolResult(success=True,
                              output="\n".join(matched) if matched else "(no matches)")
        return ToolResult(success=True,
                          output="\n".join(results) if results else "(no matches)")

    except re.error as e:
        return ToolResult(success=False, output="", error=f"Invalid regex: {e}")
    except Exception as e:
        return ToolResult(success=False, output="", error=str(e))


# ── 7. Web Fetch Tool ─────────────────────────────────────────────────────────

_ALLOWED_SCHEMES = ("http", "https")


def _is_non_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


def _validate_and_pin_url(url: str) -> tuple[bool, str, Optional[str], Optional[str]]:
    """
    Anti-SSRF : valide l'URL et épingle le hostname à l'IP résolue (anti DNS-rebind).

    Une seule résolution DNS : la requête HTTP utilise l'IP littérale + en-tête Host,
    pour que requests ne puisse pas re-résoudre vers une cible interne entre-temps.

    Returns:
        (blocked, reason, pinned_url, host_header)
    """
    try:
        parsed = urlparse(url)
    except (ValueError, TypeError):
        return True, "unparseable URL", None, None

    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        return True, f"scheme '{scheme or '?'}' not allowed (only http/https)", None, None

    host = parsed.hostname
    if not host:
        return True, "missing host", None, None

    try:
        literal = ipaddress.ip_address(host)
        if _is_non_public_ip(literal):
            return True, (
                f"non-public address {host} — SSRF blocked (internal/metadata target)"
            ), None, None
        return False, "", url, host
    except ValueError:
        pass

    port = parsed.port
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return True, f"cannot resolve host '{host}'", None, None

    chosen_ip: Optional[str] = None
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if _is_non_public_ip(ip):
            return True, (
                f"host '{host}' resolves to non-public address {ip_str} "
                f"— SSRF blocked (internal/metadata target)"
            ), None, None
        if chosen_ip is None:
            chosen_ip = ip_str

    if chosen_ip is None:
        return True, f"cannot resolve host '{host}'", None, None

    ip_lit = (
        f"[{chosen_ip}]" if ipaddress.ip_address(chosen_ip).version == 6 else chosen_ip
    )
    netloc = f"{ip_lit}:{port}" if port else ip_lit
    pinned = urlunparse((
        scheme, netloc, parsed.path or "", parsed.params, parsed.query, parsed.fragment,
    ))
    return False, "", pinned, host


def _is_blocked_url(url: str) -> tuple:
    """
    Anti-SSRF : décide si une URL doit être refusée AVANT toute requête.

    Red-team (proposé par autoresearch) : sans garde, web_fetch peut être dirigé
    vers des cibles INTERNES — loopback, réseaux privés, et surtout l'endpoint
    de métadonnées cloud 169.254.169.254 (vol de credentials IAM). On résout
    l'hôte et on refuse toute IP non publique. Fonction quasi-pure (DNS en
    lecture, n'écrit rien).

    Args:
        url: URL demandée

    Returns:
        (blocked: bool, reason: str). reason vide si autorisée.

    Example:
        >>> _is_blocked_url("ftp://example.com")[0]
        True
        >>> _is_blocked_url("file:///etc/passwd")[0]
        True
    """
    blocked, reason, _, _ = _validate_and_pin_url(url)
    return blocked, reason


def tool_web_fetch(url: str, max_chars: int = MAX_FETCH_CHARS) -> ToolResult:
    """
    Récupère le contenu texte d'une URL.

    Args:
        url:       URL à récupérer
        max_chars: Nombre max de caractères
    """
    blocked, reason, pinned, host_hdr = _validate_and_pin_url(url)
    if blocked:
        return ToolResult(success=False, output="", error=f"Blocked URL: {reason}")

    try:
        current_url = url
        current_pinned = pinned
        current_host = host_hdr
        for _hop in range(MAX_FETCH_REDIRECTS + 1):
            headers = {
                "User-Agent": "NODUS-Agent/1.0 (Temple IAM)",
                "Host": current_host,
            }
            resp = requests.get(
                current_pinned,
                timeout=15,
                headers=headers,
                allow_redirects=False,
                stream=True,
            )
            if resp.is_redirect or resp.is_permanent_redirect:
                location = resp.headers.get("Location", "")
                resp.close()
                if not location:
                    return ToolResult(success=False, output="",
                                      error="Redirect without Location header")
                next_url = urljoin(current_url, location)
                blocked, reason, next_pinned, next_host = _validate_and_pin_url(next_url)
                if blocked:
                    return ToolResult(
                        success=False, output="",
                        error=f"Blocked redirect: {reason}")
                current_url = next_url
                current_pinned = next_pinned
                current_host = next_host
                continue
            break
        else:
            return ToolResult(success=False, output="",
                              error=f"Too many redirects (>{MAX_FETCH_REDIRECTS})")
        resp.raise_for_status()

        ct = resp.headers.get("content-type", "")

        # Lecture BORNÉE (red-team anti-DoS) : on ne charge JAMAIS plus de
        # MAX_FETCH_BYTES en mémoire, même si le serveur ment sur Content-Length
        # ou stream à l'infini. On s'arrête dès le plafond atteint.
        chunks: list = []
        total = 0
        truncated_bytes = False
        for chunk in resp.iter_content(chunk_size=8192):
            if not chunk:
                continue
            chunks.append(chunk)
            total += len(chunk)
            if total >= MAX_FETCH_BYTES:
                truncated_bytes = True
                break
        resp.close()
        raw = b"".join(chunks)

        if any(t in ct for t in ("text", "json", "xml")):
            text = raw.decode("utf-8", errors="replace")
            if len(text) > max_chars:
                suffix = "+" if truncated_bytes else ""
                text = text[:max_chars] + f"\n... (truncated, {total:,}{suffix} bytes downloaded)"
        else:
            suffix = "+" if truncated_bytes else ""
            text = f"(binary content, {total:,}{suffix} bytes, type: {ct})"

        return ToolResult(success=True, output=text)

    except requests.HTTPError as e:
        return ToolResult(success=False, output="",
                          error=f"HTTP {e.response.status_code}: {e}")
    except requests.Timeout:
        return ToolResult(success=False, output="", error="Timeout (15s)")
    except requests.RequestException as e:
        return ToolResult(success=False, output="", error=str(e))
    except Exception as e:
        return ToolResult(success=False, output="", error=str(e))


# ── 8. Brave Search Tool ─────────────────────────────────────────────────────

MAX_SEARCH_RESULTS = 10

def tool_brave_search(query: str, count: int = 5, api_key: Optional[str] = None) -> ToolResult:
    """
    Recherche web via l'API Brave Search.

    Args:
        query:   Requête de recherche
        count:   Nombre de résultats (1-10, défaut 5)
        api_key: Clé API Brave (utilise BRAVE_API_KEY par défaut)
    """
    key = api_key or BRAVE_API_KEY
    if not key:
        return ToolResult(
            success=False, output="",
            error="Brave Search API key manquante — créez .brave_api_key ou définissez BRAVE_SEARCH_API_KEY",
        )

    count = max(1, min(count, MAX_SEARCH_RESULTS))

    try:
        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": key,
            },
            params={"q": query, "count": count},
            timeout=15,
        )
        resp.raise_for_status()

        data = resp.json()
        results = data.get("web", {}).get("results", [])

        if not results:
            return ToolResult(success=True, output="(no results)")

        lines = []
        for i, r in enumerate(results, 1):
            title       = r.get("title", "(no title)")
            url         = r.get("url", "")
            description = r.get("description", "")
            lines.append(f"{i}. {title}\n   {url}\n   {description}")

        return ToolResult(success=True, output="\n\n".join(lines))

    except requests.HTTPError as e:
        return ToolResult(success=False, output="",
                          error=f"HTTP {e.response.status_code}: {e}")
    except requests.Timeout:
        return ToolResult(success=False, output="", error="Timeout (15s)")
    except requests.RequestException as e:
        return ToolResult(success=False, output="", error=str(e))
    except Exception as e:
        return ToolResult(success=False, output="", error=str(e))


# ── 9. GCS Upload Tool (livraison d'artefacts, mock-first) ────────────────────

def tool_gcs_upload(
    local_path: Optional[str] = None,
    destination: Optional[str] = None,
    bucket: Optional[str] = None,
    content: Optional[str] = None,
) -> ToolResult:
    """Upload un artefact produit vers Google Cloud Storage.

    Outil de LIVRAISON du harnais (comme l'observabilité Grafana) : le planneur
    324M garde son vocabulaire de 8 outils — c'est l'exécuteur qui dépose le
    produit final via ce capability tool.

    Mock-first : sans creds (`NODUS_GCLOUD` non `real`), retourne une URI
    `gs://…` déterministe sans réseau. Avec `GCLOUD_BUCKET` +
    `GOOGLE_APPLICATION_CREDENTIALS` et `NODUS_GCLOUD=real`, upload réel via le
    SDK officiel `google-cloud-storage`. Jamais fatal : un échec cloud est
    retourné comme ToolResult(success=False), pas une exception.

    Args:
        local_path:  Chemin du fichier local à uploader (ancré par le harnais).
        destination: Chemin objet dans le bucket (ex "production/brief.md").
        bucket:      Bucket cible (défaut : GCLOUD_BUCKET).
        content:     Alternative à local_path : texte à uploader directement.

    Returns:
        ToolResult avec l'URI gs:// en output sur succès.
    """
    with gcs_from_env() as client:
        ok, out = client.upload(
            local_path=local_path, destination=destination,
            bucket=bucket, content=content,
        )
    return ToolResult(success=ok, output=out, error=None if ok else out)


# ── Schémas JSON Schema (OpenAI-compatible pour Ollama /api/chat) ─────────────

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": (
                "Executes a shell command (PowerShell 5.x on Windows) and returns its output. "
                "Prefer read_file/edit_file/glob/grep for file operations. "
                "On Windows: NEVER use '&&' or 'cd /d' — use absolute paths like "
                "'python C:\\\\path\\\\script.py'. cwd is already the task directory. "
                "Use for: git, npm, pytest, pip, python, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The command to execute"},
                    "timeout": {
                        "type": "integer",
                        "description": f"Timeout in seconds (default {DEFAULT_TIMEOUT}, max {MAX_TIMEOUT})",
                        "default": DEFAULT_TIMEOUT,
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Reads a file with line numbers (cat -n format, 1-indexed). "
                "Use offset+limit for large files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the file"},
                    "offset": {
                        "type": "integer",
                        "description": "Starting line (0-indexed, default 0)",
                        "default": 0,
                    },
                    "limit": {"type": "integer", "description": "Number of lines to read (default: all)"},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Exact string replacement in a file. "
                "Read the file first to get the exact text. "
                "Fails if old_string not found or appears multiple times without replace_all."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the file"},
                    "old_string": {"type": "string", "description": "Exact text to replace (must be unique)"},
                    "new_string": {"type": "string", "description": "Replacement text"},
                    "replace_all": {
                        "type": "boolean",
                        "description": "Replace all occurrences (default false)",
                        "default": False,
                    },
                },
                "required": ["file_path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Creates or overwrites a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the file"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["file_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "glob",
            "description": "Find files by glob pattern, sorted by modification time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern (e.g. '**/*.py')"},
                    "path": {"type": "string", "description": "Base directory (default: cwd)"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Search for a regex pattern in file contents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern"},
                    "path": {"type": "string", "description": "File or directory (default: cwd)"},
                    "glob": {"type": "string", "description": "File filter (e.g. '*.py')"},
                    "output_mode": {
                        "type": "string",
                        "enum": ["content", "files_with_matches"],
                        "description": "content=matching lines (default), files_with_matches=file paths only",
                        "default": "content",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetches text content from a URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch"},
                    "max_chars": {
                        "type": "integer",
                        "description": f"Max characters to return (default {MAX_FETCH_CHARS})",
                        "default": MAX_FETCH_CHARS,
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "brave_search",
            "description": (
                "Searches the web via Brave Search API and returns titles, URLs and descriptions. "
                "Use when you need current information not available locally."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "count": {
                        "type": "integer",
                        "description": f"Number of results (1-{MAX_SEARCH_RESULTS}, default 5)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gcs_upload",
            "description": (
                "Uploads a produced asset (file) to Google Cloud Storage and returns the gs:// URI. "
                "Use as the final DELIVERY step after writing the deliverable. "
                "Either local_path (file on disk) or content (text) plus a destination object path. "
                "Runs in deterministic mock mode when no credentials are set (default)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "local_path": {
                        "type": "string",
                        "description": "Absolute path of the local file to upload",
                    },
                    "destination": {
                        "type": "string",
                        "description": "Object path inside the bucket (e.g. 'production/shoot_day_brief.md')",
                    },
                    "bucket": {
                        "type": "string",
                        "description": "Bucket name (default: GCLOUD_BUCKET env)",
                    },
                    "content": {
                        "type": "string",
                        "description": "Alternative to local_path: text to upload directly",
                    },
                },
                "required": ["destination"],
            },
        },
    },
]


# ── Dispatcher ────────────────────────────────────────────────────────────────

def _resolve_file_path(args: dict) -> str:
    """
    Normalise le nom de l'argument chemin de fichier.
    Les LLMs confondent parfois 'path' et 'file_path' — on accepte les deux.
    """
    return args.get("file_path") or args.get("path") or ""


# Garble frequents (qwen3.5 / petits modeles) — preuves p0a/p0b harnais 2026-07-24/25 :
#   "_C:\\Users\\...\\_p0_scratch\\_found.txt"  (underscore avant lettre de lecteur)
#   "_Cp0_scratch/_p0_scratch/x.txt"            (lecteur C fusionne + dossier double)
#   "_CUsers\\admin\\..."                       (lecteur sans ':')
_DRIVE_PREFIX_GARBLE = re.compile(r"^_+([A-Za-z]:)([\\/].+)$")
_ABS_UNIX_GARBLE = re.compile(r"^_+(/.+)$")
_FUSED_DRIVE_P0 = re.compile(r"^_([A-Za-z])(p0_.+)$", re.IGNORECASE)
_MISSING_COLON_DRIVE = re.compile(
    r"^_+([A-Za-z])(Users[\\/].+)$",
    re.IGNORECASE,
)


def repair_llm_file_path(path_str: str, cwd: Optional[str] = None) -> str:
    """
    Repare les chemins absurdes produits par de petits LLM avant ancrage.

    Fonction pure (pas d'IO). Ne cree pas de chemin invente : elle NE fait que
    enlever des prefixes/doublons evidents. Si le chemin est deja sain, inchangé.

    Repairs (dans l'ordre) :
        1. `_C:\\foo` → `C:\\foo` ; `_/tmp/x` → `/tmp/x`
        2. `_CUsers\\…` → `C:\\Users\\…` (lecteur sans ':')
        3. `_Cp0_scratch/...` → `_p0_scratch/...` (lecteur fusionne)
        4. collapse segments consecutifs identiques
        5. basename `_found.txt` → `found.txt` (preserve `__init__.py`)

    Example:
        >>> repair_llm_file_path(r"_C:\\proj\\_p0_scratch\\_found.txt")
        'C:\\\\proj\\\\_p0_scratch\\\\found.txt'
        >>> repair_llm_file_path(r"_CUsers\\admin\\proj\\x.txt").replace("/", "\\\\")
        'C:\\\\Users\\\\admin\\\\proj\\\\x.txt'
        >>> repair_llm_file_path("_Cp0_scratch/_p0_scratch/x.txt")
        '_p0_scratch/x.txt'
        >>> repair_llm_file_path("_p0_scratch/found.txt")
        '_p0_scratch/found.txt'
    """
    if not path_str or not isinstance(path_str, str):
        return path_str
    s = path_str.strip().strip('"').strip("'")
    if not s:
        return s

    m = _DRIVE_PREFIX_GARBLE.match(s)
    if m:
        s = m.group(1) + m.group(2)
    else:
        m = _MISSING_COLON_DRIVE.match(s)
        if m:
            s = f"{m.group(1)}:\\{m.group(2)}"
        else:
            m = _ABS_UNIX_GARBLE.match(s)
            if m:
                s = m.group(1)
            else:
                m = _FUSED_DRIVE_P0.match(s)
                if m:
                    s = "_" + m.group(2)

    s = _collapse_doubled_first_segment(s)
    s = _strip_spurious_basename_underscore(s)
    return s


def coerce_path_to_expected(
    path_str: str,
    expected_files: Optional[list] = None,
    cwd: Optional[str] = None,
) -> str:
    """
    Si le basename (apres repair) correspond a exactement 1 expected manquant,
    force ce chemin attendu (relatif). Sinon retourne le path repare.

    Evite d'ecrire `…/_CUsers/…/primary_arg_bash.txt` quand l'attendu est
    `_p0_scratch/primary_arg_bash.txt`. Fonction quasi-pure (peut lire le disque
    via verify_files si disponible — ici on compare seulement les noms).
    """
    repaired = repair_llm_file_path(path_str, cwd)
    if not expected_files:
        return repaired
    try:
        bn = Path(repaired).name.lower()
    except (OSError, ValueError, RuntimeError):
        return repaired
    alts = {bn}
    if bn.startswith("_") and not bn.startswith("__"):
        alts.add(bn[1:])
    hits = []
    for e in expected_files:
        try:
            en = Path(str(e)).name.lower()
        except (OSError, ValueError, RuntimeError):
            continue
        if en in alts or (en.startswith("_") and en[1:] in alts):
            hits.append(str(e))
    # Dedup preserve order
    uniq: list = []
    seen: set = set()
    for h in hits:
        if h not in seen:
            seen.add(h)
            uniq.append(h)
    if len(uniq) == 1:
        return uniq[0]
    return repaired


def _collapse_doubled_first_segment(path_str: str) -> str:
    """
    Collapse les segments de dossier consecutifs identiques.

    Relatif : `_p0_scratch/_p0_scratch/x.txt` → `_p0_scratch/x.txt`
    Absolu  : `C:\\...\\_p0_scratch\\_p0_scratch\\x.txt` → `...\\_p0_scratch\\x.txt`
    (preuve p0a apres P2/P3 partiel : contenu OK, mauvais nest).
    """
    if not path_str:
        return path_str
    try:
        parts = list(Path(path_str).parts)
    except (OSError, ValueError, RuntimeError):
        return path_str
    if len(parts) < 2:
        return path_str
    collapsed: list[str] = []
    for part in parts:
        if collapsed and part == collapsed[-1]:
            continue
        collapsed.append(part)
    if len(collapsed) == len(parts):
        return path_str
    try:
        return str(Path(*collapsed))
    except (OSError, ValueError, RuntimeError):
        return path_str


def _strip_spurious_basename_underscore(path_str: str) -> str:
    """
    `_p0_scratch/_found.txt` → `_p0_scratch/found.txt`.

    Ne touche pas `__init__.py` ni un dossier final sans extension.
    """
    if not path_str:
        return path_str
    try:
        p = Path(path_str)
    except (OSError, ValueError, RuntimeError):
        return path_str
    name = p.name
    if (
        name.startswith("_")
        and not name.startswith("__")
        and "." in name[1:]
        and name[1:2].isalnum()
    ):
        try:
            return str(p.with_name(name[1:]))
        except (OSError, ValueError, RuntimeError):
            return path_str
    return path_str


def _anchor(path_str: str, cwd: Optional[str]) -> str:
    """
    Ancre un chemin relatif sur le cwd de la tâche.

    Un chemin absolu est renvoyé inchangé. Un chemin relatif est résolu
    contre cwd (s'il est fourni), garantissant que `write_file("result.txt")`
    cible le dossier de la TÂCHE, pas le cwd du process. Fonction pure.

    Args:
        path_str: Chemin (relatif ou absolu)
        cwd:      Répertoire de base de la tâche (ou None)

    Returns:
        Chemin ancré (str). Inchangé si vide, absolu, ou cwd absent.

    Example:
        >>> _anchor("result.txt", "/tmp/task")  # doctest: +SKIP
        '/tmp/task/result.txt'
        >>> _anchor("", "/tmp/task")
        ''
    """
    if not path_str or not cwd:
        return path_str
    p = Path(path_str).expanduser()
    if p.is_absolute():
        return path_str
    return str(Path(cwd) / p)


def _confine(path_str: str, cwd: Optional[str]) -> tuple:
    """
    Ancre un chemin PUIS le confine au dossier de travail (anti-évasion).

    Red-team : un chemin absolu (`/etc/passwd`) ou un `../../escape.txt`
    permettait d'écrire HORS du sandbox de la tâche — l'agent pouvait toucher
    le vrai système. Ici, quand un cwd est fixé, on résout le chemin final et
    on vérifie qu'il reste SOUS cwd. Sinon on refuse.

    Sans cwd (pas de sandbox), comportement inchangé (ancrage simple).
    Fonction quasi-pure : `resolve()` peut toucher le disque mais n'écrit rien.
    Avant ancrage : `repair_llm_file_path` corrige les garbles LLM courants.

    Args:
        path_str: Chemin demandé (relatif ou absolu)
        cwd:      Dossier de travail de la tâche (sandbox) ou None

    Returns:
        (path: str, error: Optional[str]).
        Si error est non-None, l'appel doit être refusé.

    Example:
        >>> _confine("", "/tmp/task")
        ('', None)
    """
    path_str = repair_llm_file_path(path_str, cwd)
    anchored = _anchor(path_str, cwd)
    if not anchored or not cwd:
        return anchored, None
    try:
        base = Path(cwd).expanduser().resolve()
        target = Path(anchored).expanduser().resolve()
    except (OSError, ValueError, RuntimeError) as e:
        return anchored, f"Invalid path {path_str!r}: {e}"
    if target != base and base not in target.parents:
        return anchored, (
            f"Path escapes the working directory: {path_str!r} resolves outside "
            f"{cwd!r}. Refused for safety — write only inside the task directory."
        )
    return str(target), None


_PROTECTED_REFERENCE_FILES = {"mini_pytest.py"}


def _protected_reference_error(path_str: str) -> Optional[str]:
    """
    Verrouille les fichiers de référence du sandbox contre les réécritures
    accidentelles du modèle (ex: VERIFY halluciné sur mini_pytest.py).

    Échappatoire humaine explicite :
        $env:NODUS_ALLOW_REFERENCE_OVERWRITE = "1"
    """
    try:
        path = Path(path_str).expanduser().resolve()
    except (OSError, ValueError, RuntimeError):
        return None
    if path.name not in _PROTECTED_REFERENCE_FILES:
        return None
    if not path.exists():
        return None
    if os.environ.get("NODUS_ALLOW_REFERENCE_OVERWRITE") == "1":
        return None
    return (
        f"Blocked: {path.name} is a protected reference file and already exists. "
        "Do not rewrite it because of VERIFY/refocus confusion. "
        "Set NODUS_ALLOW_REFERENCE_OVERWRITE=1 only for an explicit human-approved edit."
    )


def dispatch_tool(name: str, args: dict, cwd: Optional[str] = None) -> ToolResult:
    """
    Route un appel d'outil vers la fonction Python correspondante.

    Point d'application UNIQUE de la rédaction de secrets : tout résultat
    d'outil traverse cette fonction avant d'atteindre le contexte du modèle
    ou la mémoire persistante. On caviarde donc ici (défense en profondeur),
    indépendamment de l'outil appelé.

    Args:
        name: Nom de l'outil
        args: Arguments (accepte 'path' comme alias de 'file_path')
        cwd:  Répertoire de travail de la tâche. Les chemins relatifs et les
              commandes bash sont ancrés dessus → un fichier "result.txt"
              atterrit dans le dossier de la tâche, pas celui du process.
    """
    return _redact_result(_dispatch_tool(name, args, cwd))


def _dispatch_tool(name: str, args: dict, cwd: Optional[str] = None) -> ToolResult:
    """Routage brut (sans rédaction). Voir :func:`dispatch_tool`."""
    try:
        if name == "bash":
            return tool_bash(args["command"], args.get("timeout", DEFAULT_TIMEOUT), cwd=cwd)

        if name == "read_file":
            fp, err = _confine(_resolve_file_path(args), cwd)
            if not fp:
                return ToolResult(success=False, output="",
                                  error="Missing argument: 'file_path'")
            if err:
                return ToolResult(success=False, output="", error=err)
            return tool_read_file(fp, args.get("offset", 0), args.get("limit"))

        if name == "edit_file":
            fp, err = _confine(_resolve_file_path(args), cwd)
            if not fp:
                return ToolResult(success=False, output="",
                                  error="Missing argument: 'file_path'")
            if err:
                return ToolResult(success=False, output="", error=err)
            protected = _protected_reference_error(fp)
            if protected:
                return ToolResult(success=False, output="", error=protected)
            return tool_edit_file(
                fp, args["old_string"], args["new_string"],
                args.get("replace_all", False),
            )

        if name == "write_file":
            content = args.get("content", "")
            if not isinstance(content, str) or not content.strip():
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        "Refused empty write_file: content must be non-empty. "
                        "Put the exact text the task requires, then call write_file again."
                    ),
                )
            fp, err = _confine(_resolve_file_path(args), cwd)
            if not fp:
                return ToolResult(success=False, output="",
                                  error="Missing argument: 'file_path'")
            if err:
                return ToolResult(success=False, output="", error=err)
            protected = _protected_reference_error(fp)
            if protected:
                return ToolResult(success=False, output="", error=protected)
            return tool_write_file(fp, args["content"])

        if name == "glob":
            gp, err = _confine(args.get("path") or cwd, cwd)
            if err:
                return ToolResult(success=False, output="", error=err)
            return tool_glob(args["pattern"], gp)

        if name == "grep":
            gp, err = _confine(args.get("path") or cwd, cwd)
            if err:
                return ToolResult(success=False, output="", error=err)
            return tool_grep(
                args["pattern"], gp, args.get("glob"),
                args.get("output_mode", "content"),
            )

        if name == "web_fetch":
            return tool_web_fetch(args["url"], args.get("max_chars", MAX_FETCH_CHARS))

        if name == "brave_search":
            return tool_brave_search(args["query"], args.get("count", 5))

        if name == "gcs_upload":
            lp, err = _confine(args.get("local_path") or "", cwd)
            if err:
                return ToolResult(success=False, output="", error=err)
            return tool_gcs_upload(
                local_path=lp or None,
                destination=args.get("destination", ""),
                bucket=args.get("bucket"),
                content=args.get("content"),
            )

        return ToolResult(success=False, output="", error=f"Unknown tool: {name}")

    except KeyError as e:
        return ToolResult(success=False, output="", error=f"Missing argument: {e}")
    except Exception as e:
        return ToolResult(success=False, output="", error=f"Tool error: {e}")
