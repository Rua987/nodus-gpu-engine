#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ TEMPLE IAM - NODUS CHAT
⚡ REPL interactif au-dessus de la boucle ReAct NODUS
🔥 Tape une tâche · NODUS l'exécute · garde le contexte · recommence

Copyright © 2024 Temple IAM - All Rights Reserved

Architecture:
    chat_loop()        → boucle REPL (I/O injectable pour les tests)
    parse_input(line)  → ("command", arg) | ("task", text) | ("empty", "")
    Commandes : /exit /quit /help /memory /clear /history

    Le contexte conversationnel est porté par la mémoire persistante
    (.nodus_memory.md) : chaque tâche résolue s'y ajoute, et la suivante
    la recharge. Approche Karpathy : helpers purs + I/O isolée.
"""

import sys
from pathlib import Path
from typing import Callable, Optional, Tuple

# ── Assure l'importabilité ─────────────────────────────────────────────────────
_HERE = Path(__file__).parent.resolve()
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))  # pragma: no cover

from nodus_agent import DEFAULT_MODEL, run_agent  # noqa: E402
from nodus_memory import load_memory, resolve_memory_path  # noqa: E402

# ── Constantes ────────────────────────────────────────────────────────────────
PROMPT        = "nodus> "
EXIT_COMMANDS = {"/exit", "/quit", "/q"}
BANNER = (
    "🏛️  NODUS Chat — agent ReAct interactif\n"
    "Tape une tâche, ou une commande (/help pour la liste). /exit pour quitter.\n"
)


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_input(line: str) -> Tuple[str, str]:
    """
    Classe une ligne d'entrée utilisateur.

    Fonction pure.

    Args:
        line: Ligne brute saisie par l'utilisateur

    Returns:
        Tuple (kind, payload) où kind ∈ {"empty", "command", "task"} :
            - "empty"   : ligne vide → payload ""
            - "command" : commence par "/" → payload = commande en minuscules
            - "task"    : tout le reste → payload = texte strippé

    Example:
        >>> parse_input("   ")
        ('empty', '')
        >>> parse_input("/Help")
        ('command', '/help')
        >>> parse_input("count files")
        ('task', 'count files')
    """
    stripped = line.strip()
    if not stripped:
        return ("empty", "")
    if stripped.startswith("/"):
        return ("command", stripped.lower())
    return ("task", stripped)


def help_text() -> str:
    """
    Retourne le texte d'aide des commandes.

    Returns:
        Texte multi-ligne décrivant les commandes disponibles.
    """
    return (
        "Commandes disponibles :\n"
        "  /help            Affiche cette aide\n"
        "  /memory          Affiche la mémoire persistante actuelle\n"
        "  /clear           Efface l'écran (ANSI)\n"
        "  /history         Alias de /memory\n"
        "  /exit /quit /q   Quitte le chat\n"
        "Tout autre texte est traité comme une tâche pour l'agent.\n"
    )


def format_result(answer: str, tool_calls: int, rounds: int) -> str:
    """
    Formate le résultat d'une tâche pour l'affichage REPL.

    Fonction pure.

    Args:
        answer:     Réponse finale de l'agent
        tool_calls: Nombre d'appels d'outils
        rounds:     Nombre de rounds

    Returns:
        Bloc texte formaté.

    Example:
        >>> "42" in format_result("42", 1, 2)
        True
    """
    return (
        f"\n{answer}\n"
        f"[{tool_calls} tool calls · {rounds} rounds]\n"
    )


# ── Gestion des commandes ─────────────────────────────────────────────────────

def handle_command(
    command: str,
    memory_path: Path,
    output_fn: Callable[[str], None],
) -> bool:
    """
    Exécute une commande REPL.

    Args:
        command:     Commande normalisée (ex: "/help")
        memory_path: Chemin du fichier mémoire (pour /memory)
        output_fn:   Fonction d'affichage

    Returns:
        True si le chat doit continuer, False s'il doit s'arrêter.

    Example:
        >>> handle_command("/exit", Path("x"), lambda s: None)
        False
        >>> handle_command("/help", Path("x"), lambda s: None)
        True
    """
    if command in EXIT_COMMANDS:
        output_fn("👋 À bientôt !")
        return False

    if command == "/help":
        output_fn(help_text())
        return True

    if command in ("/memory", "/history"):
        content = load_memory(memory_path)
        output_fn(content.strip() if content.strip() else "(mémoire vide)")
        return True

    if command == "/clear":
        output_fn("\033[2J\033[H")  # ANSI clear screen + home
        return True

    output_fn(f"Commande inconnue : {command} (tape /help)")
    return True


# ── Boucle REPL ───────────────────────────────────────────────────────────────

def chat_loop(
    cwd: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    verbose: bool = False,
) -> int:
    """
    Boucle REPL interactive de NODUS.

    Chaque tâche réutilise run_agent avec memory=True : le contexte
    conversationnel persiste via .nodus_memory.md.

    I/O injectable (input_fn / output_fn) pour permettre les tests.

    Args:
        cwd:       Répertoire de travail des tâches
        model:     Modèle Ollama
        input_fn:  Fonction de lecture (défaut: input)
        output_fn: Fonction d'écriture (défaut: print)
        verbose:   Mode verbeux de l'agent

    Returns:
        Code de sortie (0 = normal).
    """
    memory_path = resolve_memory_path(cwd)
    output_fn(BANNER)

    while True:
        try:
            line = input_fn(PROMPT)
        except (EOFError, KeyboardInterrupt):
            output_fn("\n👋 À bientôt !")
            return 0

        kind, payload = parse_input(line)

        if kind == "empty":
            continue

        if kind == "command":
            should_continue = handle_command(payload, memory_path, output_fn)
            if not should_continue:
                return 0
            continue

        # kind == "task" → exécute l'agent avec mémoire
        result = run_agent(
            task=payload,
            cwd=cwd,
            model=model,
            verbose=verbose,
            memory=True,
        )
        output_fn(format_result(result.answer, result.tool_calls, result.rounds))


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(
        prog="nodus_chat",
        description="🤖 NODUS Chat — REPL interactif",
    )
    parser.add_argument(
        "--cwd", "-C", default=None,
        help="Répertoire de travail des tâches",
    )
    parser.add_argument(
        "--model", "-m", default=DEFAULT_MODEL,
        help=f"Modèle Ollama (défaut: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Mode verbeux (affiche les appels d'outils)",
    )
    args = parser.parse_args()

    return chat_loop(
        cwd=args.cwd or str(Path.cwd()),
        model=args.model,
        verbose=args.verbose,
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
