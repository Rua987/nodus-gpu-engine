# Where this runs, and what each environment caught

The test suite only checks what someone thought to check. Every bug of any
consequence in this project was found by *running it somewhere new*, not by
adding a test — so this file records where it has actually been run, what each
place found, and what is still only exercised on one machine.

## What each environment found

| environment | what it exposed |
|---|---|
| **Nebius Token Factory sandbox** | The ContreeSDK contract was wrong twice: `run()` needs `shell=` (not `args=`), and `files={}` values must be **bytes** — a `str` is read as a local path, so shipping source text made the SDK try to open a file named after a whole `conftest.py`. The test fake had copied my wrong signature, so a green suite could never have caught it. Also: the image is bare — no pytest, no dependencies, **no git, no patch**. Every auto-fix had been dying on `git: not found` and reporting "patch rejected". |
| **GitHub Actions (ubuntu-latest)** | `ModuleNotFoundError: numpy`. `--live` imports `nodus_agent` to install the `nebius:` backend patch, so it needs the vendored runtime's dependencies, not just the engine's. numpy is on my machine and not on the runner. |
| **A fresh clone** | The download progress bar redraws with `\r` — right in a terminal, wrong in a log: the redirected output came back as a single 30,000-character line. |
| **An empty venv** | With weights on disk but torch absent, the planner claimed the model "ran but declined this task". It had never loaded. `try_plan_tool_names` returns `None` for a load failure exactly as it does for a declined task. |
| **The CI matrix, again** | Three of my own tests exercised the model's behaviour without declaring they need torch. They passed locally, failed on all three Python versions. The first fix was no better — it faked torch through `sys.modules`, which depends on how the import happens rather than on what the code asks. `planner.have_torch()` is now a named function tests can patch directly. |

The pattern is the same every time: **an assumption true on the machine that
wrote the code, false everywhere else.** Adding tests does not find these;
changing environment does.

## Verified installation path

From a fresh clone and an empty venv, on Windows:

```bash
pip install -r requirements.txt     # requests + pytest only — torch is optional
python -m pytest -q                 # 458 pass, 22 clean skips (nebius x8, patch_ng x6, cryptography x6, mcp, nodus_agent)
python -m nge.demo_nebius --mock    # runs, produces its artefact
python -m nge.fetch_ckpt            # 988 MB, SHA256-verified, writes .nodus_plan_ckpt
```

`requirements.txt` declares only `requests` and `pytest`; torch is an optional
extra. That claim is checked, not assumed: the suite and the mock demo were run
in a venv containing nothing else.

## Coverage today

| path | Windows (local) | Ubuntu (CI) |
|---|---|---|
| unit tests (480 on 2026-10-03) | yes | yes — Python 3.10 / 3.11 / 3.12 |
| MCP client ↔ GPU MCP server | yes | yes |
| `--mock` demo | yes | yes |
| `--live` (real Nemotron + real sandboxes) | yes | yes — `live-smoke`, manual or weekday cron |
| `fetch_ckpt` (real 988 MB download) | yes | **no** |
| 324M planner actually loading and planning | yes | **no** — CI has no checkpoint and no torch |

The last two rows are the current blind spot: the checkpoint fetch and the real
planner are only ever exercised on one machine, running one OS.

## Running it elsewhere

`live-smoke` is the cheapest way to exercise the full `--live` path on Linux
without installing anything: Actions → `engine-tests` → **Run workflow**. It
forces `NGE_FLEET_MODE=mock`, so the cost is the Nemotron calls plus the
sandboxes the two shards run in — **no GPU is ever allocated**.

Local Linux was attempted and abandoned: WSL Ubuntu 24.04 here has neither
`pip` nor `python3-venv`, and Docker Desktop was not running. Both are fixable,
neither was worth changing someone's machine for while CI already covers the
same ground.

## Liens

- Suivi vivant : [`ENGINE_BACKLOG.md`](ENGINE_BACKLOG.md)
- Compute GPU : [`COMPUTE_GPU.md`](COMPUTE_GPU.md)
- Track juges : [`packages/engine/docs/NEBIUS_TRACK.md`](../packages/engine/docs/NEBIUS_TRACK.md)

## Token Factory nodes ≠ physical H100

`--live` with `fleet=nebius` provisions **Token Factory Contree microVMs**.
Contree's spawn API exposes CPU/disk limits only — **no GPU device passthrough**
today. Node ids like `nb-h100-00` are **labels**, not proof of an H100.

| `probe_kind` | Meaning | Heal on low efficiency? |
|--------------|---------|-------------------------|
| `nvidia-smi` | Real NVIDIA metrics (+ `gpu_name` / `gpu_class`) | Yes (class thresholds) |
| `cpu-fallback` | No driver/device — CPU load only (temp/power = 0) | **No** |
| `failed` | Probe did not run (e.g. wrong Contree `run` API) | **No** |
| `synthetic` | MockFleet demo numbers | Yes (demo feedback loop) |

`gpu_class`: `datacenter` (H100/A100/…) vs `consumer` (GeForce/RTX) vs `none` /
`synthetic`. Thresholds differ (e.g. throttle ~87 °C DC vs ~83 °C consumer).

### Image (`NGE_FLEET_IMAGE`)

Default: `python:3.12-slim`. You can point at another OCI tag Contree can
`images.use` / import (e.g. a CUDA base) — useful for deps — but a CUDA **name**
does **not** attach a GPU on TF. Heal stays gated unless you set
`NGE_FLEET_HAS_GPU=1` (only when you know the runtime exposes an NVIDIA device).

Real H100/H200 confirmation needs a **Nebius Compute GPU VM** (or future Contree
GPU support), not the default sandbox path.

### Preflight (no blind start)

Every orchestrated run prints a `[capabilities]` banner first:

- **host tools** — is `nvidia-smi` / `dcgmi` on the machine running the engine?
  (H100/H200 use `nvidia-smi` too; `dcgmi` is optional datacenter tooling.)
- **fleet expect** — mock → synthetic; TF → `cpu-fallback` unless
  `NGE_FLEET_HAS_GPU=1`.
- Hard gate: `NGE_REQUIRE_REAL_GPU=1` refuses start when heal would be blind.
