"""À quelle tentative Nemotron finit-il par répondre ?

Mesure la distribution, pas un score de run : on répète le même appel réel
jusqu'à 6 fois avec le backoff en place, et on note le rang de la tentative
qui produit enfin un patch. Si aucune 4e/5e ne réussit jamais, 3 suffit.
"""
import sys, time
from collections import Counter
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from nge import config as _cfg, llm_text
from nge.orchestrator import NgeOrchestrator
from nge.backends.nebius import chat_nebius

MAX_ATTEMPTS, TRIALS, BACKOFF = 6, 20, 2.0
cfg = _cfg.load()
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
for t in range(1, TRIALS + 1):
    got_at = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if attempt > 1:
            time.sleep(BACKOFF * (attempt - 1))
        try:
            msg = chat_nebius([{"role": "user", "content": prompt}],
                              cfg.nemotron_model, None)
        except Exception:
            continue
        if llm_text.unified_diff(msg):
            got_at = attempt
            break
    rank[got_at] += 1
    print(f"  essai {t:>2}: patch a la tentative {got_at}", flush=True)

print("\n=== distribution ===")
cum = 0
for k in range(1, MAX_ATTEMPTS + 1):
    cum += rank[k]
    print(f"  tentative {k}: {rank[k]:>2}  |  cumule {cum}/{TRIALS} "
          f"({100*cum/TRIALS:.0f}%)")
print(f"  jamais      : {rank[None]}")
print(f"\n  avec 3 tentatives -> {sum(rank[k] for k in (1,2,3))}/{TRIALS}")
print(f"  avec 5 tentatives -> {sum(rank[k] for k in (1,2,3,4,5))}/{TRIALS}")
