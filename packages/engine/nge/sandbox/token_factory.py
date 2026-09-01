"""Nebius Token Factory Sandboxes - live execution isolation (ConTree SDK).

Token Factory Sandboxes are exposed through the **ConTree SDK**
(``pip install contree-sdk``; classes ``Contree`` / ``ContreeSync``;
``sdk.images.use(image)`` -> ``image.run(shell=..., stdin=...).wait()`` ->
``result.stdout / stderr / exit_code``). Docs:
https://docs.tokenfactory.nebius.com/sandboxes/

Status of this file:
    create / put_files / exec / collect / destroy  -> IMPLEMENTED against the
        documented ``ContreeSync`` surface (file I/O done via ``cat`` since the
        SDK's dedicated upload/download helpers are not documented publicly yet).
    _build_client()                                -> the ONE open item: the
        authenticated SDK client constructor. Raises NotImplementedError with a
        pointer until confirmed against an account.
"""
from __future__ import annotations

import shlex
import time
from typing import Dict

from nge.sandbox.base import ExecResult, Sandbox, SandboxSpec


def _import_contree():
    """Return (ContreeSync, module) or raise a helpful ImportError."""
    try:
        from contree import ContreeSync  # type: ignore
        import contree as mod  # type: ignore
        return ContreeSync, mod
    except Exception:
        pass
    try:
        from contree_sdk import ContreeSync  # type: ignore
        import contree_sdk as mod  # type: ignore
        return ContreeSync, mod
    except Exception as exc:  # pragma: no cover - env dependent
        raise ImportError(
            "ConTree SDK not installed - `pip install contree-sdk` "
            "(Nebius Token Factory Sandboxes)."
        ) from exc


class TokenFactorySandbox(Sandbox):
    mode = "token_factory"

    def __init__(self, config=None) -> None:
        from nge import config as _cfg
        self.cfg = config or _cfg.load()
        self.base_url = self.cfg.token_factory_base_url
        self._api_key = self.cfg.token_factory_api_key()
        self._sdk = None
        self._images: Dict[str, object] = {}   # sandbox_id -> ConTree image handle
        self._n = 0

    # -- client -----------------------------------------------------------
    def _build_client(self):
        """Construct the authenticated ConTree API client.

        TODO(live): confirm against an account. The ConTree docs show
        ``ContreeSync(api_client)`` but do not publish the ``api_client`` /
        auth constructor. Expected shape:

            from contree import ContreeSync, ApiClient
            client = ApiClient(base_url=self.base_url, api_key=self._api_key)
            return ContreeSync(client)
        """
        if not self._api_key:
            raise RuntimeError(
                "Token Factory not configured - set TOKEN_FACTORY_API_KEY "
                "(or packages/engine/.token_factory_api_key)."
            )
        raise NotImplementedError(
            "TokenFactorySandbox._build_client: wire ContreeSync(api_client). "
            "See https://docs.tokenfactory.nebius.com/sandboxes/sdk"
        )

    def _sdk_ready(self):
        if self._sdk is None:
            ContreeSync, _ = _import_contree()
            self._sdk = self._build_client()
        return self._sdk

    # -- lifecycle ------------------------------------------------------------
    def create(self, spec: SandboxSpec) -> str:
        sdk = self._sdk_ready()
        self._n += 1
        sid = f"tf-sbx-{self._n:02d}"
        if spec.node_id:
            sid = f"{sid}@{spec.node_id}"
        # ConTree: import/select the base image for this sandbox session.
        self._images[sid] = sdk.images.use(spec.image)
        return sid

    def put_files(self, sandbox_id: str, files: Dict[str, str]) -> None:
        img = self._images[sandbox_id]
        for path, content in (files or {}).items():
            q = shlex.quote(path)
            res = img.run(shell=f"mkdir -p \"$(dirname {q})\" && cat > {q}",
                          stdin=content).wait()
            if getattr(res, "exit_code", 0) != 0:
                raise RuntimeError(f"put_files failed for {path}: {res.stderr}")

    def exec(self, sandbox_id: str, command: str, timeout: int = 120) -> ExecResult:
        img = self._images[sandbox_id]
        t0 = time.perf_counter()
        res = img.run(shell=command, timeout=timeout).wait()
        return ExecResult(
            exit_code=int(getattr(res, "exit_code", 0)),
            stdout=getattr(res, "stdout", "") or "",
            stderr=getattr(res, "stderr", "") or "",
            duration_s=round(time.perf_counter() - t0, 3),
        )

    def collect(self, sandbox_id: str, paths: list) -> Dict[str, str]:
        img = self._images[sandbox_id]
        out: Dict[str, str] = {}
        for p in paths or []:
            res = img.run(shell=f"cat {shlex.quote(p)}").wait()
            out[p] = res.stdout if getattr(res, "exit_code", 1) == 0 else \
                f"[missing: {p}] {getattr(res, 'stderr', '')}".strip()
        return out

    def destroy(self, sandbox_id: str) -> None:
        img = self._images.pop(sandbox_id, None)
        for meth in ("destroy", "close", "delete", "stop"):
            fn = getattr(img, meth, None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass
                break
