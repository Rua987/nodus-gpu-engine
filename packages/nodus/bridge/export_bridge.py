#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regénère bridge/tool_schemas.json + VERSION.json depuis le code harnais."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_HARNESS = _HERE.parent
sys.path.insert(0, str(_HARNESS))

from nodus_tools import TOOL_SCHEMAS  # noqa: E402
from parse_check import write_version  # noqa: E402


def main() -> int:
    export = []
    for s in TOOL_SCHEMAS:
        fn = s["function"]
        export.append({
            "name": fn["name"],
            "description": fn.get("description") or "",
            "parameters": fn.get("parameters") or {},
        })
    out = _HERE / "tool_schemas.json"
    out.write_text(json.dumps(export, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(export)} tools)")
    meta = write_version()
    print(f"bridge_version={meta['bridge_version']}")
    for k, v in meta["files"].items():
        print(f"  {k}: {v[:16]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
