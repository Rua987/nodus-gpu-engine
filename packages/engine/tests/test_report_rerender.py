"""Re-rendering a run's control room from its Markdown report."""
from pathlib import Path

import pytest

from nge import report_rerender

EVIDENCE = Path(__file__).resolve().parents[1] / "evidence"


def _norm(text):
    return text.replace("\r\n", "\n")


@pytest.mark.parametrize("stem", ["report_20261004T031503Z", "report_20261005T001234Z"])
def test_the_committed_rerender_is_what_the_tool_produces(tmp_path, stem):
    """The re-rendered evidence has a provenance anyone can repeat."""
    out = tmp_path / "r.html"
    assert report_rerender.main([str(EVIDENCE / f"{stem}.md"), str(out)]) == 0
    assert _norm(out.read_text(encoding="utf-8")) == _norm(
        (EVIDENCE / f"{stem}_rerender.html").read_text(encoding="utf-8"))


def test_a_node_left_for_being_busy_is_not_called_throttled():
    rep = report_rerender.from_markdown(
        (EVIDENCE / "report_20261005T001234Z.md").read_text(encoding="utf-8"))
    from nge import report_html
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        doc = report_html.render(rep, Path(td) / "r.html").read_text(encoding="utf-8")
    body = doc.split("raw event log")[0]
    assert "BUSY then released" in body and "THROTTLED" not in body
    assert "Shards run on the VMs themselves" in body
    assert "read after the shard finished" in body and "no GPU work declared" not in body


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
