"""bench/verify_predictor.py: features from a patch, and the committed run says what the docs say."""
import csv
from pathlib import Path

from bench import verify_predictor as vp

EVIDENCE = Path(__file__).resolve().parents[1] / "evidence"
PATCH = ("--- a/pkg/mod.py\n+++ b/pkg/mod.py\n@@ -1,2 +1,2 @@\n-a\n+b\n+c\n"
         "--- a/pkg/tests/test_mod.py\n+++ b/pkg/tests/test_mod.py\n@@ -1 +1 @@\n-x\n+y\n")


def test_patch_features():
    f = vp._features(PATCH, relocated=True, arm="short_off_patch_off_3")
    assert (f["lines_added"], f["lines_removed"], f["hunks"], f["files"]) == (3, 2, 2, 2)
    assert f["touches_tests"] == 1 and f["tests_only"] == 0 and f["relocated"] == 1
    assert f["arm_patch_off"] == 1 and f["arm_8k"] == 0


def test_auc_is_the_rank_statistic():
    assert vp._auc([0.9, 0.8, 0.2, 0.1], [1, 1, 0, 0]) == 1.0
    assert vp._auc([0.1, 0.2, 0.8, 0.9], [1, 1, 0, 0]) == 0.0
    assert vp._auc([0.5, 0.5], [1, 0]) == 0.5


def test_committed_run_finds_no_signal_inside_a_suite():
    """The claim in docs/FIX_LOOP.md: within a suite the label is not predictable
    from the patch (3 rejected patches in bugbench; nodus's depend on the OS),
    and the pooled signal is the suite id."""
    rows = list(csv.DictReader((EVIDENCE / "verify_predictor_20261009.csv").open(encoding="utf-8")))
    by = {}
    for r in rows:
        by.setdefault(r["target"], []).append(r["outcome"])
    ver = {t: [o for o in os if o != "refused_before_vm"] for t, os in by.items()}
    assert (ver["bugbench"].count("verified"), ver["bugbench"].count("rejected")) == (64, 3)
    assert (ver["nodus"].count("verified"), ver["nodus"].count("rejected")) == (1, 15)
    text = (EVIDENCE / "verify_predictor_20261009.txt").read_text(encoding="utf-8")
    assert text.count("inside the noise") == 2 and "suite id ALONE" in text
