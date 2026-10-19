"""bench/suite_recheck.py on the real bugbench, locally - no network, no model."""
import pytest

pytest.importorskip("patch_ng")

from bench import suite_recheck as sr  # noqa: E402


def test_the_unpatched_suite_runs_and_shows_the_six_bugs():
    res = sr.run_suite()
    assert res["applied"] and res["ran"] and len(res["failed"]) == 6


def test_a_patch_that_does_not_apply_is_not_run():
    bogus = ("--- a/packages/engine/bench/bugbench/dates.py\n"
             "+++ b/packages/engine/bench/bugbench/dates.py\n"
             "@@ -1,1 +1,1 @@\n-this line is nowhere\n+x\n")
    assert sr.run_suite(bogus) == {"applied": False, "ran": False, "failed": set()}
