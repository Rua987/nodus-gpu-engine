# Fleet test triage - 20261002T052311Z

**Task:** Run the failing pytest suite across the GPU fleet, triage, fix, report.

- Plan (heuristic): `['bash', 'edit_file', 'write_file']`  **- not the 324M planner**
  - 324M planner checkpoint NOT FOUND at __nge_force_heuristic__\missing.pt - planning falls back to the hand-written keyword heuristic. Point at the weights with NODUS_PLAN_CKPT=/path/to/checkpoint_sft_plan_v5.pt, or write that path into packages/engine/.nodus_plan_ckpt
- Fleet mode: `mock` | Sandbox: `token_factory`
- Shards: 2 | Unique failures: 2 | Auto-fixed: 0

## Shards

| # | node | exit | dur (s) | failures |
|---|------|------|---------|----------|
| 0 | `nb-h100-00` | 1 | 6.034 | 1 |
| 1 | `nb-h100-01` | 1 | 5.538 | 1 |

## Self-managed compute

**Model routing (Nemotron tiers):**

- `ultra` → plan
- `super` → slotfill, triage

**GPU pressure remediations:**

_None — every node stayed within thermal / efficiency budget._

## Auto-fixes (code agent)

Attempted 2 / 2 failure(s) · **0 patched & re-tested green** in a fresh sandbox.

| test | patch | verified | urgency | why |
|---|---|---|---|---|
| `packages/nodus/tests/test_nodus_grafana.py::test_connect_mcp_falls_back_to_mock_without_launcher` | - | — | **medium** | no patch proposed |
| | | | | _Symptom: (no message; see shard output). No patch produced — cannot clear the symptom yet. Hint: Reproduce locally, bisect the last change touching this module.._ · single failure in this file |
| `packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_drive_underscore_prefix` | `fixes/test_drive_underscore_prefix.patch` | ❌ still red | **high** | broke packages/nodus/tests/test_nodus_grafana.py::test_connect_mcp_forwards_org_id_env, packages/nodus/tests/test_nodus_tools.py::TestConfine::test_absolute_outside_refused, packages/nodus/tests/test_nodus_tools.py::TestConfine::test_no_cwd_no_confinement, packages/nodus/tests/test_nodus_tools.py::TestConfine::test_parent_traversal_refused, packages/nodus/tests/test_nodus_tools.py::TestConfine::test_repairs_drive_garble_then_confines, packages/nodus/tests/test_nodus_tools.py::TestDispatchConfinement::test_edit_escape_refused, packages/nodus/tests/test_nodus_tools.py::TestDispatchConfinement::test_glob_escape_refused, packages/nodus/tests/test_nodus_tools.py::TestDispatchConfinement::test_glob_inside_allowed, packages/nodus/tests/test_nodus_tools.py::TestDispatchConfinement::test_grep_escape_refused, packages/nodus/tests/test_nodus_tools.py::TestDispatchConfinement::test_grep_inside_allowed, packages/nodus/tests/test_nodus_tools.py::TestDispatchConfinement::test_read_escape_refused, packages/nodus/tests/test_nodus_tools.py::TestDispatchConfinement::test_read_traversal_refused, packages/nodus/tests/test_nodus_tools.py::TestDispatchConfinement::test_write_escape_refused, packages/nodus/tests/test_nodus_tools.py::TestDispatchConfinement::test_write_traversal_refused, packages/nodus/tests/test_nodus_tools.py::TestDispatchCwdAnchoring::test_glob_defaults_to_cwd, packages/nodus/tests/test_nodus_tools.py::TestDispatchTool::test_dispatch_edit_file, packages/nodus/tests/test_nodus_tools.py::TestDispatchTool::test_dispatch_edit_file_replace_all, packages/nodus/tests/test_nodus_tools.py::TestDispatchTool::test_dispatch_glob_with_path, packages/nodus/tests/test_nodus_tools.py::TestDispatchTool::test_dispatch_grep_with_all_options, packages/nodus/tests/test_nodus_tools.py::TestDispatchTool::test_dispatch_read_file, packages/nodus/tests/test_nodus_tools.py::TestDispatchTool::test_dispatch_read_file_with_offset_limit, packages/nodus/tests/test_nodus_tools.py::TestDispatchTool::test_dispatch_write_file, packages/nodus/tests/test_nodus_tools.py::TestDispatchTool::test_edit_file_path_alias, packages/nodus/tests/test_nodus_tools.py::TestDispatchTool::test_read_file_path_alias, packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_absolute_doubled_scratch_dir, packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_coerce_basename_to_expected, packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_dispatch_write_accepts_garbled_drive, packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_fused_drive_and_doubled_dir, packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_healthy_relative_unchanged, packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_unix_abs_garble, packages/nodus/tests/test_secret_redaction.py::test_dispatch_tool_normal_output_untouched, packages/nodus/tests/test_secret_redaction.py::test_dispatch_tool_redacts_real_file |
| | | | | _Symptom: (no message; see shard output). Patch tried but not kept (broke packages/nodus/tests/test_nodus_grafana.py::test_connect_mcp_forwards_org_id_env, packages/nodus/tests/test_nodus_tools.py::TestConfine::test_absolute_outside_refused, packages/nodus/tests/test_nodus_tools.py::TestConfine::test_no_cwd_no_confinement, packages/nodus/tests/test_nodus_tools.py::TestConfine::test_parent_traversal_refused, packages/nodus/tests/test_nodus_tools.py::TestConfine::test_repairs_drive_garble_then_confines, packages/nodus/tests/test_nodus_tools.py::TestDispatchConfinement::test_edit_escape_refused, packages/nodus/tests/test_nodus_tools.py::TestDispatchConfinement::test_glob_escape_refused, packages/nodus/tests/test_nodus_tools.py::TestDispatchConfinement::test_glob_inside_allowed, packages/nodus/tests/test_nodus_tools.py::TestDispatchConfinement::test_grep_escape_refused, packages/nodus/tests/test_nodus_tools.py::TestDispatchConfinement::test_grep_inside_allowed, packages/nodus/tests/test_nodus_tools.py::TestDispatchConfinement::test_read_escape_refused, packages/nodus/tests/test_nodus_tools.py::TestDispatchConfinement::test_read_traversal_refused, packages/nodus/tests/test_nodus_tools.py::TestDispatchConfinement::test_write_escape_refused, packages/nodus/tests/test_nodus_tools.py::TestDispatchConfinement::test_write_traversal_refused, packages/nodus/tests/test_nodus_tools.py::TestDispatchCwdAnchoring::test_glob_defaults_to_cwd, packages/nodus/tests/test_nodus_tools.py::TestDispatchTool::test_dispatch_edit_file, packages/nodus/tests/test_nodus_tools.py::TestDispatchTool::test_dispatch_edit_file_replace_all, packages/nodus/tests/test_nodus_tools.py::TestDispatchTool::test_dispatch_glob_with_path, packages/nodus/tests/test_nodus_tools.py::TestDispatchTool::test_dispatch_grep_with_all_options, packages/nodus/tests/test_nodus_tools.py::TestDispatchTool::test_dispatch_read_file, packages/nodus/tests/test_nodus_tools.py::TestDispatchTool::test_dispatch_read_file_with_offset_limit, packages/nodus/tests/test_nodus_tools.py::TestDispatchTool::test_dispatch_write_file, packages/nodus/tests/test_nodus_tools.py::TestDispatchTool::test_edit_file_path_alias, packages/nodus/tests/test_nodus_tools.py::TestDispatchTool::test_read_file_path_alias, packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_absolute_doubled_scratch_dir, packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_coerce_basename_to_expected, packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_dispatch_write_accepts_garbled_drive, packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_fused_drive_and_doubled_dir, packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_healthy_relative_unchanged, packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_unix_abs_garble, packages/nodus/tests/test_secret_redaction.py::test_dispatch_tool_normal_output_untouched, packages/nodus/tests/test_secret_redaction.py::test_dispatch_tool_redacts_real_file). Hint: Reproduce locally, bisect the last change touching this module.._ · single failure in this file |

## Consolidated failures

### `packages/nodus/tests/test_nodus_grafana.py::test_connect_mcp_falls_back_to_mock_without_launcher`
- Error: `(no message; see shard output)`
- Seen on: shard 0 / node `nb-h100-00`
- Heuristic hint: Reproduce locally, bisect the last change touching this module.
- Agent outcome: **needs a human**

### `packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_drive_underscore_prefix`
- Error: `(no message; see shard output)`
- Seen on: shard 1 / node `nb-h100-01`
- Heuristic hint: Reproduce locally, bisect the last change touching this module.
- Agent outcome: **patch rejected**

## Event log

```json
[
  {
    "t": 1790918530.904,
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
    "t": 1790918530.904,
    "kind": "run_start",
    "task": "Run the failing pytest suite across the GPU fleet, triage, fix, report.",
    "shards": 2,
    "gpu_type": "H100",
    "fleet_mode": "mock",
    "sandbox_mode": "token_factory",
    "jail": true
  },
  {
    "t": 1790918530.904,
    "kind": "model_route",
    "decision": "plan",
    "tier": "ultra",
    "model": "nebius:nvidia/Nemotron-3-Ultra-550b-a55b"
  },
  {
    "t": 1790918530.904,
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
    "t": 1790918530.904,
    "kind": "plan_degraded",
    "source": "heuristic",
    "reason": "324M planner checkpoint NOT FOUND at __nge_force_heuristic__\\missing.pt - planning falls back to the hand-written keyword heuristic. Point at the weights with NODUS_PLAN_CKPT=/path/to/checkpoint_sft_plan_v5.pt, or write that path into packages/engine/.nodus_plan_ckpt"
  },
  {
    "t": 1790918530.904,
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
    "t": 1790918530.907,
    "kind": "shard_split",
    "strategy": "round-robin-files",
    "files": 13,
    "shards": 2
  },
  {
    "t": 1790918530.926,
    "kind": "sandbox_env",
    "source_root": "packages/nodus",
    "requirements": "packages/nodus/requirements-ci.txt",
    "payload_files": 53
  },
  {
    "t": 1790918530.926,
    "kind": "payload",
    "files": 53,
    "bytes": 921525
  },
  {
    "t": 1790918530.926,
    "kind": "model_route",
    "decision": "slotfill",
    "tier": "super",
    "model": "nebius:nvidia/nemotron-3-super-120b-a12b"
  },
  {
    "t": 1790918531.809,
    "kind": "shard_start",
    "index": 0,
    "node_id": "nb-h100-00",
    "command": "pip install -q -r packages/nodus/requirements-ci.txt && PYTHONPATH=packages/nodus pytest -q -v -x packages/nodus/tests/test_demo_agentic_cinema.py packages/nodus/tests/test_nodus_agent.py packages/nodus/tests/test_nodus_grafana.py packages/nodus/tests/test_nodus_plan_slotfill.py packages/nodus/tests/test_nodus_policy.py packages/nodus/tests/test_nodus_verify.py packages/nodus/tests/test_ssrf_redirect.py"
  },
  {
    "t": 1790918545.432,
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
    "t": 1790918545.432,
    "kind": "shard_done",
    "index": 0,
    "node_id": "nb-h100-00",
    "migrated_from": null,
    "exit_code": 1,
    "failures": 1
  },
  {
    "t": 1790918545.432,
    "kind": "model_route",
    "decision": "slotfill",
    "tier": "super",
    "model": "nebius:nvidia/nemotron-3-super-120b-a12b"
  },
  {
    "t": 1790918546.249,
    "kind": "shard_start",
    "index": 1,
    "node_id": "nb-h100-01",
    "command": "pip install -q -r packages/nodus/requirements-ci.txt && PYTHONPATH=packages/nodus pytest -q -v -x packages/nodus/tests/test_endurance.py packages/nodus/tests/test_nodus_gcloud.py packages/nodus/tests/test_nodus_memory.py packages/nodus/tests/test_nodus_planner.py packages/nodus/tests/test_nodus_tools.py packages/nodus/tests/test_secret_redaction.py"
  },
  {
    "t": 1790918557.47,
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
    "t": 1790918557.47,
    "kind": "shard_done",
    "index": 1,
    "node_id": "nb-h100-01",
    "migrated_from": null,
    "exit_code": 1,
    "failures": 1
  },
  {
    "t": 1790918557.47,
    "kind": "triage",
    "unique_failures": 2
  },
  {
    "t": 1790918557.47,
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
    "t": 1790918557.47,
    "kind": "model_route",
    "decision": "triage",
    "tier": "super",
    "model": "nebius:nvidia/nemotron-3-super-120b-a12b"
  },
  {
    "t": 1790918557.477,
    "kind": "under_test",
    "test": "packages/nodus/tests/test_nodus_grafana.py::test_connect_mcp_falls_back_to_mock_without_launcher",
    "resolved": [
      "packages/nodus/nodus_grafana.py:72"
    ]
  },
  {
    "t": 1790918566.669,
    "kind": "patch_truncated",
    "test": "packages/nodus/tests/test_nodus_grafana.py::test_connect_mcp_falls_back_to_mock_without_launcher",
    "attempt": 1,
    "max_tokens": 2048,
    "reply_chars": 0,
    "reply_head": "",
    "reasoning_tokens": 2048,
    "why": "reasoning used the whole budget"
  },
  {
    "t": 1790918566.669,
    "kind": "fix_attempt",
    "test": "packages/nodus/tests/test_nodus_grafana.py::test_connect_mcp_falls_back_to_mock_without_launcher",
    "has_patch": false
  },
  {
    "t": 1790918566.669,
    "kind": "model_route",
    "decision": "triage",
    "tier": "super",
    "model": "nebius:nvidia/nemotron-3-super-120b-a12b"
  },
  {
    "t": 1790918566.7,
    "kind": "under_test",
    "test": "packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_drive_underscore_prefix",
    "resolved": [
      "packages/nodus/nodus_tools.py:1200"
    ]
  },
  {
    "t": 1790918576.891,
    "kind": "fix_attempt",
    "test": "packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_drive_underscore_prefix",
    "has_patch": true
  },
  {
    "t": 1790918576.891,
    "kind": "patch_relocated",
    "claimed": 1,
    "actual": 1246
  },
  {
    "t": 1790918576.891,
    "kind": "fix_sources",
    "test": "packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_drive_underscore_prefix",
    "files": [
      "packages/nodus/nodus_tools.py"
    ]
  },
  {
    "t": 1790918591.474,
    "kind": "fix_regression",
    "test": "packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_drive_underscore_prefix",
    "broke": [
      "packages/nodus/tests/test_nodus_grafana.py::test_connect_mcp_forwards_org_id_env",
      "packages/nodus/tests/test_nodus_tools.py::TestConfine::test_absolute_outside_refused",
      "packages/nodus/tests/test_nodus_tools.py::TestConfine::test_no_cwd_no_confinement",
      "packages/nodus/tests/test_nodus_tools.py::TestConfine::test_parent_traversal_refused",
      "packages/nodus/tests/test_nodus_tools.py::TestConfine::test_repairs_drive_garble_then_confines",
      "packages/nodus/tests/test_nodus_tools.py::TestDispatchConfinement::test_edit_escape_refused",
      "packages/nodus/tests/test_nodus_tools.py::TestDispatchConfinement::test_glob_escape_refused",
      "packages/nodus/tests/test_nodus_tools.py::TestDispatchConfinement::test_glob_inside_allowed",
      "packages/nodus/tests/test_nodus_tools.py::TestDispatchConfinement::test_grep_escape_refused",
      "packages/nodus/tests/test_nodus_tools.py::TestDispatchConfinement::test_grep_inside_allowed",
      "packages/nodus/tests/test_nodus_tools.py::TestDispatchConfinement::test_read_escape_refused",
      "packages/nodus/tests/test_nodus_tools.py::TestDispatchConfinement::test_read_traversal_refused",
      "packages/nodus/tests/test_nodus_tools.py::TestDispatchConfinement::test_write_escape_refused",
      "packages/nodus/tests/test_nodus_tools.py::TestDispatchConfinement::test_write_traversal_refused",
      "packages/nodus/tests/test_nodus_tools.py::TestDispatchCwdAnchoring::test_glob_defaults_to_cwd",
      "packages/nodus/tests/test_nodus_tools.py::TestDispatchTool::test_dispatch_edit_file",
      "packages/nodus/tests/test_nodus_tools.py::TestDispatchTool::test_dispatch_edit_file_replace_all",
      "packages/nodus/tests/test_nodus_tools.py::TestDispatchTool::test_dispatch_glob_with_path",
      "packages/nodus/tests/test_nodus_tools.py::TestDispatchTool::test_dispatch_grep_with_all_options",
      "packages/nodus/tests/test_nodus_tools.py::TestDispatchTool::test_dispatch_read_file",
      "packages/nodus/tests/test_nodus_tools.py::TestDispatchTool::test_dispatch_read_file_with_offset_limit",
      "packages/nodus/tests/test_nodus_tools.py::TestDispatchTool::test_dispatch_write_file",
      "packages/nodus/tests/test_nodus_tools.py::TestDispatchTool::test_edit_file_path_alias",
      "packages/nodus/tests/test_nodus_tools.py::TestDispatchTool::test_read_file_path_alias",
      "packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_absolute_doubled_scratch_dir",
      "packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_coerce_basename_to_expected",
      "packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_dispatch_write_accepts_garbled_drive",
      "packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_fused_drive_and_doubled_dir",
      "packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_healthy_relative_unchanged",
      "packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_unix_abs_garble",
      "packages/nodus/tests/test_secret_redaction.py::test_dispatch_tool_normal_output_untouched",
      "packages/nodus/tests/test_secret_redaction.py::test_dispatch_tool_redacts_real_file"
    ]
  },
  {
    "t": 1790918591.474,
    "kind": "fix_rejected",
    "test": "packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_drive_underscore_prefix",
    "node": "nb-h100-02",
    "target_fixed": true,
    "regressions": 32
  },
  {
    "t": 1790918591.474,
    "kind": "gpu_release",
    "released": [
      "nb-h100-00",
      "nb-h100-01"
    ],
    "count": 2
  }
]
```
