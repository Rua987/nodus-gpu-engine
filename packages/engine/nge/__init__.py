"""
Nodus-GPU Engine (nge)
======================

Agentic engineering platform (Nebius track):

    Nodus (324M local planner)  ->  ordered tool names        [brain / DSL]
    Nemotron via Nebius AI Studio ->  orchestration + slot-fill [inference]
    GPU fleet (Nebius cloud)      ->  provision / monitor / free [infrastructure]
    Token Factory Sandboxes      ->  isolated execution         [execution]

Isolated integration: the vendored packages ``packages/nodus`` and
``packages/gpu-agents`` are NOT modified. All new code lives here. Importing
``nge`` puts the sibling packages on ``sys.path`` so ``import nodus_agent`` etc.
work from anywhere.
"""
from __future__ import annotations

import sys
from pathlib import Path

__version__ = "0.1.0"

# packages/engine/nge/__init__.py  -> parents[2] == packages/
_PACKAGES = Path(__file__).resolve().parents[2]

for _sib in ("nodus", "gpu-agents"):
    _p = _PACKAGES / _sib
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

REPO_ROOT = _PACKAGES.parent
PACKAGES_DIR = _PACKAGES
