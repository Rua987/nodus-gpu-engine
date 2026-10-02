# Fleet test triage - 20261002T065809Z

**Task:** Run the failing pytest suite across the GPU fleet, triage, fix, report.

- Plan (heuristic): `['bash', 'edit_file', 'write_file']`  **- not the 324M planner**
  - 324M planner checkpoint NOT FOUND at __nge_force_heuristic__\missing.pt - planning falls back to the hand-written keyword heuristic. Point at the weights with NODUS_PLAN_CKPT=/path/to/checkpoint_sft_plan_v5.pt, or write that path into packages/engine/.nodus_plan_ckpt
- Fleet mode: `mock` | Sandbox: `token_factory`
- Shards: 2 | Unique failures: 6 | Auto-fixed: 5

## Shards

| # | node | exit | dur (s) | failures |
|---|------|------|---------|----------|
| 0 | `nb-h100-00` | 1 | 2.205 | 4 |
| 1 | `nb-h100-01` | 1 | 2.236 | 2 |

## Self-managed compute

**Model routing (Nemotron tiers):**

- `ultra` → plan
- `super` → slotfill, triage

**GPU pressure remediations:**

_None — every node stayed within thermal / efficiency budget._

## Auto-fixes (code agent)

Attempted 6 / 6 failure(s) · **5 patched & re-tested green** in a fresh sandbox.

| test | patch | verified | urgency | why |
|---|---|---|---|---|
| `packages/engine/bench/bugbench/tests/test_dates.py::test_century_divisible_by_400_is_leap` | `fixes/test_century_divisible_by_400_is_leap.patch` | ✅ | **medium** | re-tested green in a fresh sandbox |
| | | | | _Symptom: (no message; see shard output). Action: patch applied and suite stayed green. Hint was: Reproduce locally, bisect the last change touching this module.._ · same file has 2 failing test(s) |
| `packages/engine/bench/bugbench/tests/test_dates.py::test_days_between_ignores_order` | `fixes/test_days_between_ignores_order.patch` | ✅ | **medium** | re-tested green in a fresh sandbox |
| | | | | _Symptom: (no message; see shard output). Action: patch applied and suite stayed green. Hint was: Reproduce locally, bisect the last change touching this module.._ · same file has 2 failing test(s) |
| `packages/engine/bench/bugbench/tests/test_textkit.py::test_slug_collapses_punctuation_and_spaces` | `fixes/test_slug_collapses_punctuation_and_spaces.patch` | ❌ still red | **high** | sandbox produced no output - nothing ran |
| | | | | _Symptom: (no message; see shard output). Patch tried but not kept (sandbox produced no output - nothing ran). Hint: Reproduce locally, bisect the last change touching this module.._ · same file has 2 failing test(s) |
| `packages/engine/bench/bugbench/tests/test_textkit.py::test_short_text_is_not_truncated` | `fixes/test_short_text_is_not_truncated.patch` | ✅ | **medium** | re-tested green in a fresh sandbox |
| | | | | _Symptom: (no message; see shard output). Action: patch applied and suite stayed green. Hint was: Reproduce locally, bisect the last change touching this module.._ · same file has 2 failing test(s) |
| `packages/engine/bench/bugbench/tests/test_shop.py::test_discount_takes_a_percentage` | `fixes/test_discount_takes_a_percentage.patch` | ✅ | **medium** | re-tested green in a fresh sandbox |
| | | | | _Symptom: (no message; see shard output). Action: patch applied and suite stayed green. Hint was: Reproduce locally, bisect the last change touching this module.._ · same file has 2 failing test(s) |
| `packages/engine/bench/bugbench/tests/test_shop.py::test_cart_total_counts_every_item` | `fixes/test_cart_total_counts_every_item.patch` | ✅ | **medium** | re-tested green in a fresh sandbox |
| | | | | _Symptom: (no message; see shard output). Action: patch applied and suite stayed green. Hint was: Reproduce locally, bisect the last change touching this module.._ · same file has 2 failing test(s) |

## Consolidated failures

### `packages/engine/bench/bugbench/tests/test_dates.py::test_century_divisible_by_400_is_leap`
- Error: `(no message; see shard output)`
- Seen on: shard 0 / node `nb-h100-00`
- Heuristic hint: Reproduce locally, bisect the last change touching this module.
- Agent outcome: **auto-fixed & verified**

### `packages/engine/bench/bugbench/tests/test_dates.py::test_days_between_ignores_order`
- Error: `(no message; see shard output)`
- Seen on: shard 0 / node `nb-h100-00`
- Heuristic hint: Reproduce locally, bisect the last change touching this module.
- Agent outcome: **auto-fixed & verified**

### `packages/engine/bench/bugbench/tests/test_textkit.py::test_slug_collapses_punctuation_and_spaces`
- Error: `(no message; see shard output)`
- Seen on: shard 0 / node `nb-h100-00`
- Heuristic hint: Reproduce locally, bisect the last change touching this module.
- Agent outcome: **patch rejected**

### `packages/engine/bench/bugbench/tests/test_textkit.py::test_short_text_is_not_truncated`
- Error: `(no message; see shard output)`
- Seen on: shard 0 / node `nb-h100-00`
- Heuristic hint: Reproduce locally, bisect the last change touching this module.
- Agent outcome: **auto-fixed & verified**

### `packages/engine/bench/bugbench/tests/test_shop.py::test_discount_takes_a_percentage`
- Error: `(no message; see shard output)`
- Seen on: shard 1 / node `nb-h100-01`
- Heuristic hint: Reproduce locally, bisect the last change touching this module.
- Agent outcome: **auto-fixed & verified**

### `packages/engine/bench/bugbench/tests/test_shop.py::test_cart_total_counts_every_item`
- Error: `(no message; see shard output)`
- Seen on: shard 1 / node `nb-h100-01`
- Heuristic hint: Reproduce locally, bisect the last change touching this module.
- Agent outcome: **auto-fixed & verified**

## Event log

```json
[
  {
    "t": 1790924229.651,
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
    "t": 1790924229.651,
    "kind": "run_start",
    "task": "Run the failing pytest suite across the GPU fleet, triage, fix, report.",
    "shards": 2,
    "gpu_type": "H100",
    "fleet_mode": "mock",
    "sandbox_mode": "token_factory",
    "jail": true
  },
  {
    "t": 1790924229.651,
    "kind": "model_route",
    "decision": "plan",
    "tier": "ultra",
    "model": "nebius:nvidia/Nemotron-3-Ultra-550b-a55b"
  },
  {
    "t": 1790924229.651,
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
    "t": 1790924229.651,
    "kind": "plan_degraded",
    "source": "heuristic",
    "reason": "324M planner checkpoint NOT FOUND at __nge_force_heuristic__\\missing.pt - planning falls back to the hand-written keyword heuristic. Point at the weights with NODUS_PLAN_CKPT=/path/to/checkpoint_sft_plan_v5.pt, or write that path into packages/engine/.nodus_plan_ckpt"
  },
  {
    "t": 1790924229.651,
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
    "t": 1790924229.651,
    "kind": "shard_split",
    "strategy": "round-robin-files",
    "files": 3,
    "shards": 2
  },
  {
    "t": 1790924229.662,
    "kind": "sandbox_env",
    "source_root": "packages/engine/bench/bugbench",
    "requirements": null,
    "payload_files": 6
  },
  {
    "t": 1790924229.662,
    "kind": "payload",
    "files": 6,
    "bytes": 3348
  },
  {
    "t": 1790924229.662,
    "kind": "model_route",
    "decision": "slotfill",
    "tier": "super",
    "model": "nebius:nvidia/nemotron-3-super-120b-a12b"
  },
  {
    "t": 1790924230.467,
    "kind": "shard_start",
    "index": 0,
    "node_id": "nb-h100-00",
    "command": "pip install -q pytest && PYTHONPATH=packages/engine/bench/bugbench pytest -q -v --tb=short --junitxml=/tmp/junit_shard0.xml packages/engine/bench/bugbench/tests/test_dates.py packages/engine/bench/bugbench/tests/test_textkit.py"
  },
  {
    "t": 1790924237.185,
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
    "t": 1790924237.185,
    "kind": "shard_done",
    "index": 0,
    "node_id": "nb-h100-00",
    "migrated_from": null,
    "exit_code": 1,
    "failures": 4
  },
  {
    "t": 1790924237.185,
    "kind": "model_route",
    "decision": "slotfill",
    "tier": "super",
    "model": "nebius:nvidia/nemotron-3-super-120b-a12b"
  },
  {
    "t": 1790924237.987,
    "kind": "shard_start",
    "index": 1,
    "node_id": "nb-h100-01",
    "command": "pip install -q pytest && PYTHONPATH=packages/engine/bench/bugbench pytest packages/engine/bench/bugbench/tests/test_shop.py -q -v --tb=short --junitxml=/tmp/junit_shard1.xml"
  },
  {
    "t": 1790924243.562,
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
    "t": 1790924243.562,
    "kind": "shard_done",
    "index": 1,
    "node_id": "nb-h100-01",
    "migrated_from": null,
    "exit_code": 1,
    "failures": 2
  },
  {
    "t": 1790924243.562,
    "kind": "triage",
    "unique_failures": 6
  },
  {
    "t": 1790924243.562,
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
    "t": 1790924243.562,
    "kind": "model_route",
    "decision": "triage",
    "tier": "super",
    "model": "nebius:nvidia/nemotron-3-super-120b-a12b"
  },
  {
    "t": 1790924243.565,
    "kind": "under_test",
    "test": "packages/engine/bench/bugbench/tests/test_dates.py::test_century_divisible_by_400_is_leap",
    "resolved": [
      "packages/engine/bench/bugbench/dates.py:5"
    ]
  },
  {
    "t": 1790924244.668,
    "kind": "fix_attempt",
    "test": "packages/engine/bench/bugbench/tests/test_dates.py::test_century_divisible_by_400_is_leap",
    "has_patch": true
  },
  {
    "t": 1790924244.668,
    "kind": "patch_relocated",
    "claimed": 1,
    "actual": 5
  },
  {
    "t": 1790924244.668,
    "kind": "fix_sources",
    "test": "packages/engine/bench/bugbench/tests/test_dates.py::test_century_divisible_by_400_is_leap",
    "files": [
      "packages/engine/bench/bugbench/dates.py"
    ]
  },
  {
    "t": 1790924251.489,
    "kind": "fix_verified",
    "test": "packages/engine/bench/bugbench/tests/test_dates.py::test_century_divisible_by_400_is_leap",
    "node": "nb-h100-02",
    "target_fixed": true,
    "regressions": 0
  },
  {
    "t": 1790924251.489,
    "kind": "model_route",
    "decision": "triage",
    "tier": "super",
    "model": "nebius:nvidia/nemotron-3-super-120b-a12b"
  },
  {
    "t": 1790924251.489,
    "kind": "under_test",
    "test": "packages/engine/bench/bugbench/tests/test_dates.py::test_days_between_ignores_order",
    "resolved": [
      "packages/engine/bench/bugbench/dates.py:10"
    ]
  },
  {
    "t": 1790924252.477,
    "kind": "fix_attempt",
    "test": "packages/engine/bench/bugbench/tests/test_dates.py::test_days_between_ignores_order",
    "has_patch": true
  },
  {
    "t": 1790924252.479,
    "kind": "patch_relocated",
    "claimed": 1,
    "actual": 10
  },
  {
    "t": 1790924252.479,
    "kind": "fix_sources",
    "test": "packages/engine/bench/bugbench/tests/test_dates.py::test_days_between_ignores_order",
    "files": [
      "packages/engine/bench/bugbench/dates.py"
    ]
  },
  {
    "t": 1790924258.85,
    "kind": "fix_verified",
    "test": "packages/engine/bench/bugbench/tests/test_dates.py::test_days_between_ignores_order",
    "node": "nb-h100-03",
    "target_fixed": true,
    "regressions": 0
  },
  {
    "t": 1790924258.85,
    "kind": "model_route",
    "decision": "triage",
    "tier": "super",
    "model": "nebius:nvidia/nemotron-3-super-120b-a12b"
  },
  {
    "t": 1790924258.853,
    "kind": "under_test",
    "test": "packages/engine/bench/bugbench/tests/test_textkit.py::test_slug_collapses_punctuation_and_spaces",
    "resolved": [
      "packages/engine/bench/bugbench/textkit.py:4"
    ]
  },
  {
    "t": 1790924260.037,
    "kind": "fix_attempt",
    "test": "packages/engine/bench/bugbench/tests/test_textkit.py::test_slug_collapses_punctuation_and_spaces",
    "has_patch": true
  },
  {
    "t": 1790924260.038,
    "kind": "patch_relocated",
    "claimed": 1,
    "actual": 4
  },
  {
    "t": 1790924260.038,
    "kind": "fix_sources",
    "test": "packages/engine/bench/bugbench/tests/test_textkit.py::test_slug_collapses_punctuation_and_spaces",
    "files": [
      "packages/engine/bench/bugbench/textkit.py"
    ]
  },
  {
    "t": 1790924266.128,
    "kind": "fix_rejected",
    "test": "packages/engine/bench/bugbench/tests/test_textkit.py::test_slug_collapses_punctuation_and_spaces",
    "node": "nb-h100-04",
    "target_fixed": false,
    "regressions": 0
  },
  {
    "t": 1790924266.128,
    "kind": "model_route",
    "decision": "triage",
    "tier": "super",
    "model": "nebius:nvidia/nemotron-3-super-120b-a12b"
  },
  {
    "t": 1790924266.13,
    "kind": "under_test",
    "test": "packages/engine/bench/bugbench/tests/test_textkit.py::test_short_text_is_not_truncated",
    "resolved": [
      "packages/engine/bench/bugbench/textkit.py:18"
    ]
  },
  {
    "t": 1790924267.222,
    "kind": "fix_attempt",
    "test": "packages/engine/bench/bugbench/tests/test_textkit.py::test_short_text_is_not_truncated",
    "has_patch": true
  },
  {
    "t": 1790924267.229,
    "kind": "patch_relocated",
    "claimed": 1,
    "actual": 18
  },
  {
    "t": 1790924267.229,
    "kind": "fix_sources",
    "test": "packages/engine/bench/bugbench/tests/test_textkit.py::test_short_text_is_not_truncated",
    "files": [
      "packages/engine/bench/bugbench/textkit.py"
    ]
  },
  {
    "t": 1790924273.982,
    "kind": "fix_verified",
    "test": "packages/engine/bench/bugbench/tests/test_textkit.py::test_short_text_is_not_truncated",
    "node": "nb-h100-05",
    "target_fixed": true,
    "regressions": 0
  },
  {
    "t": 1790924273.982,
    "kind": "model_route",
    "decision": "triage",
    "tier": "super",
    "model": "nebius:nvidia/nemotron-3-super-120b-a12b"
  },
  {
    "t": 1790924273.991,
    "kind": "under_test",
    "test": "packages/engine/bench/bugbench/tests/test_shop.py::test_discount_takes_a_percentage",
    "resolved": [
      "packages/engine/bench/bugbench/shop.py:4"
    ]
  },
  {
    "t": 1790924275.29,
    "kind": "fix_attempt",
    "test": "packages/engine/bench/bugbench/tests/test_shop.py::test_discount_takes_a_percentage",
    "has_patch": true
  },
  {
    "t": 1790924275.29,
    "kind": "patch_relocated",
    "claimed": 1,
    "actual": 4
  },
  {
    "t": 1790924275.29,
    "kind": "fix_sources",
    "test": "packages/engine/bench/bugbench/tests/test_shop.py::test_discount_takes_a_percentage",
    "files": [
      "packages/engine/bench/bugbench/shop.py"
    ]
  },
  {
    "t": 1790924282.072,
    "kind": "fix_verified",
    "test": "packages/engine/bench/bugbench/tests/test_shop.py::test_discount_takes_a_percentage",
    "node": "nb-h100-06",
    "target_fixed": true,
    "regressions": 0
  },
  {
    "t": 1790924282.072,
    "kind": "model_route",
    "decision": "triage",
    "tier": "super",
    "model": "nebius:nvidia/nemotron-3-super-120b-a12b"
  },
  {
    "t": 1790924282.072,
    "kind": "under_test",
    "test": "packages/engine/bench/bugbench/tests/test_shop.py::test_cart_total_counts_every_item",
    "resolved": [
      "packages/engine/bench/bugbench/shop.py:14"
    ]
  },
  {
    "t": 1790924283.209,
    "kind": "fix_attempt",
    "test": "packages/engine/bench/bugbench/tests/test_shop.py::test_cart_total_counts_every_item",
    "has_patch": true
  },
  {
    "t": 1790924283.209,
    "kind": "patch_relocated",
    "claimed": 1,
    "actual": 14
  },
  {
    "t": 1790924283.211,
    "kind": "fix_sources",
    "test": "packages/engine/bench/bugbench/tests/test_shop.py::test_cart_total_counts_every_item",
    "files": [
      "packages/engine/bench/bugbench/shop.py"
    ]
  },
  {
    "t": 1790924289.978,
    "kind": "fix_verified",
    "test": "packages/engine/bench/bugbench/tests/test_shop.py::test_cart_total_counts_every_item",
    "node": "nb-h100-07",
    "target_fixed": true,
    "regressions": 0
  },
  {
    "t": 1790924289.978,
    "kind": "gpu_release",
    "released": [
      "nb-h100-00",
      "nb-h100-01"
    ],
    "count": 2
  }
]
```
