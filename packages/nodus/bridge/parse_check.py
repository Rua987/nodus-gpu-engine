#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Oracle de parse pour le pont A→B.

Importe le VRAI `_parse_text_tool_calls` du harnais — ne jamais réimplémenter.

Usage:
    python bridge/parse_check.py                  # run vecteurs + exit 0/1
    python bridge/parse_check.py --check-file x.txt
    python bridge/parse_check.py --score-exact gold.json pred.txt

Contrats (HANDOFF_A2B_BRIDGE.md) :
  - Grammaire = JSON {"tool_call": {"name", "arguments"}}
  - Exact match = parse OK + name exact + args required exacts (JSON normalisé)
  - Voie de secours arguments-string → {"command": ...} = ÉCHEC exact (dégradé)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Optional

_BRIDGE = Path(__file__).resolve().parent
_HARNESS = _BRIDGE.parent
if str(_HARNESS) not in sys.path:
    sys.path.insert(0, str(_HARNESS))

from nodus_agent import _parse_text_tool_calls  # noqa: E402

SCHEMAS_PATH = _BRIDGE / "tool_schemas.json"
PROMPT_PATH = _BRIDGE / "mini_prompt.txt"
VECTORS_PATH = _BRIDGE / "parse_vectors.json"
VERSION_PATH = _BRIDGE / "VERSION.json"


def load_schemas() -> dict[str, dict]:
    raw = json.loads(SCHEMAS_PATH.read_text(encoding="utf-8"))
    return {e["name"]: e for e in raw}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _normalize_args(args: Any) -> dict:
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return {"__degraded_command__": args}
    if not isinstance(args, dict):
        return {"__invalid__": repr(args)}
    return {k: args[k] for k in sorted(args.keys())}


def raw_arguments_is_strict_object(text: str) -> bool:
    """True si le JSON brut a arguments/parameters comme objet (pas string → fallback command)."""
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start < 0 or end <= start:
            return False
        data = json.loads(text[start:end])
        if not isinstance(data, dict):
            return False
        tc = data.get("tool_call") if "tool_call" in data else data
        if not isinstance(tc, dict):
            return False
        args = tc.get("arguments", tc.get("parameters"))
        if isinstance(args, dict):
            return True
        if isinstance(args, str):
            try:
                return isinstance(json.loads(args), dict)
            except json.JSONDecodeError:
                return False  # déclenche le fallback {"command": ...} → dégradé
        return False
    except (json.JSONDecodeError, TypeError):
        return False


def classify(text: str) -> dict:
    """
    Classe une sortie modèle.

    label:
      - valid           : parse OK + arguments objet strict
      - degraded        : parse OK via fallback command / args string non-JSON
      - invalid         : parse échoue ou name manquant
    """
    parsed = _parse_text_tool_calls(text)
    if not parsed:
        return {"label": "invalid", "parsed": None, "name": None, "arguments": None, "strict": False}
    fn = parsed[0]["function"]
    name = fn.get("name")
    args_raw = fn.get("arguments")
    try:
        args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
    except json.JSONDecodeError:
        args = {"__raw__": args_raw}
    strict = raw_arguments_is_strict_object(text)
    if not strict:
        return {
            "label": "degraded",
            "parsed": parsed,
            "name": name,
            "arguments": args,
            "strict": False,
        }
    return {
        "label": "valid",
        "parsed": parsed,
        "name": name,
        "arguments": args if isinstance(args, dict) else {},
        "strict": True,
    }


def score_exact(pred_text: str, gold_name: str, gold_args: dict, schemas: Optional[dict] = None) -> dict:
    """
    Exact tool-call pour le seuil 90%.

    Échec si : invalid, degraded (fallback command), mauvais name, args required mismatch.
    """
    schemas = schemas or load_schemas()
    c = classify(pred_text)
    if c["label"] != "valid":
        return {
            "exact": False,
            "reason": c["label"],
            "pred_name": c.get("name"),
            "pred_args": c.get("arguments"),
        }
    if c["name"] != gold_name:
        return {
            "exact": False,
            "reason": "wrong_name",
            "pred_name": c["name"],
            "pred_args": c["arguments"],
        }
    schema = schemas.get(gold_name)
    if not schema:
        return {"exact": False, "reason": "unknown_tool", "pred_name": c["name"], "pred_args": c["arguments"]}
    required = list((schema.get("parameters") or {}).get("required") or [])
    pred_args = c["arguments"] or {}
    gold_n = _normalize_args(gold_args)
    pred_n = _normalize_args(pred_args)
    for key in required:
        if key not in pred_n:
            return {
                "exact": False,
                "reason": f"missing_required:{key}",
                "pred_name": c["name"],
                "pred_args": pred_args,
            }
        if pred_n.get(key) != gold_n.get(key):
            return {
                "exact": False,
                "reason": f"arg_mismatch:{key}",
                "pred_name": c["name"],
                "pred_args": pred_args,
            }
    return {
        "exact": True,
        "reason": "ok",
        "pred_name": c["name"],
        "pred_args": pred_args,
    }


def run_vectors() -> int:
    vectors = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
    schemas = load_schemas()
    failed = 0
    for i, v in enumerate(vectors):
        text = v["text"]
        expect_label = v["expect_label"]
        c = classify(text)
        ok_label = c["label"] == expect_label
        exact_ok = True
        if "gold_name" in v:
            sc = score_exact(text, v["gold_name"], v.get("gold_args") or {}, schemas)
            exact_ok = sc["exact"] == v.get("expect_exact", False)
            if not exact_ok:
                print(f"FAIL[{i}] {v['id']}: exact got={sc} expect_exact={v.get('expect_exact')}")
                failed += 1
                continue
        if not ok_label:
            print(f"FAIL[{i}] {v['id']}: label got={c['label']} expect={expect_label}")
            failed += 1
            continue
        print(f"OK[{i}] {v['id']}: {c['label']}")
    print(f"\n{len(vectors) - failed}/{len(vectors)} vectors OK")
    return 0 if failed == 0 else 1


def write_version() -> dict:
    meta = {
        "bridge_version": "1.0.0",
        "grammar": "json_tool_call_text_tools",
        "parser": "nodus_agent._parse_text_tool_calls",
        "exact_policy": "parse_ok+strict_object_args+name+required_args; degraded_command_fallback=FAIL",
        "files": {
            "tool_schemas.json": sha256_file(SCHEMAS_PATH),
            "mini_prompt.txt": sha256_file(PROMPT_PATH),
            "parse_vectors.json": sha256_file(VECTORS_PATH),
            "parse_check.py": sha256_file(Path(__file__)),
        },
        "tool_count": len(load_schemas()),
        "mini_prompt_note": "placeholder {TASK}; measure tokens with tiktoken cl100k; budget <=150 without task",
    }
    VERSION_PATH.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def main() -> int:
    ap = argparse.ArgumentParser(description="Bridge parse oracle (real harness parser)")
    ap.add_argument("--check-file", type=Path, help="Classify one prediction file")
    ap.add_argument("--score-exact", nargs=2, metavar=("GOLD_JSON", "PRED_TXT"),
                    help="gold={name,arguments} file + pred text file")
    ap.add_argument("--write-version", action="store_true", help="Refresh VERSION.json hashes")
    ap.add_argument("--vectors", action="store_true", default=False, help="Run labeled vectors")
    args = ap.parse_args()

    if args.write_version:
        meta = write_version()
        print(json.dumps(meta, indent=2))
        return 0

    if args.check_file:
        text = args.check_file.read_text(encoding="utf-8")
        print(json.dumps(classify(text), indent=2, default=str))
        return 0

    if args.score_exact:
        gold = json.loads(Path(args.score_exact[0]).read_text(encoding="utf-8"))
        pred = Path(args.score_exact[1]).read_text(encoding="utf-8")
        print(json.dumps(
            score_exact(pred, gold["name"], gold.get("arguments") or {}),
            indent=2, default=str,
        ))
        return 0

    # default: vectors
    return run_vectors()


if __name__ == "__main__":
    raise SystemExit(main())
