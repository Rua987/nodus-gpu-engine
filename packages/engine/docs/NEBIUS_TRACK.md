# Nebius track — Coding & Agentic Engineering

Single source of truth for judges of the **Nodus-GPU Engine** submission.
This is a **separate submission** from the Agentic Cinema one (which stays
Google-only and untouched — see `packages/nodus/AGENTIC_CINEMA.md`).

## What it is

An **agentic engineering platform**: not an API wrapper, a full stack from the
applicative DSL down to GPU resource management.

- **Nodus** (local 324M PyTorch planner) turns a natural-language engineering
  task into a deterministic, ordered sequence of tool steps.
- **Nemotron** (via **Nebius Token Factory**, OpenAI-compatible endpoint),
  **tier-routed** by `nge/router.py`: Ultra 550b for planning/orchestration,
  Super 120b for slot-fill/triage, Nano 30b for fast telemetry checks.
- **temple-iam-gpu-agents** is repurposed as the **infrastructure arm**:
  provision / allocate / monitor / release a fleet of **Nebius cloud GPUs**.
  The orchestrator runs a **feedback loop** — when a node throttles or drops
  below an efficiency floor, the engine re-provisions and migrates that shard
  by itself (the "agents self-manage their own GPU compute" claim, made real).
- **Token Factory Sandboxes** isolate and execute each agent's code on a pinned
  GPU node, behind a **capability jail** (`nge/policy.py`) that vets every
  LLM-proposed shell command.

## Judges — run the demo (no credentials)

```bash
cd packages/engine
pip install -r requirements.txt          # requests + pytest only
python -m pytest -q                       # 43 tests, no network
python -m nge.demo_nebius --mock          # deterministic end-to-end
```

Expected: `plan (route→Ultra) → gpu_provision(3×H100) → 3 sandboxes run a
sharded pytest (commands vetted by the jail) → telemetry polls → node
nb-h100-02 throttles → engine re-provisions nb-h100-03 and migrates shard 2 →
gpu_release → out/report_<ts>.md`, **exit 0**. The report has the shard table
(with the migration), the "Self-managed compute" section (model routing +
remediations), consolidated failures with proposed fixes, and the JSON event
log.

## Judges — live run (Nebius)

```bash
cp .env.example .env
#  NEBIUS_API_KEY=...           (Nebius Token Factory key)
#  NEBIUS_BASE_URL=https://api.tokenfactory.us-central1.nebius.com/v1
#  NEMOTRON_MODEL=nebius:nvidia/nemotron-3-super-120b-a12b
#  TOKEN_FACTORY_API_KEY=...    (ConTree SDK: pip install contree-sdk)
#  NEBIUS_PROJECT_ID=... NEBIUS_REGION=eu-north1
python -m nge.demo_nebius --live
```

### Confirmed Nebius facts (2026-09)

- "AI Studio" is now **Token Factory**. OpenAI-compatible base URL:
  `https://api.tokenfactory.us-central1.nebius.com/v1`
- Nemotron 3 on Token Factory: `nvidia/nemotron-3-super-120b-a12b` (default),
  `nvidia/nemotron-3-nano-30b-a3b`, and **Nemotron 3 Ultra 550b** (long-running
  autonomous agents - exact id string still to grab from the console).
- Sandboxes are driven by the **ConTree SDK** (`contree-sdk`,
  `Contree` / `ContreeSync`, `images.use(img).run(shell=...).wait()`).
  `nge/sandbox/token_factory.py` implements create/put/exec/collect/destroy
  against that surface; only the authenticated client constructor
  (`_build_client`) is left as a TODO.

`--live` sets `NGE_TRACK=nebius` (guard: refuses any non-`nebius:` LLM), routes
slot-fill through `nodus_agent._chat`, and selects `NebiusFleet` +
`TokenFactorySandbox`.

## Stack map

| Layer | Technology | Role |
|-------|-----------|------|
| Planner | Local 324M (PyTorch), `packages/nodus` | Ordered tool **names** |
| Routing | `nge/router.py` | Nemotron Ultra / Super / Nano per decision kind |
| Orchestrator + slot-fill | **Nemotron @ Nebius Token Factory** | Decisions + argument fill |
| Self-managed compute | `orchestrator._react_to_pressure` | Throttle → re-provision + migrate shard |
| GPU fleet | **Nebius Cloud** GPU instances | Provision / monitor / release |
| Capability jail | `nge/policy.py` | Vet every LLM shell command before exec |
| Execution isolation | **Nebius Token Factory Sandboxes** (ConTree SDK) | Per-shard command execution |
| Observability | Nodus event log (Grafana MCP reusable) | Per-event annotations |

## What is real vs. skeleton in this milestone

| Real (tested in CI, no network — 43 tests) | Skeleton (documented) |
|---|---|
| `nebius:` backend + reversible register shim | `NebiusFleet` network calls |
| Nemotron tier router (`nge/router.py`) | `TokenFactorySandbox._build_client` (auth wiring only) |
| Telemetry feedback loop: throttle → re-provision + migrate | Nemotron planner fallback beyond stub |
| Capability jail (`nge/policy.py`) enforced in `run_in_sandbox` | Grafana live wiring, demo video |
| `MockFleet` (deterministic hot-node) + telemetry scoring | — |
| `TokenFactorySandbox` create/put/exec/collect/destroy vs ConTree (fake-SDK tested) | — |
| 5 GPU tools + stdlib MCP server · orchestrator · artifact · event log | — |

## Build-next checklist (live path)

1. `nge/fleet/nebius.py` — Nebius Compute: create GPU instances (preset
   `gpu-h100-sxm`), poll DCGM/Observability for telemetry, delete on release.
   (Or back the fleet with a pool of ConTree sandbox sessions — no IaaS creds.)
2. `nge/sandbox/token_factory.py::_build_client` — construct the authenticated
   `ContreeSync` client (`pip install contree-sdk`). The rest is already wired.
3. Grab the exact **Nemotron 3 Ultra 550b** model id from the Token Factory
   console; set `NEMOTRON_MODEL` (Super 120b is the working default).
4. Point Nodus' MCP at `nge/tools/mcp.json` and run a real
   `nodus_agent.run_agent(..., model=NEMOTRON_MODEL, mcp_servers="nge-gpu")`.
5. Grafana Cloud annotations from the orchestrator event log; record the demo.

## Why it wins

- **Technical implementation** — full-stack mastery: applicative DSL → LLM
  orchestration → GPU resource lifecycle → sandboxed execution.
- **Complete product** — an Agentic Engineering Platform, not a prompt wrapper.
- **Impact** — running fleets of complex agents on open, scalable cloud GPU
  infrastructure is exactly the track's problem statement.
