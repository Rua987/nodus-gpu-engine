# Nebius track — Coding & Agentic Engineering

Single source of truth for judges of the **Nodus-GPU Engine** submission.
This is a **separate submission** from the Agentic Cinema one (which stays
Google-only and untouched — see `packages/nodus/AGENTIC_CINEMA.md`).

## What it is

An **agentic engineering platform** for the "**Coding** & Agentic Engineering"
track: the agent doesn't just run tests across a GPU fleet — it **patches the
failures and verifies each fix on a clean GPU**. Not an API wrapper, a full
stack from the
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
python -m pytest -q                       # 398 tests, no network
python -m nge.demo_nebius --mock          # deterministic end-to-end
python -m nge.demo_nebius --mock --watch  # same run, live fleet view
# Judge film with verified patches (keyword plan unlocks edit_file):
python -m nge.demo_nebius --mock --watch --heuristic-plan
```

Oral script: [`JUDGE_DRY_RUN.md`](JUDGE_DRY_RUN.md). Capture with autofix:
`out/report_20260905T232100Z.html` (2/3 verified + GPU migrate).

### Optional — real ReAct loop, no cloud

```bash
pip install -r requirements-local.txt    # + mcp SDK
ollama pull qwen3.5:2b
python -m nge.demo_nebius --local         # Nodus ReAct loop, local model, real MCP
```

The local model drives `nge-gpu.gpu_provision / gpu_status / run_in_sandbox /
gpu_release` over a real MCP stdio connection — the same tool wiring `--live`
uses with Nemotron. CI covers this path headlessly via
`test_mcp_bridge_integration.py` (Nodus' MCP client ↔ our MCP server, no model).

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
- Nemotron 3 on Token Factory (ids case-sensitive from `/v1/models`):
  `nvidia/nemotron-3-super-120b-a12b` (default),
  `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`,
  `nvidia/Nemotron-3-Ultra-550b-a55b`.
- Sandboxes are driven by the **ConTree SDK** (`contree-sdk`, `ContreeSync`,
  `images.use(img).session().run(args=["/bin/sh","-c",cmd], files={...}).wait()`).
  Auth = `IAMAuth(token, project_id, base_url=".../sandboxes/")` (shared by
  `nge/nebius_client.py`).
- **Sandboxes access is granted** on this key: `permissions` reports
  `spawn: True`. `python -m nge.sandbox.token_factory` spawns a real sandbox,
  uploads files and runs commands in it.
- `NebiusFleet` and `TokenFactorySandbox` are both implemented against ConTree
  and share auth. `NebiusFleet` telemetry = an `nvidia-smi` (or CPU-fallback)
  probe run inside each node.
- The image is bare: no pytest, no dependencies, **no git and no patch**. The
  orchestrator ships the source tree, installs the requirements and applies
  patches with `patch-ng` — see [`docs/FIX_LOOP.md`](../../../docs/FIX_LOOP.md).

`--live` sets `NGE_TRACK=nebius` (guard: refuses any non-`nebius:` LLM), routes
slot-fill / patch through `nge.backends.nebius.chat_nebius` (capped
`max_tokens` + usage ledger), and selects `NebiusFleet` +
`TokenFactorySandbox`. `NGE_FLEET_MODE=mock` pins just the fleet ledger back to
mock for a partial-real run.

### Tier ≠ provider (honest routing)

- **tier** (`ultra` / `super` / `nano`) = *role* of the decision kind in
  `router.py` (plan→ultra, slotfill/triage→super, healthcheck→nano).
- **model** = Token Factory id actually billed (ledger / report).
- **No** silent failover Super→Nano if Super returns 429/5xx: event
  `model_unavailable`, decision fails honestly.
- Patch cut by `max_tokens` → `patch_truncated` (not retried as empty);
  slot-fill cut → `slotfill_truncated`. Override the patch ceiling (8192)
  with `NGE_PATCH_MAX_TOKENS`.
- **Nemotron 3 reasons before answering, inside the same `max_tokens`.**
  Measured live: short replies (slot-fill, mission) were 100% reasoning and
  empty at 256, so they run with `enable_thinking: false`; patches keep
  reasoning (it stopped invented context) with room for it. Per class:
  `NGE_THINKING_SHORT` / `NGE_THINKING_PATCH` = `on` / `off` / `model`.
  `reasoning_tokens` is in the usage line and on the truncation events.
  Evidence: [`docs/FIX_LOOP.md`](../../../docs/FIX_LOOP.md),
  *Reasoning eats the token ceiling*.
- **DeepSeek / non-Nebius models**: blocked when `NGE_TRACK=nebius`. Personal
  multi-provider experiments stay off the submission path:
  `python -m nge.demo_nebius --local` (Ollama) or `--deepseek` (API). Both
  refuse to start if `NGE_TRACK=nebius` is set.
- Fleet telemetry: see [`ENVIRONMENTS.md`](../../../docs/ENVIRONMENTS.md)
  (« Token Factory nodes ≠ physical H100 »). Event `gpu_telemetry_non_gpu`
  means heal was skipped on purpose. Probe uses Contree ``shell=``; slim TF
  nodes report ``cpu-fallback``. ``NGE_FLEET_IMAGE`` selects the OCI tag;
  ``NGE_FLEET_HAS_GPU=1`` only when a real NVIDIA device is present.


## Stack map

| Layer | Technology | Role |
|-------|-----------|------|
| Planner | Local 324M (PyTorch), `packages/nodus` | Ordered tool **names** |
| Routing | `nge/router.py` | Nemotron Ultra / Super / Nano per decision kind |
| Orchestrator + slot-fill | **Nemotron @ Nebius Token Factory** | Decisions + argument fill |
| Self-managed compute | `orchestrator._react_to_pressure` | Throttle → re-provision + migrate shard |
| Code agent | `orchestrator._attempt_fixes` | Per failure: patch → apply with `patch-ng` → re-run the whole suite → keep only what breaks nothing else |
| GPU fleet | **Nebius Cloud** GPU instances | Provision / monitor / release |
| Capability jail | `nge/policy.py` | Vet every LLM shell command before exec |
| Execution isolation | **Nebius Token Factory Sandboxes** (ConTree SDK) | Per-shard command execution |
| Observability | Nodus event log (Grafana MCP reusable) | Per-event annotations |

## What runs for real

Sandboxes beta access landed, so `--live` is no longer a skeleton. 398 tests,
plus an MCP integration job and `live-smoke` — the full pipeline against real
sandboxes on Ubuntu, on demand and on a weekday cron.

| Verified live | Still open |
|---|---|
| `nebius:` backend + reversible register shim | Verification covers `packages/nodus` only |
| Nemotron tier router (`nge/router.py`) | Hunks with no file header are not recovered |
| 324M planner loading real weights (`nge/fetch_ckpt.py`) | Nemotron sometimes returns nothing (4 retries, 2s backoff; measured) |
| `TokenFactorySandbox` — auth, spawn, exec, file upload | `fetch_ckpt` and the planner are only exercised on Windows |
| Real sharding: files split round-robin, distinct commands | resume-from-snapshot on migration (needs Token Factory branching) |
| Feedback loop: throttle → re-provision + migrate | Grafana live wiring |
| Auto-fix loop: patch applied and re-verified against the whole suite | — |
| Capability jail enforced in `run_in_sandbox` | — |

Each verification rule carries the live failure that produced it in
[`docs/FIX_LOOP.md`](../../../docs/FIX_LOOP.md); where this has been run and
what each environment caught is in
[`docs/ENVIRONMENTS.md`](../../../docs/ENVIRONMENTS.md).
| `NebiusFleet` + `TokenFactorySandbox` vs real ConTree SDK — auth verified, fake-SDK tested | — |
| Real MCP server (`mcp` SDK) ↔ Nodus `McpBridge` — `test_mcp_bridge_integration` | — |
| `demo_nebius --local`: real Nodus ReAct loop drives `nge-gpu.*` via a local model | — |
| 5 GPU tools · orchestrator · artifact · event log | — |

## Build-next checklist (live path)

1. ~~Request Sandboxes beta access~~ — **granted**; `--live` runs.
2. `python -m nge.sandbox.token_factory` — real sandbox smoke (auth + spawn +
   exec + file upload), passing.
3. Grab the exact **Nemotron 3 Ultra 550b** model id from the Token Factory
   console; set `NEMOTRON_MODEL` (Super 120b is the working default, verified).
4. Point Nodus' MCP at `nge/tools/mcp.json` and run a real
   `nodus_agent.run_agent(..., model=NEMOTRON_MODEL, mcp_servers="nge-gpu")`.
5. Grafana Cloud annotations from the orchestrator event log; record the demo.

## Why it wins

- **Technical implementation** — full-stack mastery: applicative DSL → LLM
  orchestration → GPU resource lifecycle → sandboxed execution.
- **Complete product** — an Agentic Engineering Platform, not a prompt wrapper.
- **Impact** — running fleets of complex agents on open, scalable cloud GPU
  infrastructure is exactly the track's problem statement.
