"""Smoke: Nano + Super + Ultra billed, optional live Nano→Super failover.

Coût réel Token Factory — exige ``--i-know-cost``.

    python -m bench.tier_smoke --i-know-cost
    python -m bench.tier_smoke --i-know-cost --live-failover
    python -m bench.tier_smoke --i-know-cost --max-tokens 128 --skip-local-failover
"""
from __future__ import annotations

import argparse
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from nge import config as _cfg
from nge import router
from nge.backends import usage as _usage
from nge.backends.nebius import ModelUnavailableError, chat_nebius
from nge.orchestrator import NgeOrchestrator

DEFAULT_MAX_TOKENS = 128
PROMPT = "Reply with exactly one word: pong"
# Deliberately wrong id (old lowercase) → HTTP 404 → ModelUnavailableError
BAD_NANO = "nebius:nvidia/nemotron-3-nano-30b-a3b"


def _one(label: str, model: str, max_tokens: int) -> None:
    print(f"[tier] {label}  model={model.split(':')[-1]}  max_tokens={max_tokens}")
    try:
        msg = chat_nebius([{"role": "user", "content": PROMPT}],
                          model, None, max_tokens=max_tokens)
        text = (msg.get("content") or "").strip().replace("\n", " ")[:80]
        print(f"       ok  reply={text!r}  finish={msg.get('finish_reason')}")
    except ModelUnavailableError as exc:
        print(f"       UNAVAILABLE  status={exc.status}  {exc}")
    except Exception as exc:
        print(f"       FAIL  {type(exc).__name__}: {exc}")


def _failover_local(cfg) -> None:
    calls = []

    def chat(messages, model, tools=None, max_tokens=None):
        calls.append(model)
        if "nano" in (model or "").lower():
            raise ModelUnavailableError(model, 503, "forced")
        return {"role": "assistant", "content": "pong"}

    o = NgeOrchestrator(config=cfg, chat_fn=chat)
    out = o._invoke_chat([{"role": "user", "content": PROMPT}],
                         cfg.nemotron_nano, decision="healthcheck")
    fo = [e for e in o.events if e["kind"] == "model_failover"]
    print(f"[failover] local sim  hops={len(calls)}  ok={out.get('content')!r}  "
          f"event={bool(fo)}")


def _failover_live(cfg, max_tokens: int) -> None:
    """Wrong Nano id → 404 → orchestrator hops to Super (real TF bills)."""
    before_fo = _usage.failover_count()
    snap0 = _usage.snapshot()

    def chat(messages, model, tools=None, max_tokens=None):
        return chat_nebius(messages, model, tools, max_tokens=max_tokens)

    o = NgeOrchestrator(config=cfg, chat_fn=chat)
    print(f"[failover] live  bad={BAD_NANO.split(':')[-1]} → super")
    try:
        out = o._invoke_chat(
            [{"role": "user", "content": PROMPT}],
            BAD_NANO, max_tokens=max_tokens, decision="healthcheck")
        text = (out.get("content") or "").strip().replace("\n", " ")[:80]
        print(f"       ok  reply={text!r}  finish={out.get('finish_reason')}")
    except Exception as exc:
        print(f"       FAIL  {type(exc).__name__}: {exc}")
        return
    fo = [e for e in o.events if e["kind"] == "model_failover"]
    print(f"       event={bool(fo)}  ledger_failovers="
          f"{_usage.failover_count() - before_fo}")
    if fo:
        print(f"       from={fo[0].get('from_model')}  to={fo[0].get('to_model')}  "
              f"status={fo[0].get('status')}")
    # Super should have gained a call vs snap0
    snap1 = _usage.snapshot()
    super_id = cfg.nemotron_super.split(":", 1)[-1]
    c0 = (snap0.get(super_id) or {}).get("calls", 0)
    c1 = (snap1.get(super_id) or {}).get("calls", 0)
    print(f"       super_calls Δ={c1 - c0}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--i-know-cost", action="store_true")
    ap.add_argument("--skip-ultra", action="store_true")
    ap.add_argument("--skip-local-failover", action="store_true")
    ap.add_argument("--live-failover", action="store_true",
                    help="404 Nano id → real Super hop (extra TF call)")
    ap.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    args = ap.parse_args()
    if not args.i_know_cost:
        print("refusing: spends Token Factory credits.\n"
              "Re-run: python -m bench.tier_smoke --i-know-cost "
              "[--live-failover]\n"
              f"  ~3 chats × max_tokens={args.max_tokens} "
              f"(+1 Super if --live-failover)",
              file=sys.stderr)
        return 2

    cfg = _cfg.load()
    _usage.reset_usage()
    _usage.set_jsonl_path(cfg.out_dir / "nemotron_usage.jsonl")
    print(f"[bench] max_tokens={args.max_tokens}  "
          f"live_failover={args.live_failover}")

    for decision in ("healthcheck", "slotfill", "plan"):
        rec = router.route(decision, cfg)
        _usage.record_route(rec["tier"], decision)
        if rec["tier"] == "ultra" and args.skip_ultra:
            print(f"[tier] ultra  SKIP (--skip-ultra)  would={rec['model']}")
            continue
        _one(rec["tier"], rec["model"], args.max_tokens)

    if not args.skip_local_failover:
        _failover_local(cfg)
    if args.live_failover:
        _failover_live(cfg, args.max_tokens)

    print(_usage.format_summary())
    print("[bench] refresh Token Factory → Usage to compare invoice vs ledger")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
