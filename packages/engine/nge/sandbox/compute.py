"""Sandbox on a Nebius Compute GPU VM, over SSH - for shards that need the GPU.

Token Factory sandboxes have no GPU; a shard whose tests run CUDA has to run
on the fleet VM itself. Each sandbox is a fresh directory on its node's VM,
with the venv from cloud-init (pytest) and the CUDA toolkit on PATH; files
travel as a gzip'd tar inside the SSH script, so nothing but SSH is used.

Not an isolation boundary like a microVM: the VM is ours and ephemeral, the
command still goes through the capability jail first (``tools.handlers``).
"""
from __future__ import annotations

import base64
import io
import posixpath
import shlex
import tarfile
import time
import uuid
from typing import Dict

from nge.sandbox.base import ExecResult, Sandbox, SandboxSpec

ROOT = "/tmp/nge_sbx"


class ComputeSandbox(Sandbox):
    mode = "compute"

    def __init__(self, fleet) -> None:
        if not hasattr(fleet, "run_on"):
            raise RuntimeError("the compute sandbox needs the compute fleet "
                               "(NGE_FLEET_MODE=compute) - it runs on the fleet's VMs")
        self._fleet = fleet
        self._dirs: Dict[str, tuple] = {}            # sandbox id -> (node id, directory)

    def _run(self, sid: str, script: str, timeout: float):
        node, _ = self._dirs[sid]
        return self._fleet.run_on(node, script, timeout=timeout)

    def create(self, spec: SandboxSpec) -> str:
        if not spec.node_id:
            raise RuntimeError("a compute sandbox runs on a fleet node: node_id is required")
        token = uuid.uuid4().hex[:10]
        sid = f"{token}@{spec.node_id}"
        d = f"{ROOT}/{token}"
        self._dirs[sid] = (spec.node_id, d)
        rc, _out, err = self._run(sid, f"mkdir -p {d}\n", timeout=60.0)
        if rc != 0:
            self._dirs.pop(sid, None)
            raise RuntimeError(f"compute sandbox on {spec.node_id}: {err.strip()[:200]}")
        return sid

    def put_files(self, sandbox_id: str, files: Dict[str, str]) -> None:
        _, d = self._dirs[sandbox_id]
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for rel, content in (files or {}).items():
                norm = posixpath.normpath(rel.replace("\\", "/"))
                if norm.startswith(("/", "../")) or norm == "..":
                    raise ValueError(f"refusing a path outside the sandbox: {rel!r}")
                data = content.encode("utf-8") if isinstance(content, str) else bytes(content)
                info = tarfile.TarInfo(norm)
                info.size, info.mode = len(data), 0o644
                tar.addfile(info, io.BytesIO(data))
        b64 = base64.encodebytes(buf.getvalue()).decode("ascii")
        script = (f"cd {d} && base64 -d > files.tgz <<'NGE_EOF'\n{b64}NGE_EOF\n"
                  "tar xzf files.tgz && rm files.tgz\n")
        rc, _out, err = self._run(sandbox_id, script, timeout=300.0)
        if rc != 0:
            raise RuntimeError(f"compute sandbox upload failed: {err.strip()[:200]}")

    def exec(self, sandbox_id: str, command: str, timeout: int = 120) -> ExecResult:
        from nge.fleet import compute_probe as cp
        _, d = self._dirs[sandbox_id]
        script = (f"export PATH={cp.VENV}/bin:/usr/local/cuda/bin:$PATH\n"
                  f"cd {d} || exit 97\n"
                  f"timeout {int(timeout)} sh -c {shlex.quote(command)}\n")
        t0 = time.perf_counter()
        rc, out, err = self._run(sandbox_id, script, timeout=float(timeout) + 60.0)
        return ExecResult(exit_code=int(rc), stdout=out, stderr=err,
                          duration_s=round(time.perf_counter() - t0, 3))

    def collect(self, sandbox_id: str, paths: list) -> Dict[str, str]:
        _, d = self._dirs[sandbox_id]
        got: Dict[str, str] = {}
        for p in paths or []:
            rc, out, _err = self._run(sandbox_id, f"cat {shlex.quote(d + '/' + p)}\n",
                                      timeout=60.0)
            got[p] = out if rc == 0 else f"[missing: {p}]"
        return got

    def destroy(self, sandbox_id: str) -> None:
        if sandbox_id not in self._dirs:
            return
        try:                                       # the VM may already be deleted
            self._run(sandbox_id, f"rm -rf {self._dirs[sandbox_id][1]}\n", timeout=60.0)
        finally:
            self._dirs.pop(sandbox_id, None)
