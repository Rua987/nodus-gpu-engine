"""Shared ConTree (Nebius Token Factory) client construction.

Both :class:`nge.sandbox.token_factory.TokenFactorySandbox` and
:class:`nge.fleet.nebius.NebiusFleet` build the same authenticated client
through here, so auth lives in exactly one place.
"""
from __future__ import annotations

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
    base = cfg.token_factory_base_url or DEFAULT_TF_BASE_URL
    auth = IAMAuth(token=key, project_id=pid, base_url=base)
    return ContreeSync(config=ContreeConfig(auth=auth))


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
