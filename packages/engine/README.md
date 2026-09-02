# Nodus-GPU Engine (`nge`)

**Agentic engineering platform for the Nebius "Coding & Agentic Engineering" track.**

A deterministic local planner decides *what* to do, Nemotron decides the *hard
parts*, and a fleet of Nebius GPUs + Token Factory sandboxes actually *runs the
work* — isolated, monitored, and torn down when done.

```
Nodus 324M planner   ──▶  ordered tool names            [ brain / DSL ]
Nemotron @ Nebius    ──▶  orchestration + arg slot-fill [ inference   ]
GPU fleet (Nebius)   ──▶  provision / monitor / release [ infrastructure ]
Token Factory        ──▶  isolated command execution    [ execution   ]
```

## Isolated integration

`packages/nodus/` and `packages/gpu-agents/` are **vendored unchanged**. Everything
new is in this package. The `nebius:` LLM backend is added to Nodus by a
**reversible monkey-patch** (`nge/backends/register.py`), never an edit — so the
existing Agentic Cinema (Google/Vertex) demo keeps working.

## Quick start (mock — no credentials, no network)

```bash
cd packages/engine
pip install -r requirements.txt
python -m pytest -q
python -m nge.demo_nebius --mock
# -> packages/engine/out/report_<ts>.md
```

The mock run: `plan` → `gpu_provision(3×H100)` → 3 sandboxes run a sharded pytest
→ telemetry polls → **a hot node throttles → the engine re-provisions and
migrates that shard by itself** → `gpu_release` → consolidated triage report.
Fully deterministic.

### Three things this is, that an API wrapper is not

1. **Code + Infrastructure in one loop** — the Nodus DSL plan is executed while
   the engine watches GPU telemetry and reallocates compute under thermal /
   efficiency pressure (`orchestrator._react_to_pressure`).
2. **Multi-tier Nemotron routing** — `nge/router.py`: Ultra 550b for planning,
   Super 120b for slot-fill / triage, Nano 30b for fast telemetry checks. Not
   one model for everything.
3. **Deterministic execution + capability jail** — the runtime stays strict and
   reproducible; every LLM-proposed shell command passes `nge/policy.py` before
   it can touch a sandbox.

## Local end-to-end (real ReAct loop, no cloud, no credits)

```bash
pip install -r requirements-local.txt   # adds the mcp SDK (1.x)
ollama pull qwen3.5:2b                   # any local model works
python -m nge.demo_nebius --local
```

`--local` runs the **real Nodus ReAct executor** driven by a local Ollama model
(Nemotron stand-in). Nodus connects to `nge/tools/gpu_mcp_server.py` — a real
MCP server on the official SDK — and the model drives `nge-gpu.gpu_provision`,
`gpu_status`, `run_in_sandbox`, `gpu_release` over stdio MCP. Same tool + MCP
wiring the Nebius path uses; only the model id and fleet/sandbox mode change for
`--live`. The `test_mcp_bridge_integration.py` suite exercises this path in CI
(no Ollama needed).

Real transcript (`qwen3.5:2b`, 3 rounds):

```
[agent] MCP (nge-gpu): 5 tool(s)
round 1: nge-gpu.gpu_provision({"n": 2, "gpu_type": "H100"})       -> 2 nodes ready
round 2: nge-gpu.run_in_sandbox({"command": "echo benchmark-ok",
                                 "node_id": "nb-h100-00"})          -> exit 0, "benchmark-ok"
rounds=3  tool_calls=2  stopped=done
answer: Provisioned 2 H100 nodes (nb-h100-00, nb-h100-01); benchmark on
        nb-h100-00 returned exit_code 0, "benchmark-ok".
```

## Live path (skeleton)

```bash
cp .env.example .env          # set NEBIUS_API_KEY, NEMOTRON_MODEL, TOKEN_FACTORY_*
python -m nge.demo_nebius --live
```

`--live` sets `NGE_TRACK=nebius` (backend guard: only `nebius:` models),
routes slot-fill to Nemotron via `nodus_agent._chat`, and switches the fleet /
sandbox to the real backends. Those network calls raise `NotImplementedError`
with the exact Nebius / Token Factory operation to implement — see
[`docs/NEBIUS_TRACK.md`](docs/NEBIUS_TRACK.md).

## Layout

| Path | Role |
|------|------|
| `nge/config.py` | env-driven config; everything defaults to `mock` |
| `nge/backends/nebius.py` | Nebius AI Studio (OpenAI-compatible) → Nemotron |
| `nge/backends/register.py` | reversible `nebius:` route into vendored Nodus |
| `nge/fleet/` | `GpuFleet` iface · `MockFleet` · `NebiusFleet` (skeleton) · `telemetry` |
| `nge/sandbox/` | `Sandbox` iface · `MockSandbox` · `TokenFactorySandbox` (skeleton) |
| `nge/tools/handlers.py` | the 5 tools: `gpu_provision/status/allocate/release`, `run_in_sandbox` (+ capability jail) |
| `nge/tools/gpu_mcp_server.py` | MCP server — real `mcp` SDK (`FastMCP`) + stdlib JSON-RPC fallback |
| `nge/mcp_config.py` | emits a resolved MCP config for Nodus' `McpBridge` |
| `nge/router.py` | Nemotron tier routing (ultra / super / nano) per decision kind |
| `nge/policy.py` | capability jail — allow/deny gate for sandbox commands |
| `nge/planner.py` | Nodus 324M plan → heuristic → Nemotron fallback |
| `nge/orchestrator.py` | the run: plan → fleet frame → shards → **telemetry feedback loop** → triage → artifact |
| `nge/demo_nebius.py` | `--mock` / `--live` entrypoint |
| `scenarios/` | demo scenario(s) |
| `docs/ARCHITECTURE.md` | layer contract + data flow |
| `docs/NEBIUS_TRACK.md` | judge-facing: run it, stack map, what to build next |
