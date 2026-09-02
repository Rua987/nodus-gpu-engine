"""Environment-driven configuration for the Nodus-GPU Engine.

Everything defaults to ``mock`` so the demo and the test suite run with no
credentials and no network. Set the ``NGE_*`` / ``NEBIUS_*`` / ``TOKEN_FACTORY_*``
variables (or a ``.env`` next to this package, loaded by the caller) to go live.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).resolve().parent           # .../packages/engine/nge
_ENGINE_DIR = _HERE.parent                          # .../packages/engine

_TRUTHY = {"1", "true", "yes", "on"}

# Nebius "AI Studio" was rebranded "Token Factory". OpenAI-compatible endpoint:
DEFAULT_NEBIUS_BASE_URL = "https://api.tokenfactory.us-central1.nebius.com/v1"
LEGACY_NEBIUS_BASE_URL = "https://api.studio.nebius.com/v1"

# Nemotron 3 family on Token Factory (ids per nebius.com/services/token-factory/nemotron):
#   nvidia/nemotron-3-super-120b-a12b  - hybrid MoE, multi-agent + complex reasoning (default)
#   nvidia/nemotron-3-nano-30b-a3b     - compact MoE, efficient reasoning/chat/coding
#   Nemotron 3 Ultra 550b             - long-running autonomous agents / deep research
#                                        (id suffix not yet confirmed publicly)
DEFAULT_NEMOTRON_MODEL = "nebius:nvidia/nemotron-3-super-120b-a12b"
NEMOTRON_ULTRA_MODEL = "nebius:nvidia/nemotron-3-ultra-550b"       # confirm exact id
NEMOTRON_SUPER_MODEL = "nebius:nvidia/nemotron-3-super-120b-a12b"
NEMOTRON_NANO_MODEL = "nebius:nvidia/nemotron-3-nano-30b-a3b"

NEBIUS_PREFIX = "nebius:"


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def load_api_key(provider: str, env_name: Optional[str] = None) -> Optional[str]:
    """Read an API key from ``packages/engine/.{provider}_api_key`` then env.

    Mirrors ``nodus_backends.load_api_key`` so keys are never hard-coded.
    """
    key_file = _ENGINE_DIR / f".{provider}_api_key"
    try:
        if key_file.is_file():
            content = key_file.read_text(encoding="utf-8").strip()
            if content:
                return content
    except OSError:
        pass
    return os.environ.get(env_name or f"{provider.upper()}_API_KEY") or None


def load_value(basename: str, env_name: str) -> str:
    """Read a plain config value from ``packages/engine/.{basename}`` then env."""
    f = _ENGINE_DIR / f".{basename}"
    try:
        if f.is_file():
            v = f.read_text(encoding="utf-8").strip()
            if v:
                return v
    except OSError:
        pass
    return _env(env_name)


@dataclass(frozen=True)
class Config:
    fleet_mode: str = "mock"          # mock | nebius
    sandbox_mode: str = "mock"        # mock | token_factory
    track: str = ""                   # "" | nebius
    nemotron_model: str = DEFAULT_NEMOTRON_MODEL      # default working tier (super)
    nemotron_ultra: str = NEMOTRON_ULTRA_MODEL        # reasoning / orchestration
    nemotron_super: str = NEMOTRON_SUPER_MODEL        # slot-fill / triage
    nemotron_nano: str = NEMOTRON_NANO_MODEL          # fast background / telemetry
    nebius_base_url: str = DEFAULT_NEBIUS_BASE_URL
    token_factory_base_url: str = ""
    nebius_project_id: str = ""
    nebius_region: str = "eu-north1"
    jail: bool = True                 # capability jail on run_in_sandbox
    out_dir: Path = field(default=_ENGINE_DIR / "out")

    # ---- derived ---------------------------------------------------------
    @property
    def is_mock(self) -> bool:
        return self.fleet_mode == "mock" and self.sandbox_mode == "mock"

    @property
    def nebius_chat_url(self) -> str:
        return self.nebius_base_url.rstrip("/") + "/chat/completions"

    def nebius_api_key(self) -> Optional[str]:
        return load_api_key("nebius", "NEBIUS_API_KEY")

    def token_factory_api_key(self) -> Optional[str]:
        return load_api_key("token_factory", "TOKEN_FACTORY_API_KEY")


def load(**overrides) -> Config:
    """Build a :class:`Config` from the environment, with kwarg overrides."""
    cfg = Config(
        fleet_mode=_env("NGE_FLEET_MODE", "mock").lower() or "mock",
        sandbox_mode=_env("NGE_SANDBOX", "mock").lower() or "mock",
        track=_env("NGE_TRACK").lower(),
        nemotron_model=_env("NEMOTRON_MODEL", DEFAULT_NEMOTRON_MODEL),
        nemotron_ultra=_env("NEMOTRON_ULTRA_MODEL", NEMOTRON_ULTRA_MODEL),
        nemotron_super=_env("NEMOTRON_SUPER_MODEL", NEMOTRON_SUPER_MODEL),
        nemotron_nano=_env("NEMOTRON_NANO_MODEL", NEMOTRON_NANO_MODEL),
        nebius_base_url=_env("NEBIUS_BASE_URL", DEFAULT_NEBIUS_BASE_URL),
        token_factory_base_url=load_value("token_factory_base_url", "TOKEN_FACTORY_BASE_URL"),
        nebius_project_id=load_value("nebius_project_id", "NEBIUS_PROJECT_ID"),
        nebius_region=_env("NEBIUS_REGION", "eu-north1"),
        jail=_env("NGE_JAIL", "on").lower() not in ("0", "off", "false", "no"),
        out_dir=Path(_env("NGE_OUT_DIR") or (_ENGINE_DIR / "out")),
    )
    if overrides:
        from dataclasses import replace
        cfg = replace(cfg, **overrides)
    return cfg


def hackathon_track() -> bool:
    """True when the Nebius submission guard is active (NGE_TRACK=nebius)."""
    return _env("NGE_TRACK").lower() in _TRUTHY | {"nebius"}
