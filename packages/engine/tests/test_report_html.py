"""HTML report render + orchestrator wiring."""
import tempfile
from pathlib import Path

from nge import config as _cfg, report_html
from nge.orchestrator import NgeOrchestrator

SCENARIO = {
    "task": "run failing tests across the fleet, triage, fix, report",
    "shards": 3, "gpu_type": "H100", "target": "packages/nodus/tests",
}


def test_render_is_self_contained_and_escaped(tmp_path):
    rep = {
        "plan": {"names": ["bash"], "source": "heuristic"},
        "shards": [{"index": 0, "node_id": "nb-h100-00", "exit_code": 1,
                    "duration_s": 0.5, "failures": [{}], "migrated_from": None}],
        "failures": [{"test": "t::x", "error": "Boom <script>", "proposed_fix": "do y"}],
        "routes": [{"decision": "plan", "tier": "ultra", "model": "nebius:x"}],
        "remediations": [], "events": [{"kind": "run_start", "fleet_mode": "mock",
                                       "sandbox_mode": "mock"}],
        "fixes": [{"test": "t::x", "patch": "--- a/f\n+++ b/f\n+ok\n- bad\n",
                   "verified": True}],
    }
    out = report_html.render(rep, tmp_path / "r.html")
    doc = out.read_text(encoding="utf-8")
    assert doc.startswith("<!doctype html>")
    assert "http://" not in doc.split("</style>")[0]        # no external assets
    assert "<script>" not in doc                              # error text escaped
    assert "&lt;script&gt;" in doc
    assert 'class="badge ultra"' in doc
    assert 'class="add"' in doc and 'class="del"' in doc      # diff coloured
    assert "AUTO-FIXED" in doc


def test_orchestrator_writes_html_next_to_md(tmp_path):
    cfg = _cfg.load(fleet_mode="mock", sandbox_mode="mock", out_dir=tmp_path)
    rep = NgeOrchestrator(config=cfg).run(SCENARIO)
    assert rep.html_path and Path(rep.html_path).is_file()
    assert Path(rep.html_path).suffix == ".html"
    assert Path(rep.artifact_path).with_suffix(".html") == Path(rep.html_path)
    doc = Path(rep.html_path).read_text(encoding="utf-8")
    assert "fleet run" in doc
    assert "nb-h100-02" in doc and "nb-h100-03" in doc        # migration visible
    assert "Auto-fixes" in doc
