"""Nebius Token Factory Sandboxes - live execution isolation (ConTree SDK).

Real wiring against ``contree-sdk`` (``pip install contree-sdk``):

    ContreeSync(config=ContreeConfig(auth=IAMAuth(token=..., project_id=...,
        base_url="https://api.tokenfactory.nebius.com/sandboxes/")))
    img  = client.images.docker("python:3.11-slim")   # import if needed
    sess = img.session()                               # stateful sandbox
    done = sess.run(args=["/bin/sh", "-c", cmd], files={...}, timeout=...).wait()
    done.exit_code / done.stdout / done.stderr / done.elapsed
    sess.read("path")  -> bytes

Signature-compatible with :class:`MockSandbox`. Needs ``NEBIUS_API_KEY``
(or ``packages/engine/.nebius_api_key``) **and** ``NEBIUS_PROJECT_ID``.

Smoke test:  python -m nge.sandbox.token_factory
"""
from __future__ import annotations

import time
from typing import Dict

from nge.sandbox.base import ExecResult, Sandbox, SandboxSpec

DEFAULT_TF_BASE_URL = "https://api.tokenfactory.nebius.com/sandboxes/"
DEFAULT_IMAGE = "python:3.11-slim"


def _import_contree():
    """Return (ContreeSync, ContreeConfig, IAMAuth) or raise a helpful error."""
    try:
        from contree_sdk import ContreeSync             # type: ignore
        from contree_sdk.config import ContreeConfig    # type: ignore
        from contree_sdk.auth import IAMAuth            # type: ignore
        return ContreeSync, ContreeConfig, IAMAuth
    except Exception as exc:  # pragma: no cover - env dependent
        raise ImportError(
            "ConTree SDK missing - `pip install contree-sdk` "
            "(Nebius Token Factory Sandboxes)."
        ) from exc


class TokenFactorySandbox(Sandbox):
    mode = "token_factory"

    def __init__(self, config=None) -> None:
        from nge import config as _cfg
        self.cfg = config or _cfg.load()
        self.base_url = self.cfg.token_factory_base_url or DEFAULT_TF_BASE_URL
        self._sdk = None
        self._sessions: Dict[str, object] = {}     # sid -> ConTree session
        self._pending: Dict[str, dict] = {}        # sid -> files to seed on next exec
        self._n = 0

    # -- client -----------------------------------------------------------
    def _build_client(self):
        key = self.cfg.token_factory_api_key() or self.cfg.nebius_api_key()
        pid = self.cfg.nebius_project_id
        if not key:
            raise RuntimeError(
                "Token Factory: no API key - set NEBIUS_API_KEY or "
                "packages/engine/.nebius_api_key")
        if not pid:
            raise RuntimeError(
                "Token Factory: no project id - set NEBIUS_PROJECT_ID "
                "(from the Nebius console).")
        ContreeSync, ContreeConfig, IAMAuth = _import_contree()
        auth = IAMAuth(token=key, project_id=pid, base_url=self.base_url)
        return ContreeSync(config=ContreeConfig(auth=auth))

    def _sdk_ready(self):
        if self._sdk is None:
            self._sdk = self._build_client()
        return self._sdk

    # -- lifecycle ------------------------------------------------------------
    def create(self, spec: SandboxSpec) -> str:
        sdk = self._sdk_ready()
        self._n += 1
        sid = f"tf-sbx-{self._n:02d}"
        if spec.node_id:
            sid = f"{sid}@{spec.node_id}"
        ref = spec.image or DEFAULT_IMAGE
        try:
            img = sdk.images.use(ref)                 # quickstart path, no import perm
        except Exception:
            img = sdk.images.docker(ref)              # fall back to tag/import
        self._sessions[sid] = img.session()
        self._pending[sid] = {}
        return sid

    def put_files(self, sandbox_id: str, files: Dict[str, str]) -> None:
        self._pending.setdefault(sandbox_id, {}).update(files or {})

    def exec(self, sandbox_id: str, command: str, timeout: int = 120) -> ExecResult:
        sess = self._sessions[sandbox_id]
        files = self._pending.pop(sandbox_id, None) or None
        t0 = time.perf_counter()
        done = sess.run(args=["/bin/sh", "-c", command], files=files,
                        timeout=timeout).wait()
        self._sessions[sandbox_id] = done
        dur = getattr(done, "elapsed", None)
        return ExecResult(
            exit_code=int(getattr(done, "exit_code", 0) or 0),
            stdout=getattr(done, "stdout", "") or "",
            stderr=getattr(done, "stderr", "") or "",
            duration_s=float(dur) if dur is not None
            else round(time.perf_counter() - t0, 3),
        )

    def collect(self, sandbox_id: str, paths: list) -> Dict[str, str]:
        sess = self._sessions[sandbox_id]
        out: Dict[str, str] = {}
        for p in paths or []:
            try:
                out[p] = sess.read(p).decode("utf-8", "replace")
            except Exception as exc:
                out[p] = f"[missing: {p}] {type(exc).__name__}"
        return out

    def destroy(self, sandbox_id: str) -> None:
        sess = self._sessions.pop(sandbox_id, None)
        self._pending.pop(sandbox_id, None)
        for meth in ("close", "delete", "stop"):
            fn = getattr(sess, meth, None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass
                break


def _smoke() -> int:
    """Real end-to-end: build client -> check perms -> spawn a sandbox -> run."""
    from nge import config as _cfg
    sbx = TokenFactorySandbox(_cfg.load())
    sdk = sbx._sdk_ready()
    try:
        who = sdk.get_token_info()
        perms = dict(getattr(who, "permissions", {}) or {})
        print("auth OK  token:", getattr(who, "token_uuid", "?"), " permissions:", perms)
        if not perms.get("spawn") and not perms.get("spawn_disposable"):
            print("\n>> This token has NO sandbox spawn permission. Enable Token "
                  "Factory *Sandboxes* access for this key/project in the Nebius "
                  "console (the product is in beta). Auth + wiring are correct.")
            return 2
    except Exception as exc:
        print("get_token_info failed:", exc)
        return 1
    sid = sbx.create(SandboxSpec(image=DEFAULT_IMAGE, node_id="smoke"))
    print("sandbox:", sid)
    res = sbx.exec(sid, "echo tf-sandbox-ok && python -V && (nvidia-smi -L || true)")
    print(f"exit={res.exit_code}  {res.duration_s}s\n"
          f"--- stdout ---\n{res.stdout}\n--- stderr ---\n{res.stderr}")
    sbx.destroy(sid)
    return 0 if res.exit_code == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_smoke())
