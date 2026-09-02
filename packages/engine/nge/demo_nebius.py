"""End-to-end demo of the Nodus-GPU Engine.

    python -m nge.demo_nebius --mock     # deterministic orchestrator, no creds, CI
    python -m nge.demo_nebius --local    # REAL Nodus ReAct loop, local Ollama model
                                         #   -> real MCP calls to the GPU tools
    python -m nge.demo_nebius --live     # Nemotron @ Nebius + real fleet/sandbox (skeleton)

``--mock`` is the judge path. ``--local`` proves the same tool + MCP wiring the
Nebius path will use, driven by a local model instead of Nemotron (no cloud,
no credits). ``--live`` swaps the model id + fleet/sandbox mode.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from nge import config as _cfg
from nge.orchestrator import NgeOrchestrator

_ENGINE_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_SCENARIO = _ENGINE_DIR / "scenarios" / "fleet_test_triage.json"
_REPO_ROOT = _ENGINE_DIR.parent.parent

_LOCAL_TASK = (
    "Do exactly these two tool calls with the nge-gpu tools, then stop:\n"
    "1. nge-gpu.gpu_provision with n=2 and gpu_type=\"H100\"\n"
    "2. nge-gpu.run_in_sandbox with command=\"echo benchmark-ok\" and node_id=\"nb-h100-00\"\n"
    "Then answer in ONE sentence: how many nodes were provisioned and what the "
    "sandbox printed."
)


def _load_scenario(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _live_chat_fn(model):
    from nge.backends import register
    register.apply()
    import nodus_agent as na

    def chat_fn(messages, mdl=model, tools=None):
        return na._chat(messages, mdl, tools)
    return chat_fn


# ── orchestrated path (--mock / --live) ─────────────────────────────────────

def run_orchestrated(args, live: bool) -> int:
    scenario = _load_scenario(Path(args.scenario))
    if args.shards:
        scenario["shards"] = args.shards

    if live:
        os.environ.setdefault("NGE_TRACK", "nebius")
        cfg = _cfg.load(fleet_mode="nebius", sandbox_mode="token_factory")
        chat_fn = _live_chat_fn(cfg.nemotron_model)
        print(f"[live] Nemotron={cfg.nemotron_model}  fleet=nebius  sandbox=token_factory")
    else:
        cfg = _cfg.load(fleet_mode="mock", sandbox_mode="mock")
        chat_fn = None
        print("[mock] deterministic run - no credentials, no network")

    orch = NgeOrchestrator(config=cfg, chat_fn=chat_fn)
    try:
        report = orch.run(scenario)
    except (NotImplementedError, RuntimeError) as exc:
        print(f"\n[live skeleton] {type(exc).__name__}: {exc}\n"
              "The live Nebius fleet / Token Factory path is not wired yet "
              "(needs credentials + _build_client) - see docs/NEBIUS_TRACK.md.\n"
              "Use --mock for the working end-to-end path.", file=sys.stderr)
        return 3

    print(f"\nplan({report.plan_source}): {report.plan_names}")
    tiers = {}
    for r in report.routes:
        tiers.setdefault(r["tier"], set()).add(r["decision"])
    print("model routing: " + " | ".join(
        f"{t}->{','.join(sorted(d))}" for t, d in
        sorted(tiers.items(), key=lambda x: ("ultra", "super", "nano").index(x[0]))))
    for s in report.shards:
        tag = f"  (migrated from {s.migrated_from})" if s.migrated_from else ""
        print(f"  shard {s.index} on {s.node_id}: exit={s.exit_code} "
              f"{s.duration_s}s  {len(s.failures)} failure(s){tag}")
    for rm in report.remediations:
        print(f"  ! GPU pressure: {rm['from']} {rm['reason']} "
              f"({rm.get('temp_c')}C) -> re-provisioned {rm['to']}")
    print(f"unique failures: {len(report.failures)}")
    print(f"artifact: {report.artifact_path}")
    if args.json:
        print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    return 0 if report.ok else 1


# ── real Nodus ReAct loop, local Ollama model (--local) ─────────────────────

def _ollama_up() -> bool:
    import urllib.request
    url = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def run_local(args) -> int:
    from nge.mcp_config import write_config

    model = args.model or "qwen3.5:2b"
    task = args.task or _LOCAL_TASK

    if not _ollama_up():
        print("[local] Ollama not reachable at "
              f"{os.environ.get('OLLAMA_URL', 'http://localhost:11434')} - "
              "start it (`ollama serve`) and `ollama pull " + model + "`.",
              file=sys.stderr)
        return 3

    cfg_path = write_config(_ENGINE_DIR / "out" / "mcp.local.json",
                            fleet_mode="mock", sandbox_mode="mock")
    print(f"[local] model={model}  mcp={cfg_path.name}  (real ReAct loop, no cloud)")

    from nge.nodus_patches import neutralize_mcp_prompt
    neutralize_mcp_prompt()  # drop Nodus' Godot-flavoured MCP system block

    import nodus_agent as na
    result = na.run_agent(
        task,
        cwd=str(_REPO_ROOT),
        model=model,
        verbose=True,
        max_rounds=args.max_rounds,
        mcp_servers="nge-gpu",
        mcp_config=str(cfg_path),
        text_tools=args.text_tools,
    )
    print("\n" + "=" * 60)
    print(f"rounds={result.rounds}  tool_calls={result.tool_calls}  "
          f"stopped={result.stopped_reason}")
    print("answer:\n" + (result.answer or "(none)"))
    return 0 if result.tool_calls > 0 else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Nodus-GPU Engine demo")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--mock", action="store_true", help="deterministic orchestrator (default)")
    mode.add_argument("--local", action="store_true", help="real Nodus ReAct loop + local Ollama")
    mode.add_argument("--live", action="store_true", help="Nemotron @ Nebius + real fleet/sandbox")
    ap.add_argument("--scenario", default=str(_DEFAULT_SCENARIO))
    ap.add_argument("--shards", type=int, default=None)
    ap.add_argument("--json", action="store_true", help="print the RunReport as JSON")
    # --local options
    ap.add_argument("--model", default=None, help="Ollama model (default qwen3.5:2b)")
    ap.add_argument("--task", default=None, help="override the --local task")
    ap.add_argument("--max-rounds", type=int, default=14)
    ap.add_argument("--text-tools", action="store_true",
                    help="--local: JSON-text tool mode (models without native tool calling)")
    args = ap.parse_args(argv)

    if args.local:
        return run_local(args)
    return run_orchestrated(args, live=bool(args.live))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
