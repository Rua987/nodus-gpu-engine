"""Resolve the code a failing test exercises, so the fix agent can read it.

The code agent kept writing patches for modules it had never seen. Live,
Nemotron produced a diff for ``nodus_tools.py`` quoting

    dirname, filename = os.path.split(tail)
    filename = '_' + filename

Neither line is in that file. The function it meant is at line 1200 and looks
nothing like that - the model invented plausible code because the traceback
named only the *test* file, never the module under test.

This walks the other way: parse the test with ``ast``, find the names the
failing test actually calls, follow the test module's imports to a file in the
repo, and pull out those definitions. Static only - nothing is imported or
executed, so a test whose module needs torch is still resolvable.

Everything here is total: it returns a value or an empty one, never raises.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, List, Optional, Tuple

MAX_SYMBOLS = 3
MAX_LINES_PER_SYMBOL = 120


def _parse(path: Path) -> Optional[ast.Module]:
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return None


def _find_test_node(tree: ast.Module, name: str) -> Optional[ast.AST]:
    """The ``def <name>`` anywhere in the module, including inside a class."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def called_names(node: ast.AST) -> List[str]:
    """Names invoked inside ``node``, in first-seen order.

    ``foo(x)`` yields ``foo``; ``mod.foo(x)`` yields ``foo`` too - the import
    map is what decides where it comes from.
    """
    out: List[str] = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        f = sub.func
        name = None
        if isinstance(f, ast.Name):
            name = f.id
        elif isinstance(f, ast.Attribute):
            name = f.attr
        if name and name not in out and not name.startswith("_"):
            out.append(name)
    return out


def import_map(tree: ast.Module) -> Dict[str, str]:
    """``{local name: module}`` for both import forms."""
    out: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for a in node.names:
                out[a.asname or a.name] = node.module
        elif isinstance(node, ast.Import):
            for a in node.names:
                out[a.asname or a.name.split(".")[0]] = a.name
    return out


def module_file(module: str, roots: List[Path]) -> Optional[Path]:
    """The file backing ``module`` under one of ``roots``, if any."""
    rel = module.replace(".", "/")
    for root in roots:
        for cand in (root / f"{rel}.py", root / rel / "__init__.py"):
            try:
                if cand.is_file():
                    return cand
            except OSError:
                continue
    return None


def definition(tree: ast.Module, name: str) -> Optional[Tuple[int, int]]:
    """``(start, end)`` 1-based line span of ``def``/``class`` ``name``."""
    for node in ast.walk(tree):
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and node.name == name):
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            end = getattr(node, "end_lineno", None) or node.lineno
            return start, end
    return None


def sources_under_test(test_file: Path, test_name: str, repo_root: Path,
                       roots: List[Path]) -> List[Tuple[str, int, str]]:
    """``[(repo-relative path, start line, source)]`` for what the test calls.

    Empty when the test, its imports or the definitions cannot be found - the
    caller simply has nothing extra to show the model.
    """
    tree = _parse(test_file)
    if tree is None:
        return []
    node = _find_test_node(tree, test_name)
    if node is None:
        return []

    imports = import_map(tree)
    out: List[Tuple[str, int, str]] = []
    seen = set()
    for name in called_names(node):
        module = imports.get(name)
        if not module:
            continue
        f = module_file(module, roots)
        if f is None:
            continue
        mod_tree = _parse(f)
        if mod_tree is None:
            continue
        span = definition(mod_tree, name)
        if span is None:
            continue
        try:
            rel = f.resolve().relative_to(repo_root).as_posix()
        except (OSError, ValueError):
            continue
        if (rel, span[0]) in seen:
            continue
        seen.add((rel, span[0]))

        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        start, end = span[0], min(span[1], span[0] + MAX_LINES_PER_SYMBOL - 1)
        body = "\n".join(f"{i:5d}| {lines[i - 1]}"
                         for i in range(start, min(end, len(lines)) + 1))
        out.append((rel, start, body))
        if len(out) >= MAX_SYMBOLS:
            break
    return out


def render(entries: List[Tuple[str, int, str]]) -> str:
    """The block that goes in the prompt, or ''."""
    if not entries:
        return ""
    parts = [f"{rel} line {start}, the code under test, exact text:\n{body}"
             for rel, start, body in entries]
    return "\n\n".join(parts)
