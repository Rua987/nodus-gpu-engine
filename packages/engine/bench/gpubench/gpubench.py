"""Compile and run ``matmul.cu`` - shared by the two test files (one per shard).

The same GPU workload runs on every shard, so the shard on the node with the
induced load and the shard on the idle node time the same work. Fails, rather
than skips, without nvcc: a skipped GPU bench would read as a clean pass.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIZE = 4096


def _nvcc() -> str:
    found = shutil.which("nvcc") or "/usr/local/cuda/bin/nvcc"
    if not Path(found).exists():
        raise AssertionError("nvcc not found - this bench needs the CUDA toolkit "
                             "(Nebius image family ubuntu24.04-cuda13.0 ships it)")
    return found


def run_matmul(workdir: Path, n: int = SIZE, reps: int = 0) -> subprocess.CompletedProcess:
    exe = Path(workdir) / "matmul"
    built = subprocess.run([_nvcc(), "-O2", "-o", str(exe), str(HERE / "matmul.cu")],
                           capture_output=True, text=True, timeout=300)
    if built.returncode != 0:
        raise AssertionError(f"nvcc failed:\n{built.stderr[-2000:]}")
    # At 120 reps nvcc and the GPU work were of the same order (a whole shard
    # took 10-11 s on an L40S): an induced load could not show in its time.
    # 600 reps puts the GPU well above nvcc, yet keeps a shard slowed 2-3x by
    # contention under the 180 s shard timeout whatever the real throughput.
    reps = reps or int(os.environ.get("NGE_GPUBENCH_REPS", "600"))
    run = subprocess.run([str(exe), str(n), str(reps)], capture_output=True, text=True,
                         timeout=900)
    print(run.stdout, run.stderr)
    return run
