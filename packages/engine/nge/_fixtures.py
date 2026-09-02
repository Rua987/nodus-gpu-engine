"""Deterministic failure catalogue for the mock path.

Single source of truth shared by:
  - ``nge.sandbox.mock`` — emits ``FAILED <test> - <error>`` lines, and decides
    whether a patched re-run passes
  - ``nge.orchestrator`` — in ``--mock`` the "model" returns the canned patch here

``fixable`` mimics reality: some failures a code agent can patch and verify,
some need a human. The patches are short but shaped like real unified diffs.
"""
from __future__ import annotations

from typing import Optional

FAILURES = [
    {
        "test": "tests/test_nodus_planner.py::test_plan_order",
        "error": "AssertionError: plan names out of order",
        "fixable": True,
        "patch": (
            "--- a/nodus_planner.py\n"
            "+++ b/nodus_planner.py\n"
            "@@ def parse_plan(text):\n"
            "-    return names\n"
            "+    return sorted(names, key=STEP_ORDER.index)\n"
        ),
    },
    {
        "test": "tests/test_nodus_tools.py::test_edit_file_unique",
        "error": "ValueError: old_string not unique",
        "fixable": True,
        "patch": (
            "--- a/nodus_tools.py\n"
            "+++ b/nodus_tools.py\n"
            "@@ def edit_file(path, old, new, replace_all=False):\n"
            "-    if src.count(old) != 1:\n"
            "-        raise ValueError('old_string not unique')\n"
            "+    if src.count(old) != 1 and not replace_all:\n"
            "+        raise ValueError('old_string not unique; pass replace_all=True')\n"
        ),
    },
    {
        "test": "tests/test_nodus_verify.py::test_carry_path",
        "error": "AssertionError: expected [None, 'server.py']",
        "fixable": True,
        "patch": (
            "--- a/nodus_verify.py\n"
            "+++ b/nodus_verify.py\n"
            "@@ def carry_previous_path_targets(names, targets):\n"
            "-    return targets\n"
            "+    for i in range(1, len(targets)):\n"
            "+        if targets[i] is None and names[i] in _EDIT_TOOLS:\n"
            "+            targets[i] = targets[i - 1]\n"
            "+    return targets\n"
        ),
    },
    {
        "test": "tests/test_nodus_gcloud.py::test_upload_mock",
        "error": "KeyError: 'GCLOUD_BUCKET'",
        "fixable": False,   # needs an env/config decision a human must make
        "patch": None,
    },
    {
        "test": "tests/test_nodus_memory.py::test_roundtrip",
        "error": "AssertionError: memory entry missing",
        "fixable": False,   # flaky ordering — agent can't safely auto-fix
        "patch": None,
    },
]

_BY_TEST = {f["test"]: f for f in FAILURES}
_BY_KW = {f["test"].split("::")[-1]: f for f in FAILURES}


def failure_by_test(name: str) -> Optional[dict]:
    return _BY_TEST.get(name) or _BY_KW.get(name.split("::")[-1])


def canned_patch(name: str) -> Optional[str]:
    f = failure_by_test(name)
    return f["patch"] if f else None


def is_fixable(name: str) -> bool:
    f = failure_by_test(name)
    return bool(f and f["fixable"])
