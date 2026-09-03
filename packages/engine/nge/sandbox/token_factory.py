"""Nebius Token Factory Sandboxes - live execution isolation (ConTree SDK).

Real wiring against ``contree-sdk`` (``pip install contree-sdk``):

    ContreeSync(config=ContreeConfig(auth=IAMAuth(token=..., project_id=...,
        base_url="https://api.tokenfactory.nebius.com/sandboxes/")))
    img  = client.images.docker("python:3.11-slim")   # import if needed
    sess = img.session()                               # stateful sandbox
    done = sess.run(shell=cmd, files={...}, timeout=...).wait()
    done.exit_code / done.stdout / done.stderr / done.elapsed (timedelta)
    sess.read("path")  -> bytes

Signature-compatible with :class:`MockSandbox`. Needs ``NEBIUS_API_KEY``
(or ``packages/engine/.nebius_api_key``) **and** ``NEBIUS_PROJECT_ID``.

Smoke test:  python -m nge.sandbox.token_factory
"""
from __future__ import annotations

from datetime import timedelta
import time
from typing import Dict

from nge.nebius_client import DEFAULT_TF_BASE_URL, build_contree_client
from nge.sandbox.base import ExecResult, Sandbox, SandboxSpec

DEFAULT_IMAGE = "python:3.12-slim"


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
        return build_contree_client(self.cfg)

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
        pending = self._pending.pop(sandbox_id, None) or None
        # ContreeSDK reads a dict value of type `str` as a *local path* and only
        # `bytes` as literal content, so passing source text straight through
        # made it try to open the file whose name was the whole file body.
        files = ({k: v.encode("utf-8") if isinstance(v, str) else v
                  for k, v in pending.items()} if pending else None)
        t0 = time.perf_counter()
        # ContreeSDK takes `shell="<line>"` (or command=+args=); passing the
        # /bin/sh invocation through `args` alone leaves command unset and the
        # SDK raises "Either command or shell must be provided".
        done = sess.run(shell=command, files=files, timeout=timeout).wait()
        self._sessions[sandbox_id] = done
        # `elapsed` comes back as a timedelta from the SDK, not a number
        dur = getattr(done, "elapsed", None)
        if isinstance(dur, timedelta):
            dur = dur.total_seconds()
        try:
            dur = float(dur) if dur is not None else None
        except (TypeError, ValueError):
            dur = None
        return ExecResult(
            exit_code=int(getattr(done, "exit_code", 0) or 0),
            stdout=getattr(done, "stdout", "") or "",
            stderr=getattr(done, "stderr", "") or "",
            duration_s=round(dur if dur is not None
                             else time.perf_counter() - t0, 3),
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
    from nge.nebius_client import assert_can_spawn, sandbox_permissions
    sbx = TokenFactorySandbox(_cfg.load())
    sdk = sbx._sdk_ready()
    try:
        print("auth OK  permissions:", sandbox_permissions(sdk))
        assert_can_spawn(sdk)
    except RuntimeError as exc:
        print("\n>>", exc)
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
