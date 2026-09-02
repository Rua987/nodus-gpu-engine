"""Failure catalogue shared by mock sandbox + orchestrator --mock path."""
from nge import _fixtures


def test_catalogue_shape():
    for f in _fixtures.FAILURES:
        assert "::" in f["test"]
        assert f["error"]
        if f["fixable"]:
            assert f["patch"] and f["patch"].startswith("--- a/")
        else:
            assert f["patch"] is None


def test_lookup_by_full_name_and_keyword():
    name = "tests/test_nodus_planner.py::test_plan_order"
    assert _fixtures.is_fixable(name)
    assert _fixtures.is_fixable("test_plan_order")            # bare keyword
    assert _fixtures.canned_patch(name).startswith("--- a/nodus_planner.py")


def test_unfixable_has_no_patch():
    name = "tests/test_nodus_gcloud.py::test_upload_mock"
    assert _fixtures.is_fixable(name) is False
    assert _fixtures.canned_patch(name) is None


def test_unknown_test_is_safe():
    assert _fixtures.failure_by_test("nope::nope") is None
    assert _fixtures.canned_patch("nope") is None
    assert _fixtures.is_fixable("nope") is False
