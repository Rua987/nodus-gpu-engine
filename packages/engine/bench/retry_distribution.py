"""À quelle tentative Nemotron finit-il par répondre ?

Mesure la distribution, pas un score de run. Coûte des appels réels — exige
``--i-know-cost``. Plafond max_tokens = patch via chat_nebius
(``NGE_PATCH_MAX_TOKENS``, défaut ``PATCH_MAX_TOKENS``) et raisonnement
du chemin patch (``NGE_THINKING_PATCH``), comme l'orchestrateur.

    python -m bench.retry_distribution --i-know-cost
"""
import argparse
import sys
import time
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from nge import config as _cfg, llm_text
from nge.orchestrator import NgeOrchestrator
from nge.backends import usage as _usage
from nge.backends.nebius import (chat_nebius, resolve_patch_max_tokens,
                                 resolve_thinking)

MAX_ATTEMPTS, TRIALS, BACKOFF = 4, 5, 2.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--i-know-cost", action="store_true",
                    help="required: this bench calls Nemotron for real")
    ap.add_argument("--trials", type=int, default=TRIALS)
    ap.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS)
    args = ap.parse_args()
    patch_cap = resolve_patch_max_tokens()
    if not args.i_know_cost:
        print("refusing: this bench spends Token Factory credits.\n"
              "Re-run with --i-know-cost after reading the estimate.\n"
              f"  trials={args.trials} max_attempts={args.max_attempts} "
              f"-> up to {args.trials * args.max_attempts} calls, "
              f"max_tokens={patch_cap}/call",
              file=sys.stderr)
        return 2

    cfg = _cfg.load()
    _usage.reset_usage()
    _usage.set_jsonl_path(cfg.out_dir / "nemotron_usage.jsonl")
    print(f"[bench] max_tokens={patch_cap}  "
          f"trials={args.trials} max_attempts={args.max_attempts}")

    o = NgeOrchestrator(config=cfg)
    f = {"test": "packages/nodus/tests/test_nodus_tools.py::TestRepairLlmFilePath::test_missing_colon_cusers",
         "error": "(no message)",
         "context": "packages/nodus/tests/test_nodus_tools.py:150: in test_missing_colon_cusers\n    assert got.lower()"}
    f["under_test"] = o._under_test(f, "packages/nodus")
    excerpt = o._source_excerpt(f["context"])
    prompt = (
        "A test is failing. Reply with ONLY a unified diff (```diff fenced) "
        "that fixes it - no prose.\n"
        f"Test: {f['test']}\nError: {f['error']}\n"
        f"\nTraceback:\n{f['context']}\n" + (f"\n{excerpt}\n" if excerpt else "")
        + (f"\n{f['under_test']}\n" if f['under_test'] else ""))

    rank = Counter()
    for t in range(1, args.trials + 1):
        got_at = None
        for attempt in range(1, args.max_attempts + 1):
            if attempt > 1:
                time.sleep(BACKOFF * (attempt - 1))
            try:
                msg = chat_nebius([{"role": "user", "content": prompt}],
                                  cfg.nemotron_model, None,
                                  max_tokens=patch_cap,
                                  thinking=resolve_thinking("patch"))
            except Exception:
                continue
            if llm_text.unified_diff(msg):
                got_at = attempt
                break
        rank[got_at] += 1
        print(f"  essai {t:>2}: patch a la tentative {got_at}", flush=True)

    print("\n=== distribution ===")
    cum = 0
    for k in range(1, args.max_attempts + 1):
        cum += rank[k]
        print(f"tentative {k}: {rank[k]:>3}   →  {100 * cum / args.trials:.0f}%")
    print(f"jamais      : {rank[None]:>3}")
    print()
    print(_usage.format_summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
