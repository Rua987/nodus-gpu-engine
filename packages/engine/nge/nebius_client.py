"""Shared ConTree (Nebius Token Factory) client construction.

Both :class:`nge.sandbox.token_factory.TokenFactorySandbox` and
:class:`nge.fleet.nebius.NebiusFleet` build the same authenticated client
through here, so auth lives in exactly one place.
"""
from __future__ import annotations

import logging
from typing import Dict

DEFAULT_TF_BASE_URL = "https://api.tokenfactory.nebius.com/sandboxes/"


def _import_contree():
    """(ContreeSync, ContreeConfig, IAMAuth) or a helpful ImportError."""
    try:
        from contree_sdk import ContreeSync             # type: ignore
        from contree_sdk.config import ContreeConfig    # type: ignore
        from contree_sdk.auth import IAMAuth           # type: ignore
        return ContreeSync, ContreeConfig, IAMAuth
    except Exception as exc:  # pragma: no cover - env dependent
        raise ImportError(
            "ConTree SDK missing - `pip install contree-sdk` "
            "(Nebius Token Factory Sandboxes)."
        ) from exc


def build_contree_client(cfg):
    key = cfg.token_factory_api_key() or cfg.nebius_api_key()
    pid = cfg.nebius_project_id
    if not key:
        raise RuntimeError(
            "Token Factory: no API key - set NEBIUS_API_KEY or "
            "packages/engine/.nebius_api_key")
    if not pid:
        raise RuntimeError(
            "Token Factory: no project id - set NEBIUS_PROJECT_ID / "
            "packages/engine/.nebius_project_id (Nebius console).")
    ContreeSync, ContreeConfig, IAMAuth = _import_contree()
    _quiet_token_expiry()
    base = cfg.token_factory_base_url or DEFAULT_TF_BASE_URL
    auth = IAMAuth(token=key, project_id=pid, base_url=base)
    return ContreeSync(config=ContreeConfig(auth=auth))


class _DropTokenExpiry(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not str(record.getMessage()).startswith("Token expires in")


def _quiet_token_expiry() -> None:
    """ContreeSDK warns "Token expires in 0 hours" on every call: the sandbox
    token minted from the API key lives ~5 minutes and is minted again on the
    next call (measured 2026-10-04: its expiry moved from 22:22:58 to 22:26:19
    UTC between two calls). Live, it printed in the middle of the judge film.
    An API key that really expired would fail auth, not warn."""
    lg = logging.getLogger("contree_sdk.sdk.client._base")
    if not any(isinstance(f, _DropTokenExpiry) for f in lg.filters):
        lg.addFilter(_DropTokenExpiry())


def sandbox_permissions(client) -> Dict[str, bool]:
    who = client.get_token_info()
    return dict(getattr(who, "permissions", {}) or {})


def assert_can_spawn(client) -> None:
    p = sandbox_permissions(client)
    if not (p.get("spawn") or p.get("spawn_disposable")):
        raise RuntimeError(
            "Token Factory Sandboxes: this key has no spawn permission "
            f"({p}). Request beta access at "
            "https://tokenfactory.nebius.com/sandboxes/about (free, no credits).")
