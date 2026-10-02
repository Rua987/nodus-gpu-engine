# Fleet test triage - 20261002T054700Z

**Task:** Run the failing pytest suite across the GPU fleet, triage, fix, report.

- Plan (heuristic): `['bash', 'edit_file', 'write_file']`  **- not the 324M planner**
  - 324M planner checkpoint NOT FOUND at __nge_force_heuristic__\missing.pt - planning falls back to the hand-written keyword heuristic. Point at the weights with NODUS_PLAN_CKPT=/path/to/checkpoint_sft_plan_v5.pt, or write that path into packages/engine/.nodus_plan_ckpt
- Fleet mode: `mock` | Sandbox: `token_factory`
- Shards: 2 | Unique failures: 5 | Auto-fixed: 1

## Shards

| # | node | exit | dur (s) | failures |
|---|------|------|---------|----------|
| 0 | `nb-h100-00` | 1 | 6.134 | 2 |
| 1 | `nb-h100-01` | 1 | 6.156 | 3 |

## Self-managed compute

**Model routing (Nemotron tiers):**

- `ultra` → plan
- `super` → slotfill, triage

**GPU pressure remediations:**

_None — every node stayed within thermal / efficiency budget._

## Auto-fixes (code agent)

Attempted 3 / 5 failure(s) · **1 patched & re-tested green** in a fresh sandbox.

| test | patch | verified | urgency | why |
|---|---|---|---|---|
| `packages/nodus/tests/test_nodus_grafana.py::test_connect_mcp_falls_back_to_mock_without_launcher` | - | — | **high** | no patch proposed |
| | | | | _Symptom: (no message; see shard output). No patch produced — cannot clear the symptom yet. Hint: Reproduce locally, bisect the last change touching this module.._ · same file has 2 failing test(s) |
| `packages/nodus/tests/test_nodus_grafana.py::test_connect_mcp_forwards_org_id_env` | `fixes/test_connect_mcp_forwards_org_id_env.patch` | ❌ still red | **high** | target test still failing |
| | | | | _Symptom: (no message; see shard output). Patch tried but not kept (target test still failing). Hint: Reproduce locally, bisect the last change touching this module.._ · same file has 2 failing test(s) |
| `packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_drive_underscore_prefix` | `fixes/test_drive_underscore_prefix.patch` | ✅ | **medium** | re-tested green in a fresh sandbox |
| | | | | _Symptom: (no message; see shard output). Action: patch applied and suite stayed green. Hint was: Reproduce locally, bisect the last change touching this module.._ · same file has 3 failing test(s) |

## Consolidated failures

### `packages/nodus/tests/test_nodus_grafana.py::test_connect_mcp_falls_back_to_mock_without_launcher`
- Error: `(no message; see shard output)`
- Seen on: shard 0 / node `nb-h100-00`
- Heuristic hint: Reproduce locally, bisect the last change touching this module.
- Agent outcome: **needs a human**

### `packages/nodus/tests/test_nodus_grafana.py::test_connect_mcp_forwards_org_id_env`
- Error: `(no message; see shard output)`
- Seen on: shard 0 / node `nb-h100-00`
- Heuristic hint: Reproduce locally, bisect the last change touching this module.
- Agent outcome: **patch rejected**

### `packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_drive_underscore_prefix`
- Error: `(no message; see shard output)`
- Seen on: shard 1 / node `nb-h100-01`
- Heuristic hint: Reproduce locally, bisect the last change touching this module.
- Agent outcome: **auto-fixed & verified**

### `packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_missing_colon_cusers`
- Error: `(no message; see shard output)`
- Seen on: shard 1 / node `nb-h100-01`
- Heuristic hint: Reproduce locally, bisect the last change touching this module.
- Agent outcome: **needs a human**

### `packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_coerce_basename_to_expected`
- Error: `(no message; see shard output)`
- Seen on: shard 1 / node `nb-h100-01`
- Heuristic hint: Reproduce locally, bisect the last change touching this module.
- Agent outcome: **needs a human**

## Event log

```json
[
  {
    "t": 1790919888.374,
    "kind": "capabilities",
    "host_tools": [
      "nvidia-smi"
    ],
    "host_summary": "nvidia-smi",
    "expect_probe": "synthetic",
    "expect_real_gpu": true,
    "fleet_image": "(mock)",
    "reason": "MockFleet emits synthetic H100-class telemetry",
    "heal_enabled": true
  },
  {
    "t": 1790919888.374,
    "kind": "run_start",
    "task": "Run the failing pytest suite across the GPU fleet, triage, fix, report.",
    "shards": 2,
    "gpu_type": "H100",
    "fleet_mode": "mock",
    "sandbox_mode": "token_factory",
    "jail": true
  },
  {
    "t": 1790919888.374,
    "kind": "model_route",
    "decision": "plan",
    "tier": "ultra",
    "model": "nebius:nvidia/Nemotron-3-Ultra-550b-a55b"
  },
  {
    "t": 1790919888.375,
    "kind": "plan",
    "names": [
      "bash",
      "edit_file",
      "write_file"
    ],
    "source": "heuristic",
    "note": "324M planner checkpoint NOT FOUND at __nge_force_heuristic__\\missing.pt - planning falls back to the hand-written keyword heuristic. Point at the weights with NODUS_PLAN_CKPT=/path/to/checkpoint_sft_plan_v5.pt, or write that path into packages/engine/.nodus_plan_ckpt",
    "degraded": true
  },
  {
    "t": 1790919888.375,
    "kind": "plan_degraded",
    "source": "heuristic",
    "reason": "324M planner checkpoint NOT FOUND at __nge_force_heuristic__\\missing.pt - planning falls back to the hand-written keyword heuristic. Point at the weights with NODUS_PLAN_CKPT=/path/to/checkpoint_sft_plan_v5.pt, or write that path into packages/engine/.nodus_plan_ckpt"
  },
  {
    "t": 1790919888.375,
    "kind": "gpu_provision",
    "provisioned": 2,
    "nodes": [
      {
        "id": "nb-h100-00",
        "gpu_type": "H100",
        "region": "eu-north1",
        "state": "ready",
        "job": null
      },
      {
        "id": "nb-h100-01",
        "gpu_type": "H100",
        "region": "eu-north1",
        "state": "ready",
        "job": null
      }
    ]
  },
  {
    "t": 1790919888.376,
    "kind": "shard_split",
    "strategy": "round-robin-files",
    "files": 13,
    "shards": 2
  },
  {
    "t": 1790919888.397,
    "kind": "sandbox_env",
    "source_root": "packages/nodus",
    "requirements": "packages/nodus/requirements-ci.txt",
    "payload_files": 53
  },
  {
    "t": 1790919888.397,
    "kind": "payload",
    "files": 53,
    "bytes": 921525
  },
  {
    "t": 1790919888.397,
    "kind": "model_route",
    "decision": "slotfill",
    "tier": "super",
    "model": "nebius:nvidia/nemotron-3-super-120b-a12b"
  },
  {
    "t": 1790919889.39,
    "kind": "shard_start",
    "index": 0,
    "node_id": "nb-h100-00",
    "command": "pip install -q -r packages/nodus/requirements-ci.txt && PYTHONPATH=packages/nodus pytest -q -v --tb=short --junitxml=/tmp/junit_shard0.xml packages/nodus/tests/test_demo_agentic_cinema.py packages/nodus/tests/test_nodus_agent.py packages/nodus/tests/test_nodus_grafana.py packages/nodus/tests/test_nodus_plan_slotfill.py packages/nodus/tests/test_nodus_policy.py packages/nodus/tests/test_nodus_verify.py packages/nodus/tests/test_ssrf_redirect.py"
  },
  {
    "t": 1790919904.734,
    "kind": "gpu_status",
    "node_id": "nb-h100-00",
    "telemetry": {
      "id": "nb-h100-00",
      "state": "allocated",
      "util_pct": 97.5,
      "mem_used_gb": 31.4,
      "mem_total_gb": 80.0,
      "temp_c": 73.7,
      "power_w": 529.5,
      "health": "ok",
      "efficiency": 1.0,
      "probe_kind": "synthetic",
      "gpu_class": "synthetic",
      "gpu_name": "mock-H100"
    }
  },
  {
    "t": 1790919904.734,
    "kind": "shard_done",
    "index": 0,
    "node_id": "nb-h100-00",
    "migrated_from": null,
    "exit_code": 1,
    "failures": 2
  },
  {
    "t": 1790919904.734,
    "kind": "model_route",
    "decision": "slotfill",
    "tier": "super",
    "model": "nebius:nvidia/nemotron-3-super-120b-a12b"
  },
  {
    "t": 1790919905.692,
    "kind": "shard_start",
    "index": 1,
    "node_id": "nb-h100-01",
    "command": "pip install -q -r packages/nodus/requirements-ci.txt && PYTHONPATH=packages/nodus pytest -q -v --tb=short --junitxml=/tmp/junit.xml packages/nodus/tests/test_endurance.py packages/nodus/tests/test_nodus_gcloud.py packages/nodus/tests/test_nodus_memory.py packages/nodus/tests/test_nodus_planner.py packages/nodus/tests/test_nodus_tools.py packages/nodus/tests/test_secret_redaction.py"
  },
  {
    "t": 1790919918.926,
    "kind": "gpu_status",
    "node_id": "nb-h100-01",
    "telemetry": {
      "id": "nb-h100-01",
      "state": "allocated",
      "util_pct": 57.0,
      "mem_used_gb": 22.2,
      "mem_total_gb": 80.0,
      "temp_c": 78.3,
      "power_w": 540.8,
      "health": "warm",
      "efficiency": 0.738,
      "probe_kind": "synthetic",
      "gpu_class": "synthetic",
      "gpu_name": "mock-H100"
    }
  },
  {
    "t": 1790919918.926,
    "kind": "shard_done",
    "index": 1,
    "node_id": "nb-h100-01",
    "migrated_from": null,
    "exit_code": 1,
    "failures": 3
  },
  {
    "t": 1790919918.926,
    "kind": "triage",
    "unique_failures": 5
  },
  {
    "t": 1790919918.926,
    "kind": "plan_gated_autofix",
    "allowed": true,
    "plan": [
      "bash",
      "edit_file",
      "write_file"
    ],
    "source": "heuristic",
    "because": [
      "edit_file",
      "write_file"
    ]
  },
  {
    "t": 1790919918.926,
    "kind": "model_route",
    "decision": "triage",
    "tier": "super",
    "model": "nebius:nvidia/nemotron-3-super-120b-a12b"
  },
  {
    "t": 1790919918.97,
    "kind": "under_test",
    "test": "packages/nodus/tests/test_nodus_grafana.py::test_connect_mcp_falls_back_to_mock_without_launcher",
    "resolved": [
      "packages/nodus/nodus_grafana.py:72"
    ]
  },
  {
    "t": 1790919955.564,
    "kind": "patch_truncated",
    "test": "packages/nodus/tests/test_nodus_grafana.py::test_connect_mcp_falls_back_to_mock_without_launcher",
    "attempt": 1,
    "max_tokens": 8192,
    "reply_chars": 0,
    "reply_head": "",
    "reasoning_tokens": 8192,
    "why": "reasoning used the whole budget"
  },
  {
    "t": 1790919955.564,
    "kind": "fix_attempt",
    "test": "packages/nodus/tests/test_nodus_grafana.py::test_connect_mcp_falls_back_to_mock_without_launcher",
    "has_patch": false
  },
  {
    "t": 1790919955.564,
    "kind": "model_route",
    "decision": "triage",
    "tier": "super",
    "model": "nebius:nvidia/nemotron-3-super-120b-a12b"
  },
  {
    "t": 1790919955.571,
    "kind": "under_test",
    "test": "packages/nodus/tests/test_nodus_grafana.py::test_connect_mcp_forwards_org_id_env",
    "resolved": [
      "packages/nodus/nodus_grafana.py:72"
    ]
  },
  {
    "t": 1790919980.139,
    "kind": "fix_attempt",
    "test": "packages/nodus/tests/test_nodus_grafana.py::test_connect_mcp_forwards_org_id_env",
    "has_patch": true
  },
  {
    "t": 1790919980.144,
    "kind": "fix_sources",
    "test": "packages/nodus/tests/test_nodus_grafana.py::test_connect_mcp_forwards_org_id_env",
    "files": [
      "packages/nodus/tests/test_nodus_grafana.py"
    ]
  },
  {
    "t": 1790919995.247,
    "kind": "fix_rejected",
    "test": "packages/nodus/tests/test_nodus_grafana.py::test_connect_mcp_forwards_org_id_env",
    "node": "nb-h100-02",
    "target_fixed": false,
    "regressions": 0
  },
  {
    "t": 1790919995.247,
    "kind": "model_route",
    "decision": "triage",
    "tier": "super",
    "model": "nebius:nvidia/nemotron-3-super-120b-a12b"
  },
  {
    "t": 1790919995.284,
    "kind": "under_test",
    "test": "packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_drive_underscore_prefix",
    "resolved": [
      "packages/nodus/nodus_tools.py:1200"
    ]
  },
  {
    "t": 1790920006.378,
    "kind": "fix_attempt",
    "test": "packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_drive_underscore_prefix",
    "has_patch": true
  },
  {
    "t": 1790920006.38,
    "kind": "patch_relocated",
    "claimed": 1,
    "actual": 1246
  },
  {
    "t": 1790920006.383,
    "kind": "fix_sources",
    "test": "packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_drive_underscore_prefix",
    "files": [
      "packages/nodus/nodus_tools.py"
    ]
  },
  {
    "t": 1790920020.162,
    "kind": "fix_verified",
    "test": "packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_drive_underscore_prefix",
    "node": "nb-h100-03",
    "target_fixed": true,
    "regressions": 0
  },
  {
    "t": 1790920020.162,
    "kind": "gpu_release",
    "released": [
      "nb-h100-00",
      "nb-h100-01"
    ],
    "count": 2
  }
]
```
