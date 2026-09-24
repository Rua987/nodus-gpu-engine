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
        "routes": [
            {"decision": "plan", "tier": "ultra", "model": "nebius:x"},
            {"decision": "slotfill", "tier": "super", "model": "nebius:y"},
            {"decision": "healthcheck", "tier": "nano", "model": "nebius:z"},
        ],
        "remediations": [], "events": [{"kind": "run_start", "fleet_mode": "mock",
                                       "sandbox_mode": "mock"}],
        "fixes": [{"test": "t::x", "patch": "--- a/f\n+++ b/f\n+ok\n- bad\n",
                   "verified": True, "node": "nb-h100-04"}],
    }
    out = report_html.render(rep, tmp_path / "r.html")
    doc = out.read_text(encoding="utf-8")
    assert doc.startswith("<!doctype html>")
    assert "http://" not in doc.split("</style>")[0]        # no external assets
    assert "<script>" not in doc                              # error text escaped
    assert "&lt;script&gt;" in doc
    assert 'class="badge ultra"' in doc
    assert 'class="add"' in doc and 'class="del"' in doc      # diff coloured
    assert "PATCHES KEPT" in doc or "AUTO-FIXED" in doc
    assert "control room" in doc
    assert "VERIFY" in doc and "nb-h100-04" in doc
    assert "fresh box" in doc or "fresh sandbox" in doc
    assert "already in Auto-fixes" in doc
    assert 'class="roles"' in doc
    assert "</span> <span" in doc
    assert "plansuper" not in doc
    assert "triagenano" not in doc


def test_live_cpu_card_shows_truncate_not_fake_ok(tmp_path):
    test = "pkg/tests/t.py::test_x"
    rep = {
        "plan": {"names": ["bash", "edit_file"], "source": "heuristic"},
        "shards": [{"index": 0, "node_id": "nb-h100-00", "exit_code": 1,
                    "duration_s": 6.8, "failures": [{}, {}], "migrated_from": None}],
        "failures": [{"test": test, "error": "(no message; see shard output)",
                      "proposed_fix": "bisect"}],
        "routes": [
            {"decision": "plan", "tier": "ultra", "model": "nebius:u"},
            {"decision": "triage", "tier": "super", "model": "nebius:s"},
        ],
        "remediations": [],
        "fixes": [{"test": test, "verified": False, "patch": None,
                   "reason": "no patch proposed"}],
        "events": [
            {"kind": "capabilities", "expect_probe": "cpu-fallback"},
            {"kind": "run_start", "fleet_mode": "nebius",
             "sandbox_mode": "token_factory"},
            {"kind": "gpu_status", "node_id": "nb-h100-00",
             "telemetry": {"id": "nb-h100-00", "temp_c": 0, "util_pct": 0,
                           "health": "ok", "probe_kind": "cpu-fallback"}},
            {"kind": "patch_truncated", "test": test, "max_tokens": 2048,
             "reply_chars": 0, "why": "finish_reason=length"},
        ],
    }
    doc = report_html.render(rep, tmp_path / "live.html").read_text(encoding="utf-8")
    assert "CPU — no GPU probe" in doc
    assert "temp 0C" not in doc
    assert "2/3 is honesty, not a miss" not in doc
    assert "0/1 kept" in doc
    assert "Super truncated (2048 tokens, 0-char reply)" in doc
    assert "heal gated" in doc
    assert "within budget" not in doc
    assert "cpu-fallback — no GPU thermometer" in doc
    assert "0.0°C" not in doc and "0.0&deg;C" not in doc
    assert '<div class="sub"></div>' not in doc
    assert "route only" in doc
    assert "No pressure/migrate" in doc
    assert "no usable diff" in doc
    assert "re-tested red" not in doc


def test_fix_subtitle_distinguishes_rejected_patch(tmp_path):
    t_empty = "t::empty"
    t_red = "t::red"
    rep = {
        "plan": {"names": ["edit_file"], "source": "heuristic"},
        "shards": [{"index": 0, "node_id": "nb-h100-00", "exit_code": 1,
                    "duration_s": 1.0, "failures": [{}, {}], "migrated_from": None}],
        "failures": [
            {"test": t_empty, "error": "e1", "proposed_fix": ""},
            {"test": t_red, "error": "e2", "proposed_fix": ""},
        ],
        "routes": [{"decision": "triage", "tier": "super", "model": "nebius:s"}],
        "remediations": [],
        "fixes": [
            {"test": t_empty, "verified": False, "patch": None,
             "reason": "no patch proposed"},
            {"test": t_red, "verified": False, "patch": "--- a/x\n+++ b/x\n+y\n",
             "reason": "target test still failing", "node": "nb-h100-01"},
        ],
        "events": [
            {"kind": "capabilities", "expect_probe": "cpu-fallback"},
            {"kind": "run_start", "fleet_mode": "nebius",
             "sandbox_mode": "token_factory"},
            {"kind": "patch_truncated", "test": t_empty, "max_tokens": 2048,
             "reply_chars": 0},
        ],
    }
    doc = report_html.render(rep, tmp_path / "mix.html").read_text(encoding="utf-8")
    assert "0/2 kept" in doc
    assert "re-tested red" in doc
    assert "no usable diff" in doc
    assert "Super produced no usable diff (truncated or empty) — honesty" not in doc


def test_orchestrator_writes_html_next_to_md(tmp_path):
    cfg = _cfg.load(fleet_mode="mock", sandbox_mode="mock", out_dir=tmp_path)
    rep = NgeOrchestrator(config=cfg).run(SCENARIO)
    assert rep.html_path and Path(rep.html_path).is_file()
    assert Path(rep.html_path).suffix == ".html"
    assert Path(rep.artifact_path).with_suffix(".html") == Path(rep.html_path)
    doc = Path(rep.html_path).read_text(encoding="utf-8")
    assert "control room" in doc or "fleet run" in doc
    assert "nb-h100-02" in doc and "nb-h100-03" in doc        # migration visible
    assert "Auto-fixes" in doc
    assert "THROTTLED then released" in doc
    assert "overheated" in doc
    assert "Short plot only" in doc
    verify = {f.get("node") for f in (rep.fixes or []) if f.get("node")}
    if verify:
        for nid in verify:
            assert nid in doc
        assert "VERIFY" in doc
        assert "already in Auto-fixes" in doc
