# Nodus-GPU Engine

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

## Layout

| Path | What |
|------|------|
| [`packages/engine/`](packages/engine/) | **The project.** All new code (`nge`): Nebius backend, tier router, GPU fleet + Token Factory sandbox layers, capability jail, orchestrator, demo. |
| [`packages/nodus/`](packages/nodus/) | **Vendored, unmodified** snapshot of <https://github.com/Rua987/nodus> — the Nodus runtime (ReAct executor, `bridge/`, backends, MCP). The `nebius:` backend is added by a reversible monkey-patch, never an edit. See [`docs/VENDORING.md`](docs/VENDORING.md). |

## Quick start (mock — no credentials, no network)

```bash
cd packages/engine
pip install -r requirements.txt
python -m pytest -q                 # 43 tests
python -m nge.demo_nebius --mock    # -> packages/engine/out/report_<ts>.md
```

The mock run: `plan (→Ultra)` → `gpu_provision(3×H100)` → 3 sandboxes run a
sharded pytest (commands vetted by the jail) → a hot node throttles → the engine
re-provisions and migrates that shard by itself → `gpu_release` → consolidated
triage report.

## The differentiators (all real in the mock demo)

1. **Code + Infrastructure in one loop** — `orchestrator._react_to_pressure`:
   GPU telemetry drives compute reallocation while the plan executes.
2. **Multi-tier Nemotron routing** — `nge/router.py`: Ultra 550b (plan),
   Super 120b (slot-fill / triage), Nano 30b (fast telemetry checks).
3. **Deterministic execution + capability jail** — `nge/policy.py` gates every
   LLM-proposed shell command; the runtime stays strict and reproducible.

Full judge-facing doc: [`packages/engine/docs/NEBIUS_TRACK.md`](packages/engine/docs/NEBIUS_TRACK.md).
Architecture: [`packages/engine/docs/ARCHITECTURE.md`](packages/engine/docs/ARCHITECTURE.md).

## Live path

`packages/engine/docs/NEBIUS_TRACK.md` lists what's wired vs. skeleton
(`NebiusFleet` network calls and `TokenFactorySandbox._build_client` are the
remaining TODOs; everything else runs).
