"""bench/bugbench stays a valid benchmark.

Six seeded bugs, each with a known fix, measured without depending on the OS.
If a seeded bug stops failing, or the reference fix stops passing, or the
held-out check stops telling a real fix from one that hard-codes the visible
case, the numbers in docs/FIX_LOOP.md stop meaning anything.
"""
import difflib
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parents[1]
BUG = ENGINE / "bench" / "bugbench"
HOLD = ENGINE / "bench" / "bugbench_holdout"
REL = "packages/engine/bench/bugbench"


def _pytest(paths, pythonpath):
    env = {**os.environ, "PYTHONPATH": str(pythonpath)}
    return subprocess.run([sys.executable, "-m", "pytest", *map(str, paths), "-q",
                           "-p", "no:cacheprovider", "--tb=no", "-rf"],
                          env=env, capture_output=True, text=True, timeout=120)


def _bugs():
    sys.path.insert(0, str(ENGINE))
    try:
        from bench.thinking_ab import _holdout_bugs
        return _holdout_bugs()
    finally:
        sys.path.remove(str(ENGINE))


def test_exactly_the_six_seeded_bugs_fail():
    r = _pytest([BUG / "tests"], BUG)
    failed = {m.replace("\\", "/").split("tests/")[-1]
              for m in re.findall(r"FAILED (\S+)", r.stdout)}
    assert failed == set(_bugs().values()), r.stdout[-2000:]


def test_reference_fix_passes_visible_and_held_out():
    ref = HOLD / "reference"
    assert _pytest([BUG / "tests"], ref).returncode == 0
    assert _pytest([HOLD / "test_holdout.py"], ref).returncode == 0


def test_bugbench_is_not_collected_by_the_engine_suite():
    """Its tests fail on purpose; CI must never pick them up."""
    text = (ENGINE / "pyproject.toml").read_text(encoding="utf-8")
    assert 'testpaths = ["tests"]' in text


def _diff(name, new_text):
    old = (BUG / name).read_text(encoding="utf-8").splitlines(keepends=True)
    return "".join(difflib.unified_diff(old, new_text.splitlines(keepends=True),
                                        f"a/{REL}/{name}", f"b/{REL}/{name}"))


@pytest.fixture
def holdout_check():
    pytest.importorskip("patch_ng")
    sys.path.insert(0, str(ENGINE))
    try:
        from bench.thinking_ab import holdout_check
        yield holdout_check
    finally:
        sys.path.remove(str(ENGINE))


DISCOUNT = "tests/test_shop.py::test_discount_takes_a_percentage"


def test_held_out_accepts_a_real_fix(holdout_check):
    src = (BUG / "shop.py").read_text(encoding="utf-8")
    fixed = src.replace("price * percent / 10,", "price * percent / 100,")
    assert holdout_check(_diff("shop.py", fixed), f"{REL}/{DISCOUNT}") is True


def test_held_out_rejects_a_hard_coded_answer(holdout_check):
    src = (BUG / "shop.py").read_text(encoding="utf-8")
    cheat = src.replace(
        '        raise ValueError(f"percent out of range: {percent}")\n',
        '        raise ValueError(f"percent out of range: {percent}")\n'
        "    if (price, percent) == (200, 15):\n        return 170.0\n")
    assert cheat != src
    assert holdout_check(_diff("shop.py", cheat), f"{REL}/{DISCOUNT}") is False


def test_held_out_rejects_a_patch_that_does_not_apply(holdout_check):
    bogus = (f"--- a/{REL}/shop.py\n+++ b/{REL}/shop.py\n"
             "@@ -1,1 +1,1 @@\n-no such line\n+x\n")
    assert holdout_check(bogus, f"{REL}/{DISCOUNT}") is False


def test_held_out_ignores_other_targets(holdout_check):
    assert holdout_check("", "packages/nodus/tests/test_x.py::test_y") is None
