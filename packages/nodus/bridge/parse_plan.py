#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Oracle de parse pour le pont PLAN (NODUS planificateur).

Contrat : NODUS recoit `plan_prompt.txt` (placeholder {TASK}) et repond avec
UNIQUEMENT un JSON array de noms d'outils, ex. ["glob","read_file"].
Le harnais remplit les arguments de chaque etape lui-meme (NODUS ne fournit
PAS les args — capacite copie exacte mesuree insuffisante, cf. CYCLES_HISTORY
toolcalls v1..v4, plafond 11/120).

Ce fichier est le parseur de REFERENCE : le harnais doit l'importer (ou
reproduire strictement `parse_plan`), pas le reimplementer a sa facon.

Labels :
  - valid    : JSON array propre, tous les noms connus
  - degraded : array casse mais noms recuperables par regex (utilisable avec
               prudence ; compte FAIL pour la metrique exact)
  - invalid  : rien d'exploitable

Usage:
    python bridge/parse_plan.py                      # vecteurs + exit 0/1
    python bridge/parse_plan.py --check-file x.txt
    python bridge/parse_plan.py --score gold.json pred.txt
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

_BRIDGE = Path(__file__).resolve().parent

PROMPT_PATH = _BRIDGE / "plan_prompt.txt"
VECTORS_PATH = _BRIDGE / "plan_vectors.json"
VERSION_PATH = _BRIDGE / "PLAN_VERSION.json"

TOOLS = ("bash", "read_file", "write_file", "edit_file", "glob", "grep",
         "web_fetch", "brave_search")
_NAME_RE = re.compile(r"\b(" + "|".join(TOOLS) + r")\b")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def parse_plan(text: str) -> dict:
    """
    Retourne {"label": valid|degraded|invalid, "names": [...] | None}.

    Identique au parseur du probe train (probe_plan_multistep.py) — c'est la
    definition qui a produit les chiffres de PLAN_VERSION.json.
    """
    if not text or not text.strip():
        return {"label": "invalid", "names": None}
    t = text.strip()
    start, end = t.find("["), t.rfind("]") + 1
    if start >= 0 and end > start:
        try:
            data = json.loads(t[start:end])
            if isinstance(data, list):
                names = [x.strip() for x in data if isinstance(x, str) and x.strip()]
                if names and all(n in TOOLS for n in names):
                    return {"label": "valid", "names": names}
                if names:
                    return {"label": "degraded", "names": names}
        except (json.JSONDecodeError, TypeError):
            pass
    found = _NAME_RE.findall(t)
    if found:
        return {"label": "degraded", "names": found}
    return {"label": "invalid", "names": None}


def score_plan(pred_text: str, gold_names: list[str]) -> dict:
    """
    Metrique du pont plan.

    exact_plan  : label valid ET suite == gold (l'ordre compte)
    prefix1     : premier outil correct (toleree degraded) — utile au harnais
                  pour decider s'il fait confiance a la 1re etape seulement
    """
    p = parse_plan(pred_text)
    names = p["names"]
    return {
        "exact_plan": p["label"] == "valid" and names == list(gold_names),
        "prefix1": bool(names) and names[0] == gold_names[0],
        "set_ok": bool(names) and set(names) == set(gold_names),
        "label": p["label"],
        "pred_names": names,
    }


def run_vectors() -> int:
    vectors = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
    failed = 0
    for i, v in enumerate(vectors):
        p = parse_plan(v["text"])
        ok = p["label"] == v["expect_label"]
        if ok and "gold" in v:
            sc = score_plan(v["text"], v["gold"])
            ok = sc["exact_plan"] == v.get("expect_exact", False)
        if not ok:
            print(f"FAIL[{i}] {v['id']}: got={p} expect_label={v['expect_label']} "
                  f"expect_exact={v.get('expect_exact')}")
            failed += 1
        else:
            print(f"OK[{i}] {v['id']}: {p['label']}")
    print(f"\n{len(vectors) - failed}/{len(vectors)} vectors OK")
    return 0 if failed == 0 else 1


def write_version() -> dict:
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        prompt_tokens = len(enc.encode(
            PROMPT_PATH.read_text(encoding="utf-8").replace("{TASK}", "")))
    except Exception:
        prompt_tokens = None
    meta = {
        "plan_bridge_version": "1.1.0",
        "grammar": "json_array_of_tool_names",
        "parser": "bridge.parse_plan.parse_plan",
        "exact_policy": "label=valid AND names==gold (ordre compte); degraded=FAIL",
        "checkpoint": "checkpoints/checkpoint_sft_plan_v5.pt",
        "checkpoint_source": "sft_plan_v5 (v2b->v5, corpus plan_v5 20k hard 0.60, ciblage des 12 echecs v4 dont brave->web_fetch)",
        "measured": {
            "holdout": "D:\\datasets\\plan\\plan_v3_holdout_fresh.json (n=120, inedit, jamais vu par aucun corpus)",
            "exact_plan_brut": "119/120 (99%)",
            "exact_plan_avec_garde_fous": "119/120 (99%)",
            "residus": "f04 'Shell out to dotnet format.' (gold bash, pred edit_file)",
            "regressions_garde_fous": "0",
            "holdout_v2_sature": "100/100 (0 regression apres rejeu)",
            "probe": "probe_plan_multistep_plan_v3fresh_v5.json (train repo)",
            "note": "v5 > v2b sur taches inedites (v2b+GF 109/120 91%) ; le holdout v2 contamine donnait une fausse egalite. Repromu 2026-08-15 apres preuve fresh.",
        },
        "harness_contract": {
            "args": "REMPLIS PAR LE HARNAIS — NODUS ne fournit que les noms",
            "confiance": "plan = suggestion a verifier etape par etape, pas un ordre",
            "fallback": "si label!=valid ou plan absurde -> harnais planifie seul",
        },
        "files": {
            "plan_prompt.txt": sha256_file(PROMPT_PATH),
            "plan_vectors.json": sha256_file(VECTORS_PATH),
            "parse_plan.py": sha256_file(Path(__file__)),
        },
        "tool_count": len(TOOLS),
        "plan_prompt_tokens_cl100k_sans_task": prompt_tokens,
    }
    VERSION_PATH.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
    return meta


def main() -> int:
    ap = argparse.ArgumentParser(description="Plan bridge parse oracle")
    ap.add_argument("--check-file", type=Path)
    ap.add_argument("--score", nargs=2, metavar=("GOLD_JSON", "PRED_TXT"))
    ap.add_argument("--write-version", action="store_true")
    args = ap.parse_args()

    if args.write_version:
        print(json.dumps(write_version(), indent=2, ensure_ascii=False))
        return 0
    if args.check_file:
        print(json.dumps(parse_plan(args.check_file.read_text(encoding="utf-8")),
                         indent=2))
        return 0
    if args.score:
        gold = json.loads(Path(args.score[0]).read_text(encoding="utf-8"))
        pred = Path(args.score[1]).read_text(encoding="utf-8")
        print(json.dumps(score_plan(pred, gold["names"]), indent=2))
        return 0
    return run_vectors()


if __name__ == "__main__":
    raise SystemExit(main())
