# -*- coding: utf-8 -*-
"""P0 phase 0a — taxonomie plan : V (vocab) vs P (mauvais plan) vs OK.

Méthode et table de décision : ``docs/MEASURE_BEFORE_LEVER.md``.
Phase 0a : compare un plan or (humain) au planneur, sans sandbox ni Nemotron.

    python -m bench.failure_taxonomy              # heuristique seule (rapide)
    python -m bench.failure_taxonomy --model      # + 324M si checkpoint + torch
    python -m bench.failure_taxonomy --csv out/taxonomy_p0.csv

Décision (parmi les cas hors-OK) :
  V dominant  -> élargir les 8 (train cher)
  P dominant  -> meilleur corpus / checkpoint, pas +outils
  peu de ratés -> ne pas ouvrir de chantier plan
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from nge import config as _cfg
from nge import planner as _planner

# (id, task, gold_plan | None, vocab_gap | None)
# gold_plan = noms parmi les 8. vocab_gap = outil hors vocab (étiquette V).
CASES = [
    # --- coding classique (8 suffisent) ---
    ("find_read",
     "Find the config file and read it",
     ["glob", "read_file"], None),
    ("grep_edit",
     "Search for TODO in the repo then fix the first one",
     ["grep", "read_file", "edit_file"], None),
    ("pytest_fix",
     "Run pytest and patch the failing test",
     ["bash", "read_file", "edit_file"], None),
    ("write_report",
     "Write a short summary report of the triage",
     ["write_file"], None),
    ("fetch_docs",
     "Fetch https://example.com/api docs and save notes",
     ["web_fetch", "write_file"], None),
    ("web_then_code",
     "Brave-search how requests timeouts work then edit client.py",
     ["brave_search", "read_file", "edit_file"], None),
    ("read_edit_port",
     "Read server.py then change the port to 8080",
     ["read_file", "edit_file"], None),
    ("list_then_open",
     "List python files under src/ then open the main one",
     ["glob", "read_file"], None),
    ("bash_only",
     "Run the unit tests with pytest -q",
     ["bash"], None),
    ("inspect_fail",
     "Inspect the failing traceback and update the assertion",
     ["read_file", "edit_file"], None),
    # --- FR (heuristique anglaise souvent faible) ---
    ("fr_lis_edite",
     "lis config.yaml puis change le timeout",
     ["read_file", "edit_file"], None),
    ("fr_trouve_lit",
     "trouve le fichier settings et lis-le",
     ["glob", "read_file"], None),
    ("fr_cherche_todo",
     "cherche FIXME dans le code puis corrige",
     ["grep", "read_file", "edit_file"], None),
    ("fr_lance_tests",
     "lance la suite de tests",
     ["bash"], None),
    ("fr_resume",
     "ecris un rapport de triage dans out/report.md",
     ["write_file"], None),
    # --- formulations piégeuses mais dans les 8 ---
    ("telegraphic",
     "config. conf read. fix port.",
     ["read_file", "edit_file"], None),
    ("locate_yaml",
     "which file is the docker compose? open it",
     ["glob", "read_file"], None),
    ("download_schema",
     "download the openapi json from that url and store it",
     ["web_fetch", "write_file"], None),
    # --- V : besoin hors des 8 (humain) ---
    ("v_gcs",
     "Upload the gallery mp4 to the GCS bucket for the demo",
     None, "gcs_upload"),
    ("v_gpu_alloc",
     "Provision three H100 nodes and pin the shard to node 0",
     None, "gpu_provision"),
    ("v_browser",
     "Open the local dashboard and click the Run button",
     None, "browser"),
    ("v_email",
     "Email the triage report to the on-call alias",
     None, "send_email"),
    ("v_mcp_custom",
     "Call the internal MCP tool fleet.migrate_shard with shard-2",
     None, "mcp_tool"),
    ("v_screenshot",
     "Take a screenshot of the watch UI and attach it to the PR",
     None, "screenshot"),
]


def _label(gold, vocab_gap, names) -> str:
    if vocab_gap:
        return "V"
    if names == gold:
        return "OK"
    if gold is not None and set(names) == set(gold):
        return "P_order"  # mêmes outils, mauvais ordre → compte comme P
    return "P"


def _run_one(task: str, use_model: bool, cfg) -> tuple[list, str]:
    if use_model:
        pr = _planner.plan(task, allow_nemotron=False, config=cfg)
        return list(pr.names), pr.source
    return _planner._heuristic(task), "heuristic"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", action="store_true",
                    help="use planner.plan (324M if ckpt+torch, else heuristic)")
    ap.add_argument("--csv", type=Path, default=None,
                    help="write per-case rows to this CSV")
    args = ap.parse_args()

    cfg = _cfg.load()
    ckpt, exists, note = _planner.ckpt_status(cfg)
    print(f"[planner] {note}")
    print(f"[planner] torch={_planner.have_torch()}  mode="
          f"{'plan()' if args.model else 'heuristic-only'}")
    print()

    rows = []
    counts = Counter()
    for cid, task, gold, gap in CASES:
        names, source = _run_one(task, args.model, cfg)
        lab = _label(gold, gap, names)
        # P_order rolls into P for the decision table
        bucket = "P" if lab == "P_order" else lab
        counts[bucket] += 1
        mark = {"OK": "ok  ", "V": "V   ", "P": "P   ", "P_order": "Pord"}[lab]
        gold_s = gap if gap else (gold or [])
        print(f"{mark} {cid:<16} got={names}  gold={gold_s}  src={source}")
        rows.append({
            "id": cid, "label": bucket, "detail": lab, "source": source,
            "got": " ".join(names),
            "gold": gap or " ".join(gold or []),
            "task": task,
        })

    n = len(CASES)
    print("\n=== distribution (phase 0a) ===")
    for k in ("OK", "P", "V"):
        c = counts[k]
        print(f"  {k}: {c:>3}  →  {100 * c / n:.0f}%")

    fails = counts["P"] + counts["V"]
    print(f"\n  hors-OK: {fails}/{n}")
    if fails == 0:
        decision = "Non chantier plan — corpus trop facile ou planneur parfait"
    else:
        v_share = counts["V"] / fails
        p_share = counts["P"] / fails
        print(f"  parmi hors-OK: V={100 * v_share:.0f}%  P={100 * p_share:.0f}%")
        if v_share >= 0.5:
            decision = "Go évaluer +outils (V dominant) — train cher, pas avant n plus large"
        elif p_share >= 0.5:
            decision = "Go meilleur plan sur les 8 (P dominant) — pas élargir le vocab"
        else:
            decision = "Empatté — affiner le corpus avant tout chantier"
    print(f"\nDécision: {decision}")
    print("Note: A/X/I/F hors scope 0a (besoin run exécuteur / events).")

    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"\nCSV: {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
