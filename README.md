# Nodus-GPU Engine

[![engine-tests](https://github.com/Rua987/nodus-gpu-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/Rua987/nodus-gpu-engine/actions/workflows/ci.yml)
[![python](https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12-blue)](pyproject.toml)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![tests](https://img.shields.io/badge/tests-43%20passing%20%C2%B7%20no%20network-brightgreen)](packages/engine/tests)

**Agentic engineering platform — Nebius "Coding & Agentic Engineering" track.**

A deterministic local planner decides *what* to do, Nemotron (tier-routed) decides
the *hard parts*, and a fleet of Nebius GPUs + Token Factory sandboxes actually
*runs the work* — isolated, monitored, and re-provisioned by the engine itself
when a node throttles.

```
Nodus 324M planner   ──▶  ordered tool names             [ brain / DSL ]
Nemotron @ Nebius    ──▶  routing: Ultra / Super / Nano  [ inference   ]
GPU fleet (Nebius)   ──▶  provision / monitor / migrate  [ infrastructure ]
Token Factory        ──▶  isolated exec + capability jail [ execution   ]
```

> **The 324M planner needs its weights.** They are ~988 MB and not in git, so
> without them the planner step falls back to a hand-written keyword heuristic
> — a real fallback, but *not* the model. Every run says which one produced the
> plan (`plan(nodus-324m)` vs `plan(heuristic)`, plus a `[planner] WARNING`
> line and a `plan_degraded` event), so this is never silent. To use the model:
>
> ```bash
> echo /path/to/checkpoint_sft_plan_v5.pt > packages/engine/.nodus_plan_ckpt
> # or: export NODUS_PLAN_CKPT=/path/to/checkpoint_sft_plan_v5.pt
> ```
>
> The two disagree — on `"Find the config file and read it"` the model answers
> `['bash']` where the heuristic guesses `['glob', 'read_file']`.

## Layout

| Path | What |
|------|------|
| [`packages/engine/`](packages/engine/) | **The project.** All new code (`nge`): Nebius backend, tier router, GPU fleet + Token Factory sandbox layers, capability jail, orchestrator, demo. |
| [`packages/nodus/`](packages/nodus/) | **Vendored, unmodified** snapshot of <https://github.com/Rua987/nodus> — the Nodus runtime (ReAct executor, `bridge/`, backends, MCP). The `nebius:` backend is added by a reversible monkey-patch, never an edit. See [`docs/VENDORING.md`](docs/VENDORING.md). |


The auto-fix loop's verification rules each come from a live run that broke without them — including a patch that repaired its target test while breaking 28 others, twelve of them path-security checks. The evidence is in [`docs/FIX_LOOP.md`](docs/FIX_LOOP.md).
## Quick start (mock — no credentials, no network)

```bash
cd packages/engine
pip install -r requirements.txt
python -m pytest -q                 # 43 tests
python -m nge.demo_nebius --mock    # -> out/report_<ts>.md  +  .html (self-contained)
```

The mock run: `plan (→Ultra)` → `gpu_provision(3×H100)` → 3 sandboxes run a
sharded pytest (commands vetted by the jail) → a hot node throttles → the engine
re-provisions and migrates that shard by itself → **the code agent proposes a
patch per failure, applies + re-tests it in a fresh sandbox, keeps the verified
ones** → `gpu_release` → consolidated report (triage + `fixes/*.patch`).

```bash
python -m nge.demo_nebius --mock --watch    # live fleet view: util/temp bars, migration, fixes
```

## The differentiators (all real in the mock demo)

1. **Code + Infrastructure in one loop** — `orchestrator._react_to_pressure`:
   GPU telemetry drives compute reallocation while the plan executes.
2. **A code agent, not just a test runner** — `orchestrator._attempt_fixes`:
   propose a patch → `git apply` + re-test in a fresh GPU sandbox → keep only
   what re-tests green; unverifiable failures are flagged for a human.
3. **Multi-tier Nemotron routing** — `nge/router.py`: Ultra 550b (plan),
   Super 120b (slot-fill / triage / patch), Nano 30b (fast telemetry checks).
4. **Deterministic execution + capability jail** — `nge/policy.py` gates every
   LLM-proposed shell command; the runtime stays strict and reproducible.

Full judge-facing doc: [`packages/engine/docs/NEBIUS_TRACK.md`](packages/engine/docs/NEBIUS_TRACK.md).
Architecture: [`packages/engine/docs/ARCHITECTURE.md`](packages/engine/docs/ARCHITECTURE.md).

## Live path

`packages/engine/docs/NEBIUS_TRACK.md` lists what's wired vs. skeleton
(`NebiusFleet` network calls and `TokenFactorySandbox._build_client` are the
remaining TODOs; everything else runs).

## License

MIT — see [`LICENSE`](LICENSE). The vendored `packages/nodus/` subtree is also
MIT (Copyright (c) 2024 Temple IAM), with its own [`packages/nodus/LICENSE`](packages/nodus/LICENSE).
