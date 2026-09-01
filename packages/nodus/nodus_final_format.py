#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Strict final-answer format detection and validation for NODUS.

When a task explicitly demands a machine-parsable final answer (exact token,
PROPOSE: lines only, etc.), the agent loop can reject prose-heavy finals and
force one correction round.
"""

from dataclasses import dataclass
import re
from typing import Optional


MAX_FINAL_FORMAT_RETRIES = 1

_EXACT_PATTERNS = (
    r"final answer must be exactly:\s*(.+)",
    r"reply with exactly:\s*(.+)",
    r"must be exactly:\s*(.+)",
)


@dataclass(frozen=True)
class StrictFinalSpec:
    """Parsed strict final-answer requirement from a task prompt."""
    mode: str  # "exact" | "propose_lines"
    exact: Optional[str] = None
    min_propose: int = 3


def detect_strict_final_spec(task: str) -> Optional[StrictFinalSpec]:
    """
    Detect whether the task demands a strict machine-parsable final answer.

    Returns None when no explicit format constraint is found.
    """
    if not task or not task.strip():
        return None

    low = task.lower()
    for pattern in _EXACT_PATTERNS:
        match = re.search(pattern, task, re.IGNORECASE)
        if match:
            exact = match.group(1).strip().strip("`\"'")
            exact = exact.splitlines()[0].strip()
            if exact:
                return StrictFinalSpec(mode="exact", exact=exact)

    if "propose:" in low and any(
        needle in low
        for needle in (
            "only lines",
            "only parsable",
            "no summary",
            "no prose",
            "final answer must be only",
            "final answer = uniquement",
        )
    ):
        min_propose = 3
        count = re.search(r"minimum\s+(\d+)", task, re.IGNORECASE)
        if count:
            min_propose = int(count.group(1))
        return StrictFinalSpec(mode="propose_lines", min_propose=min_propose)

    return None


def _propose_line_ok(line: str) -> bool:
    stripped = line.strip().lstrip("*#->` \t")
    if not stripped.lower().startswith("propose:"):
        return False
    parts = stripped.split(":", 1)[1].split("|")
    return len(parts) >= 3


def strict_final_ok(text: str, spec: StrictFinalSpec) -> bool:
    """Return True when the assistant final answer matches the strict spec."""
    if not text or not text.strip():
        return False

    if spec.mode == "exact":
        return text.strip() == spec.exact

    if spec.mode == "propose_lines":
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if len(lines) < spec.min_propose:
            return False
        return all(_propose_line_ok(line) for line in lines)

    return True


def strict_final_challenge(spec: StrictFinalSpec) -> str:
    """User-turn relance when the final answer format is wrong."""
    if spec.mode == "exact":
        return (
            f"Your final answer format is invalid. It must be EXACTLY this line "
            f"and nothing else:\n{spec.exact}\n"
            "No markdown, bullets, explanation, or extra text. Reply again now."
        )

    return (
        f"Your final answer format is invalid. Reply with ONLY lines starting "
        f"with PROPOSE: (minimum {spec.min_propose} lines, pipe-separated fields). "
        "No summary, headers, or prose."
    )
