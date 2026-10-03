"""Does Nemotron's reasoning help or starve each call class? Measure, per arm.

Nemotron 3 Super reasons before it answers, and those tokens count against
``max_tokens``. Live, slot-fill (256) came back as 256 reasoning tokens and
an empty reply, and patches were cut at 2048 with nothing written. Turning
reasoning off is not a free win either: a first try produced diffs whose file
headers lacked ``--- ``/``+++ ``. This bench measures each setting on the
real loop instead of guessing (docs/MEASURE_BEFORE_LEVER.md).

Per run: Token Factory sandboxes run the real suite (real failures, real
whole-suite re-verification), the fleet is simulated, the plan is the keyword
heuristic so the autofix gate opens. Arms are interleaved run by run so a
slow or flaky hour hits every arm alike.

    python -m bench.thinking_ab --i-know-cost
    python -m bench.thinking_ab --i-know-cost --runs 3 --csv out/thinking_ab.csv
    python -m bench.thinking_ab --i-know-cost --arms baseline,short_off --sandbox mock
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Optional

# Every arm sets all three knobs, so an arm means the same thing whatever the
# defaults in nge/backends/nebius.py become. "model" = send no reasoning switch.
ARMS = {
    # behaviour before 2026-10-01: model default (reasoning on), patch 2048
    "baseline": {"NGE_THINKING_SHORT": "model", "NGE_THINKING_PATCH": "model",
                 "NGE_PATCH_MAX_TOKENS": "2048"},
    "short_off": {"NGE_THINKING_SHORT": "off", "NGE_THINKING_PATCH": "model",
                  "NGE_PATCH_MAX_TOKENS": "2048"},
    "short_off_patch_off": {"NGE_THINKING_SHORT": "off", "NGE_THINKING_PATCH": "off",
                            "NGE_PATCH_MAX_TOKENS": "2048"},
    # the defaults chosen from this bench (2026-10-01)
    "short_off_patch_8k": {"NGE_THINKING_SHORT": "off", "NGE_THINKING_PATCH": "on",
                           "NGE_PATCH_MAX_TOKENS": "8192"},
}
_ARM_KEYS = ("NGE_THINKING_SHORT", "NGE_THINKING_PATCH", "NGE_PATCH_MAX_TOKENS")

SCENARIO = {
    "task": "Run the failing pytest suite across the GPU fleet, triage, fix, report.",
    "shards": 2,
    "gpu_type": "H100",
    "target": "packages/nodus/tests",
    "collect": [],
}

# nodus: the vendored suite - its live failures are Windows-only tests, so
#        "verified" cannot separate the arms there (docs/FIX_LOOP.md).
# bugbench: six seeded bugs with a known fix, OS-independent; every bug is
#        attempted (the product default tries 3) and each verified patch is
#        re-checked against held-out cases the model never saw.
TARGETS = {
    "nodus": {"target": "packages/nodus/tests", "max_fixes": None},
    "bugbench": {"target": "packages/engine/bench/bugbench/tests", "max_fixes": 6},
}
_ENGINE = Path(__file__).resolve().parents[1]
_REPO = _ENGINE.parents[1]
_HOLDOUT = _ENGINE / "bench" / "bugbench_holdout" / "test_holdout.py"


def holdout_check(patch: str, test_id: str) -> Optional[bool]:
    """Apply ``patch`` to a copy of bugbench and run the held-out cases of the
    bug ``test_id`` targets. True = a real fix, False = it only satisfied the
    visible test (or does not apply), None = not a bugbench test."""
    import shutil
    import subprocess
    import tempfile

    import patch_ng

    bugs = _holdout_bugs()
    key = next((k for k, t in bugs.items() if test_id.endswith(t)), None)
    if key is None:
        return None
    rel = Path("packages/engine/bench/bugbench")
    with tempfile.TemporaryDirectory(prefix="nge_holdout_") as td:
        root = Path(td)
        shutil.copytree(_REPO / rel, root / rel,
                        ignore=shutil.ignore_patterns("__pycache__"))
        ps = patch_ng.fromstring((patch or "").encode("utf-8"))
        if not ps or not ps.apply(strip=1, root=str(root)):
            return False
        env = {**os.environ, "PYTHONPATH": str(root / rel)}
        r = subprocess.run([sys.executable, "-m", "pytest", str(_HOLDOUT), "-q",
                            "-p", "no:cacheprovider", "-k", f"test_{key}"],
                           cwd=td, env=env, capture_output=True, text=True,
                           timeout=120)
        return r.returncode == 0


def _holdout_bugs() -> dict:
    import ast
    tree = ast.parse(_HOLDOUT.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "BUG":
            return ast.literal_eval(node.value)
    return {}

_SLOT_FAIL = ("slotfill_empty", "slotfill_truncated", "slotfill_error",
              "slotfill_off_target", "slotfill_bad_flags", "slotfill_rejected")
_PATCH_FILE = re.compile(r"^\+\+\+ b/(\S+)", re.M)


def _tests_only(patch: str) -> bool:
    """True when every file the patch edits is a test file - a "fix" that may
    just rewrite the assertion to match the bug."""
    files = _PATCH_FILE.findall(patch or "")
    return bool(files) and all(
        "/tests/" in f or Path(f).name.startswith("test_") for f in files)


def _set_arm(env: dict) -> None:
    for k in _ARM_KEYS:
        os.environ.pop(k, None)
    os.environ.update(env)


def run_once(arm: str, sandbox: str, out_root: Path, target: str = "nodus") -> dict:
    from nge import config as _cfg
    from nge.backends import register
    from nge.backends import usage as _usage
    from nge.backends.nebius import chat_nebius
    from nge.orchestrator import NgeOrchestrator
    from nge.tools import handlers

    _set_arm(ARMS[arm])
    out = out_root / f"{arm}_{int(time.time())}"
    cfg = _cfg.load(fleet_mode="mock", sandbox_mode=sandbox, out_dir=out)
    from nge import planner as _pl
    cfg = replace(cfg, nodus_plan_ckpt=str(Path(_pl.FORCE_HEURISTIC) / "missing.pt"))
    register.apply()
    _usage.reset_usage()
    _usage.set_jsonl_path(out / "nemotron_usage.jsonl")

    def chat_fn(messages, mdl=None, tools=None, max_tokens=None, thinking=None):
        return chat_nebius(messages, mdl or cfg.nemotron_model, tools,
                           max_tokens=max_tokens, thinking=thinking)

    o = NgeOrchestrator(config=cfg, chat_fn=chat_fn)
    if TARGETS[target]["max_fixes"]:
        o.MAX_FIXES = TARGETS[target]["max_fixes"]
    handlers.reset_state(o.config)
    t0 = time.time()
    error = ""
    try:
        o.run({**SCENARIO, "target": TARGETS[target]["target"]})
    except Exception as exc:                       # a run that dies is data too
        error = f"{type(exc).__name__}: {exc}"[:200]
    wall = time.time() - t0

    kinds = Counter(e["kind"] for e in o.events)
    slot_calls = sum(1 for e in o.events
                     if e["kind"] == "model_route" and e.get("decision") == "slotfill")
    slot_fail = sum(kinds[k] for k in _SLOT_FAIL)
    fixes = list(o.fixes)
    verified = [f for f in fixes if f.get("verified")]
    snap = _usage.snapshot()
    led = {k: sum(r.get(k, 0) or 0 for r in snap.values())
           for k in ("calls", "prompt_tokens", "completion_tokens", "reasoning_tokens")}
    est = sum(_usage.estimate_usd_ht(r["prompt_tokens"], r["completion_tokens"],
                                     r.get("tier") or "super") for r in snap.values())
    return {
        "arm": arm, "sandbox": sandbox, "error": error, "wall_s": round(wall, 1),
        "unique_failures": next((e.get("unique_failures") for e in o.events
                                 if e["kind"] == "triage"), 0),
        "slot_calls": slot_calls, "slot_ok": slot_calls - slot_fail,
        "slot_truncated": kinds["slotfill_truncated"], "slot_empty": kinds["slotfill_empty"],
        "slot_off_target": kinds["slotfill_off_target"],
        "slot_bad": kinds["slotfill_bad_flags"] + kinds["slotfill_rejected"],
        "fix_tried": len(fixes),
        "patch_produced": sum(1 for f in fixes if f.get("patch")),
        "patch_truncated": kinds["patch_truncated"],
        "patch_unparsed": kinds["patch_unparsed"],
        "patch_empty": kinds["patch_empty"],
        "context_invented": kinds["fix_context_invented"],
        "verified": len(verified),
        "verified_tests_only": sum(1 for f in verified if _tests_only(f.get("patch"))),
        "rejected": kinds["fix_rejected"],
        "regression": kinds["fix_regression"],
        **led, "usd_est": round(est, 5),
        "target": target,
        "holdout_ok": sum(1 for f in verified
                          if holdout_check(f.get("patch"), f.get("test", "")) is True)
        if target == "bugbench" else "",
        "out": str(out),
    }


def _summary(rows: list) -> str:
    by = defaultdict(list)
    for r in rows:
        by[r["arm"]].append(r)
    hdr = (f"{'arm':<22}{'runs':>5}{'slot ok':>10}{'patch':>9}{'trunc':>7}"
           f"{'unpars':>8}{'invent':>8}{'verif':>7}{'holdout':>9}{'tests-only':>12}"
           f"{'regr':>6}{'out tok':>9}{'reason':>8}{'$ est':>9}")
    lines = [hdr, "-" * len(hdr)]
    for arm, rs in by.items():
        s = lambda k: sum(r[k] or 0 for r in rs)     # noqa: E731
        hold = (str(s("holdout_ok")) if any(r["holdout_ok"] != "" for r in rs)
                else "-")
        lines.append(
            f"{arm:<22}{len(rs):>5}{s('slot_ok'):>5}/{s('slot_calls'):<4}"
            f"{s('patch_produced'):>4}/{s('fix_tried'):<4}{s('patch_truncated'):>7}"
            f"{s('patch_unparsed'):>8}{s('context_invented'):>8}{s('verified'):>7}"
            f"{hold:>9}{s('verified_tests_only'):>12}"
            f"{s('regression'):>6}{s('completion_tokens'):>9}{s('reasoning_tokens'):>8}"
            f"{sum(r['usd_est'] for r in rs):>9.4f}")
        errs = [r["error"] for r in rs if r["error"]]
        if errs:
            lines.append(f"{'':<22}  run errors: {errs}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--i-know-cost", action="store_true",
                    help="required: every run spends Nemotron calls (and sandboxes)")
    ap.add_argument("--runs", type=int, default=1, help="runs per arm")
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--target", default="nodus", choices=tuple(TARGETS),
                    help="bugbench = seeded OS-independent bugs with held-out checks")
    ap.add_argument("--sandbox", default="token_factory", choices=("token_factory", "mock"),
                    help="mock = synthetic failures: only the reply-side numbers mean anything")
    ap.add_argument("--csv", type=Path, default=None)
    args = ap.parse_args(argv)
    if not args.i_know_cost:
        print("refusing: this spends Token Factory credits. Re-run with --i-know-cost.",
              file=sys.stderr)
        return 2
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    unknown = [a for a in arms if a not in ARMS]
    if unknown:
        print(f"unknown arm(s) {unknown}; choose from {list(ARMS)}", file=sys.stderr)
        return 2

    os.environ.setdefault("NGE_TRACK", "nebius")
    from nge import config as _cfg
    out_root = _cfg.load().out_dir / "thinking_ab"
    rows = []
    saved = {k: os.environ.get(k) for k in _ARM_KEYS}
    try:
        for i in range(args.runs):
            for arm in arms:                     # interleaved, not arm-by-arm
                print(f"[thinking_ab] run {i + 1}/{args.runs}  arm={arm}", flush=True)
                row = run_once(arm, args.sandbox, out_root, args.target)
                row["round"] = i + 1
                rows.append(row)
                print(f"  -> slot {row['slot_ok']}/{row['slot_calls']}  "
                      f"patch {row['patch_produced']}/{row['fix_tried']}  "
                      f"verified {row['verified']} (holdout {row['holdout_ok'] or '-'})  "
                      f"trunc {row['patch_truncated']}  "
                      f"unparsed {row['patch_unparsed']}  reasoning={row['reasoning_tokens']}"
                      + (f"  ERROR {row['error']}" if row["error"] else ""), flush=True)
                if args.csv:                     # write as we go: a crash keeps data
                    args.csv.parent.mkdir(parents=True, exist_ok=True)
                    with args.csv.open("w", newline="", encoding="utf-8") as f:
                        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                        w.writeheader()
                        w.writerows(rows)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    print("\n" + _summary(rows))
    if args.sandbox == "mock":
        print("\n(sandbox=mock: failures are synthetic fixtures - verified/regression "
              "say nothing about real patches)")
    if args.csv:
        print(f"\nCSV: {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
