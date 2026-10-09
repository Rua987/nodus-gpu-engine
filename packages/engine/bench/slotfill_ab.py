"""Free-text vs typed slot-fill, on the real slot-fill call and real shard contexts.

Token Factory enforces a strict ``json_schema`` on Nemotron 3 Super at decode
time (probe 2026-10-08). With ``NGE_SLOTFILL=schema`` the model only picks
typed options and the engine writes the command; in free text the model writes
the command and the guards catch what is wrong. This measures both on the same
prompts: how often the command survives the guards, latency, output tokens.
No sandbox, no test runs - only the slot-fill call.

    python -m bench.slotfill_ab --i-know-cost
    python -m bench.slotfill_ab --i-know-cost --calls 10 --csv out/slotfill_ab.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from collections import Counter
from pathlib import Path

TARGETS = ["packages/nodus/tests", "packages/engine/bench/bugbench/tests"]
SHARDS = 2
TASK = "Run the failing pytest suite across the GPU fleet, triage the failures, propose fixes."
PLAN = ["bash", "edit_file", "write_file"]
# events after which _shard_command used the deterministic template instead
FALLBACK = ("slotfill_off_target", "slotfill_bad_flags", "slotfill_narrowed",
            "slotfill_rejected", "slotfill_empty", "slotfill_truncated",
            "slotfill_error", "slotfill_schema_violated", "model_unavailable")


def run(calls: int, out_csv: Path) -> list:
    from nge import config as _cfg
    from nge.backends import usage as _usage
    from nge.demo_nebius import _live_chat_fn
    from nge.orchestrator import NgeOrchestrator

    cfg = _cfg.load(fleet_mode="mock", sandbox_mode="mock")
    rows = []
    for n in range(calls):                     # interleaved: a slow minute hits both
        for mode in ("text", "schema"):
            os.environ["NGE_SLOTFILL"] = mode
            for target in TARGETS:
                o = NgeOrchestrator(config=cfg, chat_fn=_live_chat_fn(cfg.nemotron_model))
                files = o._discover_test_files(target)
                for i in range(SHARDS):
                    own = o._shard_targets(files, i, SHARDS)
                    o.events.clear()
                    _usage.reset_usage()
                    t0 = time.perf_counter()
                    cmd = o._shard_command(TASK, PLAN, target, i, SHARDS, own)
                    dt = time.perf_counter() - t0
                    kinds = [e["kind"] for e in o.events]
                    why = next((k for k in kinds if k in FALLBACK), "")
                    snap = _usage.snapshot()
                    rows.append({
                        "round": n, "mode": mode, "target": target.split("/")[1],
                        "shard": i, "files": len(own), "usable": int(not why),
                        "fallback_reason": why, "seconds": round(dt, 2),
                        "out_tokens": sum(r.get("completion_tokens", 0) or 0
                                          for r in snap.values()),
                        "command": cmd[-160:],
                    })
                    print(f"{mode:<6} {target.split('/')[1]:<7} shard {i}: "
                          f"{'ok ' if not why else why:<24} {dt:5.2f}s  {cmd[-90:]}")
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return rows


def summary(rows: list) -> str:
    lines = [f"{'mode':<8}{'calls':>6}{'usable':>9}{'mean s':>9}{'mean out tok':>14}  fallbacks"]
    for mode in ("text", "schema"):
        rs = [r for r in rows if r["mode"] == mode]
        if not rs:
            continue
        fb = Counter(r["fallback_reason"] for r in rs if r["fallback_reason"])
        lines.append(f"{mode:<8}{len(rs):>6}{sum(r['usable'] for r in rs):>5}/{len(rs):<3}"
                     f"{sum(r['seconds'] for r in rs) / len(rs):>9.2f}"
                     f"{sum(r['out_tokens'] for r in rs) / len(rs):>14.1f}  {dict(fb) or '-'}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--i-know-cost", action="store_true", help="live Nemotron calls (cents)")
    ap.add_argument("--calls", type=int, default=10, help="rounds; each = 8 calls")
    ap.add_argument("--csv", default="out/slotfill_ab.csv")
    args = ap.parse_args(argv)
    if not args.i_know_cost:
        print("refusing: live Nemotron calls - pass --i-know-cost", file=sys.stderr)
        return 2
    rows = run(args.calls, Path(args.csv))
    print()
    print(summary(rows))
    print(f"csv: {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
