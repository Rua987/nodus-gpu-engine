"""Shared test wiring: put ``packages/engine`` on sys.path, force mock modes."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ENGINE = Path(__file__).resolve().parents[1]          # packages/engine
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

# Never let a stray real credential / track flag leak into the suite.
for _k in ("NGE_TRACK", "NGE_FLEET_MODE", "NGE_SANDBOX", "NGE_PLAN_FALLBACK",
           "NEBIUS_API_KEY", "TOKEN_FACTORY_API_KEY"):
    os.environ.pop(_k, None)
os.environ["NGE_FLEET_MODE"] = "mock"
os.environ["NGE_SANDBOX"] = "mock"

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_credentials(tmp_path_factory, monkeypatch):
    """No test may touch a real key. Point the ``.nebius_api_key`` /
    ``.token_factory_api_key`` file lookup at an empty dir; tests that need a
    key set it explicitly (env or monkeypatched load_api_key)."""
    import nge.config as _cfg
    monkeypatch.setattr(_cfg, "_ENGINE_DIR", tmp_path_factory.mktemp("nokeys"))
    yield


@pytest.fixture(autouse=True)
def _reset_engine():
    from nge.tools import handlers
    handlers.reset_state()
    yield
    handlers.reset_state()
