# Architecture — Nodus-GPU Engine

## Layers

| # | Layer | Component | Owns |
|---|-------|-----------|------|
| 1 | Brain / DSL | `nge/planner.py` → `packages/nodus/nodus_plan_local.py` | NL task → **ordered tool names** (fixed 8-tool coding vocab). Deterministic; no args. |
| 2 | Inference | `nge/backends/nebius.py` + `nge/router.py` → `packages/nodus/nodus_backends._chat_openai_compatible` | Nemotron @ Nebius, **tier-routed**: Ultra 550b (plan/orchestrate), Super 120b (slot-fill/triage), Nano 30b (telemetry/healthcheck). |
| 3 | Runtime | `nge/orchestrator.py` | Deterministic infra frame around the plan; fan-out; **feedback loop** (`_react_to_pressure`: throttling node → re-provision + migrate shard); **auto-fix loop** (`_attempt_fixes`: patch → `git apply` + re-test in a fresh sandbox → keep only verified); event log. |
| 3b | Capability jail | `nge/policy.py` | Allow/deny gate every LLM-proposed shell command hits before a sandbox runs it. |
| 4 | Infrastructure | `nge/fleet/` (`MockFleet` \| `NebiusFleet`) | `provision(n)` / `status()` / `allocate()` / `release()` of Nebius GPU nodes + telemetry. |
| 5 | Execution | `nge/sandbox/` (`MockSandbox` \| `TokenFactorySandbox`) | Isolated `create → put_files → exec → collect → destroy` on a pinned node. |
| 6 | Tools bridge | `nge/tools/gpu_mcp_server.py` (real `mcp` SDK) + `nge/mcp_config.py` | Exposes layers 4–5 as MCP tools. Nodus' `McpBridge` (`ClientSessionGroup`, SDK 1.x) spawns it over stdio; the model calls `nge-gpu.*`. Proven by `test_mcp_bridge_integration.py` (CI) and `demo_nebius --local` (real ReAct loop, local Ollama model). |

`demo_nebius` has three entrypoints against the *same* layers 4–6:
`--mock` (deterministic orchestrator, CI), `--local` (real Nodus ReAct loop +
local model over real MCP — no cloud), `--live` (Nemotron @ Nebius + real
fleet/sandbox — skeleton).

## Data flow (the demo scenario)

```
scenario.json
   │  task, shards=3, gpu_type=H100, target=packages/nodus/tests
   ▼
planner.plan(task) ──────────────▶ ["bash","edit_file","write_file"]   (source: nodus-324m | heuristic)
   ▼
orchestrator.run()
   ├─ gpu_provision(n=3, H100) ─────────▶ fleet: [nb-h100-00, nb-h100-01, nb-h100-02]
   ├─ route("plan") ─────────────────────────▶ Nemotron Ultra 550b   [model_route event]
   ├─ for i in 0..2:
   │     gpu_allocate("shard-i")
   │     route("slotfill") ──────────────────▶ Nemotron Super 120b
   │     cmd = slot-fill(task, plan, i)         # chat_fn=Nemotron in live; template in mock
   │     policy.check_command(cmd) ──────────▶ capability jail (deny rm -rf, curl|bash, git push, …)
   │     run_in_sandbox(cmd, node=nb-h100-0i)   # MockSandbox → deterministic pytest output
   │     gpu_status(node)  ───────────────────▶ util/mem/temp/power/health/efficiency  → event
   │     _react_to_pressure(shard):             # ── feedback loop ──
   │        if health==throttle or eff<0.25:
   │           route("healthcheck") ─────────▶ Nemotron Nano 30b
   │           gpu_provision(1) + migrate shard onto the fresh node   [gpu_remediation event]
   ├─ triage(shard stdout)  ─────────────────▶ dedup FAILED lines
   ├─ _attempt_fixes(failures[:3]):             # ── auto-fix loop (code agent) ──
   │     route("triage") ────────────────────▶ Nemotron Super 120b → unified diff
   │     gpu_provision(1) + run_in_sandbox("git apply fix.patch && pytest -k <t>")
   │     keep patch iff exit==0               [fix_attempt / fix_verified events]
   ├─ gpu_release()  ────────────────────────▶ all nodes gone (billing stops)
   └─ write out/report_<ts>.md + out/fixes/*.patch  ─▶ artifact (+ full JSON event log)
```

## Interface contracts

- **`GpuFleet`** (`nge/fleet/base.py`): `provision(n, gpu_type) -> [GpuNode]`,
  `status(node_id=None) -> [GpuNodeStatus]`, `allocate(job) -> GpuNode`,
  `release(node_ids=None) -> [str]`. `MockFleet` telemetry is a pure function of
  `(node index, poll tick)` → reproducible.
- **`Sandbox`** (`nge/sandbox/base.py`): `create(SandboxSpec) -> id`,
  `put_files(id, {path: content})`, `exec(id, cmd, timeout) -> ExecResult`,
  `collect(id, paths) -> {path: content}`, `destroy(id)`.
- **Tools** (`nge/tools/handlers.py`): five JSON-in/JSON-out functions sharing one
  process-wide `EngineState` (fleet + sandbox + provisioned nodes). `reset_state()`
  between runs. Schemas in `TOOL_SCHEMAS` (Nodus/OpenAI shape) and re-exported as
  MCP `inputSchema` by the server.
- **Backend** (`nge/backends/register.py`): `apply()` wraps
  `nodus_backends.detect_backend` + `chat_api` (and the copies bound in
  `nodus_agent`) to recognise `nebius:`; `restore()` fully undoes it.

## Shard state across a migration

When a node throttles, the migrated shard **restarts from scratch** on the fresh
node (the orchestrator re-issues the same command). This is correct for the
stateless shards here (an idempotent `pytest` run). Stateful workloads would
need **resume-from-snapshot**, which is exactly the primitive Nebius Token
Factory Sandboxes provide (ConTree's git-like branching / state restore) — so
the design path is: restart now, `fork`/`restore` the sandbox when running on
Token Factory. Not yet wired.

## Why the planner does not plan GPU steps

The 324M model was trained on exactly 8 coding tools
(`bridge/tool_schemas.json`). Fleet / sandbox lifecycle is **not** in its
vocabulary, so the orchestrator adds it deterministically
(`provision → [plan steps, executed in sandbox] → collect → release`) and lets
Nemotron handle any dynamic decision. This matches the Nodus law: *the plan is a
suggestion of names; the executor keeps control of the real arguments.*
