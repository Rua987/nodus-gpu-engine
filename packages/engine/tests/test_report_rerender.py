"""Re-rendering a run's control room from its Markdown report."""
from pathlib import Path

import pytest

from nge import report_rerender

EVIDENCE = Path(__file__).resolve().parents[1] / "evidence"


def _norm(text):
    return text.replace("\r\n", "\n")


def test_the_committed_rerender_is_what_the_tool_produces(tmp_path):
    """The re-rendered evidence has a provenance anyone can repeat."""
    out = tmp_path / "r.html"
    assert report_rerender.main([str(EVIDENCE / "report_20261004T031503Z.md"), str(out)]) == 0
    assert _norm(out.read_text(encoding="utf-8")) == _norm(
        (EVIDENCE / "report_20261004T031503Z_rerender.html").read_text(encoding="utf-8"))


def test_rebuilt_input_matches_the_run():
    rep = report_rerender.from_markdown(
        (EVIDENCE / "report_20261004T031503Z.md").read_text(encoding="utf-8"))
    assert [(s["index"], s["node_id"], len(s["failures"])) for s in rep["shards"]] == \
        [(0, "cg-l40s-a-00", 2), (1, "cg-l40s-a-01", 3)]
    assert len(rep["failures"]) == 5 and rep["fixes"] == [] and rep["remediations"] == []
    assert rep["plan"]["source"] == "nodus-324m"


def test_a_run_with_fix_attempts_is_refused():
    """Patch bodies and verdicts are not in the event log: a control room
    without them would misstate the run."""
    with pytest.raises(ValueError, match="attempted fixes"):
        report_rerender.from_markdown(
            (EVIDENCE / "report_20261003T233405Z.md").read_text(encoding="utf-8"))
