"""Deterministic in-process sandbox.

No containers, no network, no GPU. ``exec`` recognises a few command shapes
(pytest, python -c, echo) and returns canned-but-realistic output seeded by the
command + sandbox id, so a fleet run is reproducible in CI and in the demo.
"""
from __future__ import annotations

import hashlib
import re
import time
from typing import Dict

from nge.sandbox.base import ExecResult, Sandbox, SandboxSpec

# A small fixed pool of "failures" the triage step will parse back out.
_FAIL_POOL = [
    ("tests/test_nodus_planner.py::test_plan_order", "AssertionError: plan names out of order"),
    ("tests/test_nodus_tools.py::test_edit_file_unique", "ValueError: old_string not unique"),
    ("tests/test_nodus_verify.py::test_carry_path", "AssertionError: expected [None, 'server.py']"),
    ("tests/test_nodus_gcloud.py::test_upload_mock", "KeyError: 'GCLOUD_BUCKET'"),
    ("tests/test_nodus_memory.py::test_roundtrip", "AssertionError: memory entry missing"),
]


def _seed(*parts: str) -> int:
    h = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return int(h[:8], 16)


class MockSandbox(Sandbox):
    mode = "mock"

    def __init__(self) -> None:
        self._fs: Dict[str, Dict[str, str]] = {}
        self._n = 0

    def create(self, spec: SandboxSpec) -> str:
        self._n += 1
        sid = f"mock-sbx-{self._n:02d}"
        if spec.node_id:
            sid = f"{sid}@{spec.node_id}"
        self._fs[sid] = {}
        return sid

    def put_files(self, sandbox_id: str, files: Dict[str, str]) -> None:
        self._fs.setdefault(sandbox_id, {}).update(files or {})

    def exec(self, sandbox_id: str, command: str, timeout: int = 120) -> ExecResult:
        seed = _seed(sandbox_id, command)
        t0 = time.perf_counter()

        if "pytest" in command:
            # 1..2 deterministic failures per shard, drawn from the pool.
            k = 1 + (seed % 2)
            picks = [_FAIL_POOL[(seed + i) % len(_FAIL_POOL)] for i in range(k)]
            total = 40 + (seed % 20)
            failed = len(picks)
            lines = [f"============================= test session starts =============================",
                     f"collected {total} items", ""]
            for name, msg in picks:
                lines.append(f"FAILED {name} - {msg}")
            lines.append("")
            lines.append(f"================ {failed} failed, {total - failed} passed in "
                         f"{1.2 + (seed % 50) / 10:.2f}s ================")
            out = "\n".join(lines)
            dur = round(time.perf_counter() - t0 + 0.5 + (seed % 30) / 10, 3)
            return ExecResult(exit_code=1, stdout=out, duration_s=dur)

        m = re.search(r"python3?\s+-c\s+(['\"])(.*?)\1", command, re.S)
        if m:
            return ExecResult(exit_code=0, stdout=f"[mock python -c] {m.group(2)[:120]}",
                              duration_s=round(time.perf_counter() - t0, 3))

        if command.strip().startswith("echo "):
            return ExecResult(exit_code=0, stdout=command.strip()[5:].strip(" '\""),
                              duration_s=round(time.perf_counter() - t0, 3))

        return ExecResult(exit_code=0, stdout=f"[mock exec ok] {command[:200]}",
                          duration_s=round(time.perf_counter() - t0, 3))

    def collect(self, sandbox_id: str, paths: list) -> Dict[str, str]:
        fs = self._fs.get(sandbox_id, {})
        out: Dict[str, str] = {}
        for p in paths or []:
            out[p] = fs.get(p, f"[mock artifact] {p} (not produced in mock exec)")
        return out

    def destroy(self, sandbox_id: str) -> None:
        self._fs.pop(sandbox_id, None)
