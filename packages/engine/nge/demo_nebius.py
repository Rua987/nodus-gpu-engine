"""End-to-end demo of the Nodus-GPU Engine.

    python -m nge.demo_nebius --mock          # default: no creds, no network, CI
    python -m nge.demo_nebius --live          # Nemotron + real fleet/sandbox (skeleton)

Mock is the judge path: deterministic plan -> 3-node fleet -> 3 sandboxes ->
triage -> Markdown artifact, exit 0.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from nge import config as _cfg
from nge.orchestrator import NgeOrchestrator

_DEFAULT_SCENARIO = Path(__file__).resolve().parent.parent / "scenarios" / "fleet_test_triage.json"


def _load_scenario(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _live_chat_fn(model):
    """Nemotron slot-fill via the vendored Nodus backend + the nebius: route."""
    from nge.backends import register
    register.apply()
    import nodus_agent as na

    def chat_fn(messages, mdl=model, tools=None):
        return na._chat(messages, mdl, tools)
    return chat_fn


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Nodus-GPU Engine demo")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--mock", action="store_true", help="deterministic, no creds (default)")
    mode.add_argument("--live", action="store_true", help="Nemotron + real fleet/sandbox")
    ap.add_argument("--scenario", default=str(_DEFAULT_SCENARIO))
    ap.add_argument("--shards", type=int, default=None)
    ap.add_argument("--json", action="store_true", help="print the RunReport as JSON")
    args = ap.parse_args(argv)

    live = bool(args.live)
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
              "Use --mock for the working end-to-end path.",
              file=sys.stderr)
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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
