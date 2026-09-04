# Pipeline validation runs

Record of end-to-end runs used to validate the pipeline.

> **Superseded on 2026-09-03.** These runs were made while Token Factory
> Sandboxes beta access was still pending, so the infrastructure below is
> mocked. Access has since been granted and `--live` runs for real — against
> real sandboxes, in CI as well (`live-smoke`). Kept as the record of what was
> verified before that, and because switching the sandboxes on immediately
> exposed four bugs the mock had been hiding: see
> [`../../docs/ENVIRONMENTS.md`](../../docs/ENVIRONMENTS.md).

Two real LLMs were in the loop across these runs: Nemotron via Token Factory
(cloud) and a local Ollama model driving the real Nodus agent.

Date: 2026-09-02 · engine @ commit `1907861` · 70 unit tests green + CI.

---

## Run A — real Nemotron, simulated infra

```bash
NGE_FLEET_MODE=mock NGE_SANDBOX=mock python -m nge.demo_nebius --live
# [live] Nemotron=nebius:nvidia/nemotron-3-super-120b-a12b  fleet=mock  sandbox=mock
# exit 0
```

**Real:** 6 Nemotron Super calls (3 slot-fill + 3 patch proposals) via the
`nebius:` backend; `register.apply()` + `register.verify()`; tier routing;
capability jail; the telemetry feedback loop; the auto-fix loop; and the
**HTML report rendering real model output**.

**Still mock:** fleet telemetry, sandbox execution, and therefore the
`verified` verdict (decided by the fixture `fixable` flag, not by running the
real patch).

### Evidence

- Slot-fill produced 3 distinct, plausible commands (all passed the jail):
  - `pytest packages/nodus/tests -v --tb=short --gpu --junitxml=shard0_report.xml`
  - `pytest packages/nodus/tests -v > shard1_test_results.txt 2>&1`
  - `pytest packages/nodus/tests --tb=short -v > /tmp/pytest_shard2.log 2>&1`
- Nemotron patches (real unified diffs, written to `out/fixes/*.patch`):
  - `test_upload_mock` (`KeyError: 'GCLOUD_BUCKET'`) →
    `monkeypatch.setenv('GCLOUD_BUCKET', 'test-bucket')` — a genuinely sensible fix
  - `test_roundtrip` → inserts `mem.save()` before `mem.dump()`
  - `test_carry_path` → only edited the assertion (`'server.py'` → `'server.pyc'`)
    — the model cheated; a real sandbox verify would catch this
- Divergence from pure `--mock` (proves real LLM output flows through):
  shard durations 3.3 / 1.7 / 2.8 s (vs canned 0.5 / 0.9 / 1.5), 3 unique
  failures instead of 4 (different commands → different mock-sandbox seeds).
- `nb-h100-02 throttle (90.4 °C, 730 W) → re-provisioned nb-h100-03`, shard 2
  migrated by the engine.
- HTML (`out/report_<ts>.html`, ~15 KB, self-contained): tier badges, shard
  table with the migration, the real Nemotron diffs, health colours
  (2 OK / 1 WARM / 1 THROTTLE), full event log.

---

## Run B — real Nodus ReAct loop + real MCP + local model

```bash
python -m nge.demo_nebius --local --model granite4.1:3b --max-rounds 10
# exit 0
```

**Real:** `nodus_agent.run_agent` (the vendored ReAct loop); Nodus'
`McpBridge` spawning `nge/tools/gpu_mcp_server.py` as a stdio MCP subprocess
and loading its 5 tools; a local Ollama model making real tool calls.

**Still mock:** the fleet + sandbox behind the tools (`MockFleet` /
`MockSandbox`).

### Evidence (transcript excerpt)

```
[agent] MCP (nge-gpu): 5 tool(s) from out/mcp.local.json
[agent] model: granite4.1:3b
-- round 1 --
[agent] TOOL nge-gpu.gpu_provision({"gpu_type": "H100", "n": 2})
[agent] OK { "provisioned": 2, "nodes": [nb-h100-00, nb-h100-01] }
[agent] TOOL nge-gpu.run_in_sandbox({"command": "echo benchmark-ok", "node_id": "nb-h100-00"})
[agent] OK { "exit_code": 0, "stdout": "benchmark-ok" }
-- round 2 --
[agent] OK final answer
rounds=2  tool_calls=2  stopped=done
answer: Two H100 nodes were provisioned (nb-h100-00, nb-h100-01) and the
        sandbox on node nb-h100-00 printed "benchmark-ok".
```

---

## Coverage matrix

| Component | Run A | Run B | Unit tests | Against real Nebius |
|---|:-:|:-:|:-:|:-:|
| Planner (heuristic / 324M) | ✓ | ✓ | ✓ | n/a |
| `nebius:` backend → Nemotron | ✓ | — | mocked HTTP | **✓ (separate Nemotron call, verified)** |
| Tier router (Ultra/Super/Nano) | ✓ | — | ✓ | — |
| Nodus ReAct loop (`run_agent`) | — | ✓ | — | — |
| Real MCP server ↔ `McpBridge` | — | ✓ | ✓ (`test_mcp_bridge_integration`) | — |
| Capability jail | ✓ | ✓ | ✓ | — |
| Telemetry feedback loop (migrate) | ✓ | — | ✓ | — |
| Auto-fix loop (patch → apply → re-test) | ✓ | — | ✓ | — |
| HTML report renders real data | ✓ | — | ✓ | — |
| `NebiusFleet` network calls | mock | mock | fake-SDK | **pending beta access** |
| `TokenFactorySandbox` network calls | mock | mock | fake-SDK | **pending beta access** |

## Blocker

Token Factory Sandboxes is in beta — `Request access` at
<https://tokenfactory.nebius.com/sandboxes/about> (free, no credits). Verified
against the account: auth + client construction succeed (`WhoAmI` returns), the
key's `permissions` are all `False` until access is granted. When
`permissions.spawn` flips true:

```bash
python -m nge.sandbox.token_factory          # first real sandbox
python -m nge.demo_nebius --live             # full real pipeline + real GPU telemetry in the HTML
```
