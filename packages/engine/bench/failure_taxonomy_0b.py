# -*- coding: utf-8 -*-
"""P0 phase 0b — taxonomie exécuteur via events (A / X / I / F / Q).

Méthode et table de décision : ``docs/MEASURE_BEFORE_LEVER.md``.
Phase 0a classait le *plan* (V/P). Ici on classifie ce que l'orchestrateur
émet déjà, avec des sondes déterministes (chat_fn scripté) + un run mock
baseline. Pas de Nemotron sauf ``--live``.

    python -m bench.failure_taxonomy_0b
    python -m bench.failure_taxonomy_0b --csv out/taxonomy_p0b.csv
    python -m bench.failure_taxonomy_0b --live --i-know-cost

Décision : parmi A/X/I/F, quel bucket domine → levier harnais / parse / infra / retry.
Q (fix_rejected) oriente vers la boucle de vérif, pas vers +outils.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from nge import config as _cfg
from nge.orchestrator import NgeOrchestrator
from nge.tools import handlers

# Pas d'attente retry pendant les sondes (conftest fait pareil).
NgeOrchestrator.RETRY_DELAY_S = 0.0

SCENARIO = {
    "task": "Run the failing pytest suite across the GPU fleet, triage, fix, report.",
    "shards": 3,
    "gpu_type": "H100",
    "target": "packages/nodus/tests",
    "collect": [],
}

# kind d'event → bucket 0b (Q = qualité patch vérifiée, hors grille stricte)
KIND_BUCKET = {
    # A — bon plan possible, mauvais args / slot-fill
    "slotfill_empty": "A",
    "slotfill_error": "A",
    "slotfill_off_target": "A",
    "slotfill_bad_flags": "A",
    "slotfill_rejected": "A",
    "slotfill_narrowed": "A",
    # X — parse / format de réponse
    "patch_unparsed": "X",
    # I — infra / fleet / sandbox / env
    "gpu_pressure": "I",
    "gpu_remediation": "I",
    "gpu_provision_replacement": "I",
    "replacement_node_pressure_warning": "I",
    "fix_unjudged": "I",
    "payload_truncated": "I",
    "under_test_error": "I",
    "sandbox_env": "I",  # informatif ; compté une fois par run
    # F — flake modèle (vide / récupéré au retry)
    "patch_empty": "F",
    "patch_retry_succeeded": "F",
    # Q — patch produit mais rejeté à la vérif (signal utile, hors A/X/I/F)
    "fix_rejected": "Q",
    "fix_regression": "Q",
    # T — réponse coupée par max_tokens (raisonnement compris). Absent avant
    # 2026-10-01 : un patch_truncated n'était compté nulle part, donc un run
    # live où tout était tronqué ressortait « A=0 X=0 F=0 ».
    "slotfill_truncated": "T",
    "patch_truncated": "T",
}

BUCKETS = ("A", "X", "I", "F", "T", "Q")


def _orch(out: Path, chat_fn=None) -> NgeOrchestrator:
    cfg = _cfg.load(fleet_mode="mock", sandbox_mode="mock", out_dir=out)
    return NgeOrchestrator(config=cfg, chat_fn=chat_fn)


def _classify(events) -> Counter:
    c = Counter()
    for e in events:
        b = KIND_BUCKET.get(e.get("kind"))
        if b:
            c[b] += 1
    return c


def _own_files(prompt: str) -> list[str]:
    return re.findall(r"packages/nodus/tests/[\w./-]+\.py", prompt)


def _is_patch_prompt(prompt: str) -> bool:
    return "unified diff" in prompt.lower() or "Reply with ONLY a unified diff" in prompt


# ── sondes ───────────────────────────────────────────────────────────────

def probe_baseline(out: Path):
    """Run mock sans chat_fn — throttle / remediation = I naturel."""
    o = _orch(out)
    handlers.reset_state(o.config)
    o.run(SCENARIO)
    return o.events, "I"


def probe_slotfill_off_target(out: Path):
    def chat_fn(messages, model=None, tools=None):
        return {"content": "python -m pytest packages/nodus/tests -v --gpu"}
    o = _orch(out, chat_fn=chat_fn)
    handlers.reset_state(o.config)
    o.run(SCENARIO)
    return o.events, "A"


def probe_slotfill_bad_flags(out: Path):
    def chat_fn(messages, model=None, tools=None):
        p = messages[-1]["content"]
        if _is_patch_prompt(p):
            return {"content": ""}  # ignore patch path for this probe
        own = _own_files(p)
        return {"content": f"pytest {' '.join(own)} -v --html=r.html"}
    o = _orch(out, chat_fn=chat_fn)
    handlers.reset_state(o.config)
    o.run({**SCENARIO, "shards": 2, "auto_fix": False})
    return o.events, "A"


def probe_slotfill_rejected(out: Path):
    def chat_fn(messages, model=None, tools=None):
        p = messages[-1]["content"]
        if _is_patch_prompt(p):
            return {"content": ""}
        own = _own_files(p)
        return {"content": f"pytest {' '.join(own)} -q && echo $(whoami)"}
    o = _orch(out, chat_fn=chat_fn)
    handlers.reset_state(o.config)
    o.run({**SCENARIO, "shards": 2, "auto_fix": False})
    return o.events, "A"


def probe_slotfill_empty(out: Path):
    def chat_fn(messages, model=None, tools=None):
        if _is_patch_prompt(messages[-1]["content"]):
            return {"content": "```diff\n--- a/x.py\n+++ b/x.py\n@@\n-a\n+b\n```"}
        return {"content": ""}
    o = _orch(out, chat_fn=chat_fn)
    handlers.reset_state(o.config)
    o.run({**SCENARIO, "shards": 2, "auto_fix": False})
    return o.events, "A"


def probe_patch_empty(out: Path):
    o = _orch(out, chat_fn=lambda m, mo=None, t=None: {"content": ""})
    o._propose_patch({"test": "t.py::test_a", "error": "e"}, "m")
    return o.events, "F"


def probe_patch_retry(out: Path):
    calls = {"n": 0}
    diff = "--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,1 @@\n-a\n+b\n"

    def chat_fn(messages, model=None, tools=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"content": ""}
        return {"content": f"```diff\n{diff}```"}

    o = _orch(out, chat_fn=chat_fn)
    o._propose_patch({"test": "t.py::test_a", "error": "e"}, "m")
    return o.events, "F"


def probe_patch_prose(out: Path):
    prose = "I cannot fix this without seeing the caller. " * 4
    o = _orch(out, chat_fn=lambda m, mo=None, t=None: {"content": prose})
    o._propose_patch({"test": "t.py::test_a", "error": "e"}, "m")
    return o.events, "X"


def probe_patch_headerless(out: Path):
    headerless = "```diff\n@@ -1,2 +1,2 @@\n keep\n-old\n+new\n```"
    o = _orch(out, chat_fn=lambda m, mo=None, t=None: {"content": headerless})
    o._propose_patch({"test": "t.py::test_a", "error": "e"}, "m")
    return o.events, "X"


def _budget_spent(m, mo=None, t=None):
    # the live shape: every token went to reasoning, nothing reached content
    return {"content": "", "finish_reason": "length", "reasoning_tokens": 256}


def probe_slotfill_truncated(out: Path):
    o = _orch(out, chat_fn=_budget_spent)
    handlers.reset_state(o.config)
    o.run({**SCENARIO, "shards": 2, "auto_fix": False})
    return o.events, "T"


def probe_patch_truncated(out: Path):
    o = _orch(out, chat_fn=_budget_spent)
    o._propose_patch({"test": "t.py::test_a", "error": "e"}, "m")
    return o.events, "T"


PROBES = [
    ("baseline_mock", probe_baseline),
    ("slotfill_off_target", probe_slotfill_off_target),
    ("slotfill_bad_flags", probe_slotfill_bad_flags),
    ("slotfill_rejected", probe_slotfill_rejected),
    ("slotfill_empty", probe_slotfill_empty),
    ("patch_empty", probe_patch_empty),
    ("patch_retry", probe_patch_retry),
    ("patch_prose", probe_patch_prose),
    ("patch_headerless", probe_patch_headerless),
    ("slotfill_truncated", probe_slotfill_truncated),
    ("patch_truncated", probe_patch_truncated),
]


def _run_live(out: Path):
    """Un run réel : Nemotron + fleet mock (pas d'alloc GPU)."""
    os.environ.setdefault("NGE_FLEET_MODE", "mock")
    os.environ.setdefault("NGE_SANDBOX", "mock")
    from nge.backends import register
    from nge.backends import usage as _usage
    from nge.backends.nebius import chat_nebius
    register.apply()
    cfg = _cfg.load(fleet_mode="mock", sandbox_mode="mock", out_dir=out)
    _usage.reset_usage()
    _usage.set_jsonl_path(cfg.out_dir / "nemotron_usage.jsonl")

    def chat_fn(messages, mdl=None, tools=None, max_tokens=None, thinking=None):
        return chat_nebius(messages, mdl or cfg.nemotron_model, tools,
                           max_tokens=max_tokens, thinking=thinking)

    o = NgeOrchestrator(config=cfg, chat_fn=chat_fn)
    handlers.reset_state(o.config)
    o.run({**SCENARIO, "shards": 2})
    print(_usage.format_summary())
    return o.events


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", type=Path, default=None)
    ap.add_argument("--live", action="store_true",
                    help="1 run Nemotron (fleet+sandbox mock) — coûte des appels")
    ap.add_argument("--i-know-cost", action="store_true",
                    help="required with --live")
    args = ap.parse_args()
    if args.live and not args.i_know_cost:
        print("refusing: --live spends Token Factory credits. "
              "Re-run with --i-know-cost.", file=sys.stderr)
        return 2

    rows = []
    live = None
    hits = 0

    print("=== sondes déterministes (0b) ===\n")
    with tempfile.TemporaryDirectory(prefix="nge_p0b_") as td:
        base = Path(td)
        for name, fn in PROBES:
            out = base / name
            out.mkdir()
            events, expect = fn(out)
            dist = _classify(events)
            # la sonde « réussit » si le bucket attendu apparaît
            ok = dist[expect] > 0
            hits += ok
            mark = "ok  " if ok else "MISS"
            kinds = [e["kind"] for e in events if e.get("kind") in KIND_BUCKET]
            print(f"{mark} {name:<22} expect={expect}  "
                  f"buckets={dict(dist)}  kinds={kinds[:8]}")
            rows.append({
                "probe": name, "expect": expect, "hit": ok,
                **{b: dist[b] for b in BUCKETS},
                "kinds": " ".join(kinds),
            })

        if args.live:
            print("\n=== live (Nemotron, 1 run) ===\n")
            try:
                live_out = base / "live"
                live_out.mkdir()
                events = _run_live(live_out)
                dist = _classify(events)
                live = dist
                kinds = [e["kind"] for e in events if e.get("kind") in KIND_BUCKET]
                print(f"live buckets={dict(dist)}")
                print(f"live kinds={kinds}")
                rows.append({
                    "probe": "live_nemotron", "expect": "-", "hit": True,
                    **{b: dist[b] for b in BUCKETS},
                    "kinds": " ".join(kinds),
                })
            except Exception as exc:
                print(f"live FAILED: {type(exc).__name__}: {exc}")

    print(f"\n=== couverture sondes: {hits}/{len(PROBES)} ont émis le bucket attendu ===")
    print("(sondes plantées : elles prouvent le classifieur, ce ne sont pas "
          "des fréquences — docs/MEASURE_BEFORE_LEVER.md)")

    # Décider sur les sondes reviendrait à mesurer ce qu'on a planté : la
    # version précédente sommait sondes + baseline mock et concluait « I ».
    # sandbox_env est informatif (un par run), pas une panne.
    if live is None:
        decision = "pas de --live : aucun signal terrain, pas de décision de levier"
    else:
        field = {b: live[b] for b in ("A", "X", "F", "T")}
        field["I"] = max(0, live["I"] - 1)          # retire sandbox_env
        print("\n=== live seul (signal terrain, n=1 run) ===")
        for k in ("A", "X", "I", "F", "T", "Q"):
            print(f"  {k}: {field.get(k, live[k])}")
        core = sum(field.values())
        if core == 0:
            decision = ("live sans panne A/X/I/F/T"
                        + (f" ; Q={live['Q']} -> boucle de vérif" if live["Q"] else ""))
        else:
            top = max(field, key=lambda k: field[k])
            levers = {
                "A": "Go harnais / slot-fill (args), pas le 324M",
                "X": "Go parse / format de réponse (diff, mission)",
                "I": "Go engine infra (fleet, sandbox, jail)",
                "F": "Go flakiness modèle (retry déjà à 4 — mesurer avant d'augmenter)",
                "T": "Go budget de tokens (raisonnement on/off, max_tokens), pas des retries",
            }
            print(f"\n  dominant: {top} ({100 * field[top] / core:.0f}%) — n=1, "
                  f"relancer avant d'en faire une majorité stable")
            decision = levers[top]

    print(f"\nDécision: {decision}")

    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"\nCSV: {args.csv}")
    return 0 if hits == len(PROBES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
