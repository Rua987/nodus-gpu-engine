"""Nemotron tier router."""
from nge import config as _cfg
from nge import router


def test_tiers():
    assert router.tier_for("plan") == "ultra"
    assert router.tier_for("orchestrate") == "ultra"
    assert router.tier_for("slotfill") == "super"
    assert router.tier_for("triage") == "super"
    assert router.tier_for("telemetry_digest") == "nano"
    assert router.tier_for("healthcheck") == "nano"
    assert router.tier_for("something-unknown") == "super"  # default


def test_model_for_resolves_ids():
    cfg = _cfg.load()
    assert router.model_for("plan", cfg) == cfg.nemotron_ultra
    assert router.model_for("slotfill", cfg) == cfg.nemotron_super
    assert router.model_for("healthcheck", cfg) == cfg.nemotron_nano
    for m in (cfg.nemotron_ultra, cfg.nemotron_super, cfg.nemotron_nano):
        assert m.lower().startswith("nebius:nvidia/")
        assert "nemotron" in m.lower()
    assert "ultra" in cfg.nemotron_ultra.lower()
    assert "super" in cfg.nemotron_super.lower()
    assert "nano" in cfg.nemotron_nano.lower()


def test_route_record():
    cfg = _cfg.load()
    rec = router.route("plan", cfg)
    assert rec == {"decision": "plan", "tier": "ultra", "model": cfg.nemotron_ultra}


def test_env_override(monkeypatch):
    monkeypatch.setenv("NEMOTRON_ULTRA_MODEL", "nebius:nvidia/nemotron-3-ultra-550b-a99b")
    cfg = _cfg.load()
    assert router.model_for("plan", cfg).endswith("a99b")
