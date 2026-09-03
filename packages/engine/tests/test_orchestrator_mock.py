"""End-to-end mock run: plan -> fleet -> sandboxes -> triage -> artifact."""
import json
from pathlib import Path

import pytest

from nge import config as _cfg
from nge.orchestrator import NgeOrchestrator

SCENARIO = {
    "task": "Run the failing pytest suite across the GPU fleet, triage the failures, "
            "propose fixes, and deliver a consolidated Markdown report.",
    "shards": 3,
    "gpu_type": "H100",
    "target": "packages/nodus/tests",
    "collect": [],
}


@pytest.fixture
def cfg(tmp_path):
    return _cfg.load(fleet_mode="mock", sandbox_mode="mock", out_dir=tmp_path)


def test_full_mock_run_produces_artifact(cfg):
    rep = NgeOrchestrator(config=cfg).run(SCENARIO)

    assert rep.ok is True
    assert len(rep.shards) == 3
    assert rep.plan_source in ("nodus-324m", "heuristic")
    assert rep.failures, "mock shards should surface at least one failure"

    art = Path(rep.artifact_path)
    assert art.is_file()
    text = art.read_text(encoding="utf-8")
    assert "Fleet test triage" in text
    assert "Consolidated failures" in text
    assert "Event log" in text


def test_event_log_covers_the_pipeline(cfg):
    rep = NgeOrchestrator(config=cfg).run(SCENARIO)
    kinds = [e["kind"] for e in rep.events]
    for expected in ("run_start", "plan", "gpu_provision", "shard_start",
                     "gpu_status", "triage", "gpu_release", "artifact", "run_end"):
        assert expected in kinds
    # final fleet release frees exactly the shard fleet (00, 01, migrated 03)
    rel = [e for e in rep.events if e["kind"] == "gpu_release"][-1]
    assert rel["count"] == 3


def test_run_is_deterministic(cfg):
    a = NgeOrchestrator(config=cfg).run(SCENARIO)
    b = NgeOrchestrator(config=cfg).run(SCENARIO)
    assert [s.failures for s in a.shards] == [s.failures for s in b.shards]
    assert a.failures == b.failures


def test_telemetry_sink_receives_events(cfg):
    seen = []

    class Sink:
        def record(self, kind, **fields):
            seen.append(kind)

    NgeOrchestrator(config=cfg, telemetry=Sink()).run(SCENARIO)
    assert "gpu_provision" in seen and "run_end" in seen


def test_model_routing_is_recorded(cfg):
    rep = NgeOrchestrator(config=cfg).run(SCENARIO)
    tiers = {r["tier"] for r in rep.routes}
    assert "ultra" in tiers            # plan -> Ultra
    assert "super" in tiers            # slot-fill -> Super
    assert "nano" in tiers             # pressure healthcheck -> Nano
    for r in rep.routes:
        assert r["model"].startswith("nebius:nvidia/nemotron-3-")
    kinds = [e["kind"] for e in rep.events]
    assert "model_route" in kinds


def test_feedback_loop_migrates_the_hot_node(cfg):
    rep = NgeOrchestrator(config=cfg).run(SCENARIO)

    # shard 2 lands on nb-h100-02 which is a deterministic "hot" node
    assert len(rep.remediations) == 1
    rm = rep.remediations[0]
    assert rm["shard"] == 2
    assert rm["from"] == "nb-h100-02"
    assert rm["to"] == "nb-h100-03"
    assert rm["reason"] == "throttle"

    sr2 = rep.shards[2]
    assert sr2.migrated_from == "nb-h100-02"
    assert sr2.node_id == "nb-h100-03"

    kinds = [e["kind"] for e in rep.events]
    assert "gpu_pressure" in kinds and "gpu_remediation" in kinds

    text = Path(rep.artifact_path).read_text(encoding="utf-8")
    assert "Self-managed compute" in text
    assert "migrated to `nb-h100-03`" in text


def test_healthy_shards_are_not_migrated(cfg):
    rep = NgeOrchestrator(config=cfg).run(SCENARIO)
    assert rep.shards[0].migrated_from is None
    assert rep.shards[1].migrated_from is None


def test_autofix_loop_patches_and_verifies(cfg):
    rep = NgeOrchestrator(config=cfg).run(SCENARIO)

    assert rep.fixes, "the code agent should attempt fixes"
    assert [x for x in rep.fixes if x.get("verified")], "a canned patch should re-test green"
    # A failure with no canned patch must record patch=None. Asserted directly
    # rather than hoping the deterministic draw includes one - it stopped doing
    # so when the shard command changed, which is a seed detail, not a bug.
    from nge.tools import handlers
    o2 = NgeOrchestrator(config=cfg)
    handlers.reset_state(cfg)
    no_patch = o2._attempt_fixes([{"test": "nope.py::test_unknown", "error": "x"}],
                                 "packages/nodus/tests")
    assert no_patch and no_patch[0]["patch"] is None
    assert no_patch[0]["reason"] == "no patch proposed"

    kinds = [e["kind"] for e in rep.events]
    assert "fix_attempt" in kinds and "fix_verified" in kinds

    art = Path(rep.artifact_path)
    text = art.read_text(encoding="utf-8")
    assert "Auto-fixes (code agent)" in text
    assert "patched & re-tested green" in text
    assert "auto-fixed & verified" in text

    fixes_dir = art.parent / "fixes"
    assert fixes_dir.is_dir()
    patches = list(fixes_dir.glob("*.patch"))
    assert patches and any("--- a/" in p.read_text(encoding="utf-8") for p in patches)


def test_autofix_is_deterministic(cfg):
    a = NgeOrchestrator(config=cfg).run(SCENARIO)
    b = NgeOrchestrator(config=cfg).run(SCENARIO)
    assert [(x["test"], x.get("verified"), x.get("patch")) for x in a.fixes] == \
           [(x["test"], x.get("verified"), x.get("patch")) for x in b.fixes]


def test_chat_fn_slotfill_is_used(cfg):
    calls = []

    def chat_fn(messages, model=None, tools=None):
        calls.append(model)
        return {"role": "assistant", "content": "python -m pytest packages/nodus/tests -q -k smoke"}

    rep = NgeOrchestrator(config=cfg, chat_fn=chat_fn).run(SCENARIO)
    assert calls, "chat_fn should be called for slot-fill"
    assert any("-k smoke" in s.command for s in rep.shards)
