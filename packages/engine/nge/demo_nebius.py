"""End-to-end demo of the Nodus-GPU Engine.

    python -m nge.demo_nebius --mock      # deterministic orchestrator, no creds, CI
    python -m nge.demo_nebius --local     # REAL Nodus ReAct + Ollama (free)
    python -m nge.demo_nebius --deepseek  # PERSONAL: ReAct + DeepSeek API (off Nebius track)
    python -m nge.demo_nebius --live      # Nemotron @ Nebius (hackathon path)

``--mock`` is the judge path. ``--local`` / ``--deepseek`` prove MCP tool wiring
with a non-Nebius model. ``--live`` is the submission path (``NGE_TRACK=nebius``).
``--deepseek`` must never set that track.
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

_DEFAULT_OLLAMA = "qwen3.5:2b"
_DEFAULT_DEEPSEEK = "deepseek-chat"

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
    """Route live chat through ``chat_nebius`` so max_tokens + usage apply."""
    from nge.backends import register
    from nge.backends.nebius import chat_nebius
    register.apply()

    def chat_fn(messages, mdl=None, tools=None, max_tokens=None):
        return chat_nebius(messages, mdl or model, tools, max_tokens=max_tokens)
    return chat_fn


# ── orchestrated path (--mock / --live) ─────────────────────────────────────

def run_orchestrated(args, live: bool) -> int:
    scenario = _load_scenario(Path(args.scenario))
    if args.shards:
        scenario["shards"] = args.shards

    if live:
        os.environ.setdefault("NGE_TRACK", "nebius")
        # env can pin either half back to mock for a partial-real run, e.g.
        #   NGE_FLEET_MODE=mock python -m nge.demo_nebius --live
        cfg = _cfg.load(fleet_mode=os.environ.get("NGE_FLEET_MODE") or "nebius",
                        sandbox_mode=os.environ.get("NGE_SANDBOX") or "token_factory")
        from nge.backends import usage as _usage
        from nge.backends.nebius import resolve_max_tokens
        _usage.reset_usage()
        _usage.set_jsonl_path(cfg.out_dir / "nemotron_usage.jsonl")
        chat_fn = _live_chat_fn(cfg.nemotron_model)
        print(f"[live] Nemotron={cfg.nemotron_model}  "
              f"fleet={cfg.fleet_mode}  sandbox={cfg.sandbox_mode}")
        print(f"[live] max_tokens default={resolve_max_tokens()} "
              f"(slot=256 patch=2048; override NGE_NEMOTRON_MAX_TOKENS)")
    else:
        cfg = _cfg.load(fleet_mode="mock", sandbox_mode="mock")
        chat_fn = None
        if not args.watch:
            print("[mock] deterministic run - no credentials, no network")

    if getattr(args, "heuristic_plan", False):
        from dataclasses import replace
        # Missing ckpt → planner falls back to keyword heuristic (edit_file on
        # the default triage task) so the autofix gate opens for judge films.
        cfg = replace(
            cfg,
            nodus_plan_ckpt=str(Path("__nge_force_heuristic__") / "missing.pt"),
        )
        print("[planner] --heuristic-plan: skip 324M -> keyword plan "
              "(expect edit_file -> autofix ON on default scenario)")

    # --mission overrides the scenario file: the engineer states the what,
    # the model (when there is one) extracts the how, the regex is the floor.
    if getattr(args, "mission", None):
        from nge.mission import parse_mission, parse_mission_llm
        mis = (parse_mission_llm(args.mission, chat_fn, cfg.nemotron_model)
               if chat_fn else parse_mission(args.mission))
        scenario = mis.scenario()
        if args.shards:
            scenario["shards"] = args.shards
        print(f"[mission] {mis.shards}x{mis.gpu_type} target={mis.target} "
              f"self_heal={mis.self_heal} auto_fix={mis.auto_fix}")
        for d in mis.derived:
            print(f"          - {d}")

    from nge import planner as _planner
    _ck, _ok, _note = _planner.ckpt_status(cfg)
    print(f"[planner] {_note}" if _ok else f"[planner] WARNING - {_note}")

    watch = None
    if args.watch:
        from nge.watch import ConsoleWatch
        watch = ConsoleWatch(delay=args.watch_delay)

    orch = NgeOrchestrator(config=cfg, chat_fn=chat_fn, telemetry=watch)
    try:
        report = orch.run(scenario)
    except Exception as exc:
        from nge.fleet.capabilities import RealGpuRequired
        if isinstance(exc, RealGpuRequired):
            print(f"\n[capabilities refused] {exc}", file=sys.stderr)
            return 2
        if isinstance(exc, (NotImplementedError, RuntimeError)):
            print(f"\n[live blocked] {type(exc).__name__}: {exc}\n"
                  "The live path (NebiusFleet + TokenFactorySandbox) is wired and "
                  "authenticates; it needs Token Factory Sandboxes beta access on "
                  "the key. Use --mock for the working end-to-end path.",
                  file=sys.stderr)
            return 3
        raise

    print(f"\nplan({report.plan_source}): {report.plan_names}")
    gated = [e for e in report.events if e.get("kind") == "plan_gated_autofix"]
    if gated and not gated[-1].get("allowed"):
        print("  plan gate: autofix OFF "
              "(plan has no edit_file/write_file — triage only)")
    elif gated and gated[-1].get("allowed"):
        print(f"  plan gate: autofix ON  because={gated[-1].get('because')}")
    if live:
        from nge.backends import usage as _usage
        print(_usage.format_summary())
        fos = [e for e in report.events if e.get("kind") == "model_failover"]
        if fos:
            print(f"[usage] failovers this run: {len(fos)}")
        # Honest: routes alone ≠ billed Ultra/Nano (324M plan, heal-gated Nano)
        billed = _usage.snapshot()
        routed = {r["tier"] for r in report.routes}
        billed_tiers = {_usage.guess_tier(m) for m in billed}
        gap = routed - billed_tiers
        if gap:
            print(f"[usage] routed but not billed this run: {', '.join(sorted(gap))}")
    tiers = {}
    for r in report.routes:
        tiers.setdefault(r["tier"], set()).add(r["decision"])
    print("model routing: " + " | ".join(
        f"{t}->{','.join(sorted(d))}" for t, d in
        sorted(tiers.items(), key=lambda x: ("ultra", "super", "nano").index(x[0]))))
    if not args.watch:
        for s in report.shards:
            tag = f"  (migrated from {s.migrated_from})" if s.migrated_from else ""
            print(f"  shard {s.index} on {s.node_id}: exit={s.exit_code} "
                  f"{s.duration_s}s  {len(s.failures)} failure(s){tag}")
    for rm in report.remediations:
        print(f"  ! GPU pressure: {rm['from']} {rm['reason']} "
              f"({rm.get('temp_c')}C) -> re-provisioned {rm['to']}")
    verified = [x for x in report.fixes if x.get("verified")]
    print(f"unique failures: {len(report.failures)}  |  "
          f"auto-fixed & verified: {len(verified)}/{len(report.fixes)}")
    for x in report.fixes:
        mark = "OK " if x.get("verified") else ("-- " if not x.get("patch") else "KO ")
        print(f"  fix {mark} {x['test']}")
    print(f"artifact: {report.artifact_path}")
    if report.html_path:
        print(f"html:     {report.html_path}")
    if args.json:
        print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    return 0 if report.ok else 1


# ── personal ReAct path (--local Ollama / --deepseek API) ───────────────────

def _ollama_up() -> bool:
    import urllib.request
    url = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _needs_ollama(model: str) -> bool:
    """True when the model is served by local Ollama (not a cloud API id)."""
    try:
        import nodus_backends as nb
        return nb.detect_backend(model) == "ollama"
    except Exception:
        return True


def _refuse_nebius_track(label: str):
    """Personal modes must not run under the hackathon guard."""
    if _cfg.hackathon_track():
        print(f"[{label}] refused: NGE_TRACK=nebius is the hackathon path.\n"
              "Unset NGE_TRACK (or set it empty) for personal Ollama/DeepSeek.",
              file=sys.stderr)
        return 2
    return None


def run_react_personal(args, *, provider: str, default_model: str) -> int:
    """Real Nodus ReAct + nge-gpu MCP; fleet/sandbox stay mock.

    ``provider`` is only a banner label (``local`` / ``deepseek``) — the real
    backend comes from ``nodus_backends.detect_backend(model)``.
    """
    blocked = _refuse_nebius_track(provider)
    if blocked is not None:
        return blocked

    from nge.mcp_config import write_config

    model = args.model or default_model
    task = args.task or _LOCAL_TASK

    # A deepseek model name that routes to Ollama is a config mistake, not a
    # missing-server problem - check it first so it's reported as such even
    # when Ollama also happens to be down (it always is on a clean machine).
    if provider == "deepseek" and _needs_ollama(model):
        print(f"[{provider}] model {model!r} routes to Ollama, not DeepSeek API.\n"
              f"Use {_DEFAULT_DEEPSEEK!r} or deepseek-reasoner.",
              file=sys.stderr)
        return 2

    if _needs_ollama(model) and not _ollama_up():
        print(f"[{provider}] Ollama not reachable at "
              f"{os.environ.get('OLLAMA_URL', 'http://localhost:11434')} - "
              f"start it (`ollama serve`) and `ollama pull {model}`.",
              file=sys.stderr)
        return 3

    cfg_path = write_config(_ENGINE_DIR / "out" / f"mcp.{provider}.json",
                            fleet_mode="mock", sandbox_mode="mock")
    print(f"[{provider}] PERSONAL (off Nebius track)  model={model}  "
          f"mcp={cfg_path.name}  fleet=mock")

    from nge.nodus_patches import neutralize_mcp_prompt
    neutralize_mcp_prompt()

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
    mode.add_argument("--mock", action="store_true",
                      help="deterministic orchestrator (default)")
    mode.add_argument("--local", action="store_true",
                      help="personal: ReAct + local Ollama (free)")
    mode.add_argument("--deepseek", action="store_true",
                      help="personal: ReAct + DeepSeek API (off Nebius track)")
    mode.add_argument("--live", action="store_true",
                      help="hackathon: Nemotron @ Nebius + real fleet/sandbox")
    ap.add_argument("--scenario", default=str(_DEFAULT_SCENARIO))
    ap.add_argument("--mission", default=None,
                    help="natural-language mission, overrides --scenario "
                         "(parsed by the model when one is available)")
    ap.add_argument("--shards", type=int, default=None)
    ap.add_argument("--json", action="store_true", help="print the RunReport as JSON")
    ap.add_argument("--watch", action="store_true",
                    help="--mock/--live: live fleet console view (util/temp bars, migration)")
    ap.add_argument("--watch-delay", type=float, default=0.6,
                    help="seconds between --watch frames (default 0.6)")
    ap.add_argument("--heuristic-plan", action="store_true",
                    help="skip 324M checkpoint; keyword plan (often unlocks "
                         "autofix via edit_file — judge film of verified patches)")
    ap.add_argument("--model", default=None,
                    help="override model (--local default qwen3.5:2b; "
                         "--deepseek default deepseek-chat)")
    ap.add_argument("--task", default=None, help="override the ReAct task")
    ap.add_argument("--max-rounds", type=int, default=14)
    ap.add_argument("--text-tools", action="store_true",
                    help="JSON-text tool mode (models without native tool calling)")
    args = ap.parse_args(argv)

    if args.local:
        return run_react_personal(args, provider="local",
                                  default_model=_DEFAULT_OLLAMA)
    if args.deepseek:
        return run_react_personal(args, provider="deepseek",
                                  default_model=_DEFAULT_DEEPSEEK)
    return run_orchestrated(args, live=bool(args.live))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
