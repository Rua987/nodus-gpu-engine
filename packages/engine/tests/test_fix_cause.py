"""Cause / urgency tags for auto-fix reports."""
from nge.fix_cause import annotate_fix, urgency_for


def test_verified_low_urgency_single_file():
    f = {"test": "a.py::t1", "error": "AssertionError: x",
         "proposed_fix": "Sort the list."}
    a = annotate_fix(f, reason="re-tested green", verified=True,
                       has_patch=True, all_failures=[f])
    assert a["urgency"] == "low"
    assert "Symptom:" in a["cause"]
    assert a["reason"] == "re-tested green"


def test_no_patch_medium_and_cluster_raises():
    fails = [
        {"test": "m.py::a", "error": "boom", "proposed_fix": "hint"},
        {"test": "m.py::b", "error": "boom2", "proposed_fix": "hint2"},
    ]
    a = annotate_fix(fails[0], reason="no patch proposed", verified=False,
                       has_patch=False, all_failures=fails)
    assert a["urgency"] == "high"  # 2 failures in same file
    assert "same file has 2" in a["fragility"]


def test_regression_is_high():
    assert urgency_for(verified=False, has_patch=True,
                       reason="broke other.py::t",
                       regressions=["other.py::t"]) == "high"


def test_hint_sentence_has_one_full_stop():
    """The judge-film HTML read "Hint was: ... before asserting.." three times."""
    from nge.fix_cause import annotate_fix
    f = {"test": "t.py::test_a", "error": "AssertionError: x",
         "proposed_fix": "Sort plan names before asserting."}
    for verified, has_patch in ((True, True), (False, False), (False, True)):
        row = annotate_fix(f, reason="r", verified=verified, has_patch=has_patch,
                           all_failures=[f])
        assert ".." not in " ".join(str(v) for v in row.values()), row
