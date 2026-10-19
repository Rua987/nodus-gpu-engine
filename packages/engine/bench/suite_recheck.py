"""Re-run the whole visible bugbench suite on every patch a live film called
verified, after the fact, from the diffs in its HTML. No model call.

Until 2026-10-19 the live films' sandbox re-run ran no test: the import path
reached patch-ng, not pytest, so the suite died collecting (exit 2) and, with
no FAILED line, every patch that applied read as verified. The held-out check
(``bench.thinking_ab.holdout_check``) ran locally with a real pytest, so it
stands; this replays the other half the films claimed - the target passes and
nothing else breaks - on the same diffs.

    python -m bench.suite_recheck evidence/report_*.html --csv evidence/suite_recheck_20261019.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from bench.holdout_from_html import diffs_from_html, verified_tests

_REPO = Path(__file__).resolve().parents[3]
_REL = Path("packages/engine/bench/bugbench")
_FAILED = re.compile(r"^(?:FAILED|ERROR)\s+(\S+::\S+)", re.M)
_COUNT = re.compile(r"\b\d+ (?:passed|failed)\b")


def run_suite(patch: str = "") -> dict:
    """Copy bugbench, apply ``patch`` (if any), run its visible tests."""
    import patch_ng
    with tempfile.TemporaryDirectory(prefix="nge_recheck_") as td:
        root = Path(td)
        shutil.copytree(_REPO / _REL, root / _REL, ignore=shutil.ignore_patterns("__pycache__"))
        if patch:
            ps = patch_ng.fromstring(patch.encode("utf-8"))
            if not ps or not ps.apply(strip=1, root=str(root)):
                return {"applied": False, "ran": False, "failed": set()}
        env = {**os.environ, "PYTHONPATH": str(root / _REL)}
        r = subprocess.run([sys.executable, "-m", "pytest", str(_REL / "tests"), "-q",
                            "-p", "no:cacheprovider"],
                           cwd=td, env=env, capture_output=True, text=True, timeout=120)
        ran = r.returncode in (0, 1) and _COUNT.search(r.stdout) is not None
        return {"applied": True, "ran": ran, "failed": set(_FAILED.findall(r.stdout))}


def recheck(pages) -> list:
    base = run_suite()
    assert base["ran"], "the unpatched suite must run"
    rows = []
    for page in pages:
        page = Path(page)
        patches = diffs_from_html(page.read_text(encoding="utf-8"))
        for test in verified_tests(page.with_suffix(".md").read_text(encoding="utf-8")):
            res = run_suite(patches.get(test, ""))
            fixed = res["ran"] and test not in res["failed"]
            broke = sorted(res["failed"] - base["failed"])
            rows.append({"run": page.stem.replace("report_", ""), "test": test.split("::")[-1],
                         "applied": res["applied"], "tests_ran": res["ran"],
                         "target_fixed": fixed, "regressions": " ".join(broke),
                         "verified": fixed and res["ran"] and not broke})
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pages", nargs="+", help="live-film report HTML files")
    ap.add_argument("--csv", default="")
    a = ap.parse_args(argv)
    rows = recheck(a.pages)
    for r in rows:
        print(f"{r['run']}  {'OK ' if r['verified'] else 'KO '} {r['test']}"
              + (f"  broke: {r['regressions']}" if r["regressions"] else ""))
    ok = sum(r["verified"] for r in rows)
    print(f"suite re-check: {ok}/{len(rows)} patches fix their test and break nothing")
    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
