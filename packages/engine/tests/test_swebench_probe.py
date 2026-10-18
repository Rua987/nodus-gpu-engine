"""bench/swebench_probe.py helpers, and the committed probe says what docs/REAL_BUGS.md says."""
import json
from pathlib import Path

from bench import swebench_probe as sp

EVIDENCE = Path(__file__).resolve().parents[1] / "evidence"


def test_image_name_follows_the_swebench_registry():
    assert sp.image_for("pallets__flask-5014") == \
        "swebench/sweb.eval.x86_64.pallets_1776_flask-5014:latest"


def test_test_files_come_from_the_test_patch():
    patch = "--- a/tests/t.py\n+++ b/tests/t.py\n@@ -1 +1 @@\n-a\n+b\n"
    assert sp.test_files(patch) == ["tests/t.py"]


def test_outcomes_read_pytest_rA_summary_lines():
    out = "PASSED tests/t.py::test_a\nFAILED tests/t.py::test_b - AssertionError\nERROR x::y\n"
    assert sp.outcomes(out) == {"tests/t.py::test_a": "PASSED", "tests/t.py::test_b": "FAILED",
                                "x::y": "ERROR"}


def test_committed_probe_ran_two_real_tasks_end_to_end():
    reports = [json.loads(l) for l in (EVIDENCE / "swebench_probe_20261018.txt").read_text(
        encoding="utf-8").splitlines() if l.startswith("{")]
    assert [r["instance"] for r in reports] == ["pallets__flask-5014", "psf__requests-5414"]
    for r in reports:
        assert r["ok"] and r["base_commit_ok"]
        assert r["f2p_failed_before"] == r["f2p_passed_after"] == r["f2p"]
        assert r["p2p_passed_after"] == r["p2p"]
