"""Archive of every fix attempt - kept, rejected or never produced.

Two lessons point here. The first Fermat-formalisation run "quickly lost track
of the project's state" until a shared structure held it (Anthropic, 2026);
and here, on 2026-10-17, the patch files of a live take were overwritten by the
next run (``out/fixes/`` is shared), so its held-out check had to be rebuilt
from the diffs in its HTML. The offline predictor experiment (2026-10-09)
found too little data to learn from for the same reason.

Layout, under the run's ``out_dir``::

    attempts/
      index.jsonl                         one line per attempt, append-only
      <test slug>/<run id>-<n>/
        attempt.json                      verdict, category, model settings, events
        failure.txt                       the error and traceback the model saw
        diff.patch                        the patch, when there was one
        pytest.log                        the verification re-run, when there was one

Nothing is overwritten: a second run adds a directory. Rejections and missing
patches are kept on purpose - they are what a later attempt must not repeat,
and the data the experiments lacked. ``NGE_ARCHIVE_ATTEMPTS=0`` turns it off.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional

ROOT = "attempts"

# the obstacle, named - what a self-repair turn would be told about
CATEGORIES = ("fixed", "regression", "target_still_failing", "output_cut", "no_output",
              "blocked", "context_invented", "truncated", "unparsed", "empty",
              "model_unavailable", "error", "no_patch")


def enabled() -> bool:
    return os.environ.get("NGE_ARCHIVE_ATTEMPTS", "1").strip() not in ("0", "false", "no", "off")


def slug(test: str) -> str:
    """A directory name for a test id: readable, filesystem-safe, short."""
    s = re.sub(r"[^A-Za-z0-9._-]+", "__", test.replace("::", "--")).strip("_")
    return s[-120:]


def category(row: dict, test_events: Iterable[dict]) -> str:
    """Why the attempt ended where it did, from the fix row and its events."""
    kinds = [e.get("kind") for e in test_events]
    if row.get("verified"):
        return "fixed"
    if not row.get("patch"):
        for kind, cat in (("patch_truncated", "truncated"), ("patch_unparsed", "unparsed"),
                          ("model_unavailable", "model_unavailable"),
                          ("patch_error", "error"), ("patch_empty", "empty")):
            if kind in kinds:
                return cat
        return "no_patch"
    if "fix_context_invented" in kinds:
        return "context_invented"
    if row.get("regressions"):
        return "regression"
    why = row.get("reason") or ""
    if "cut at the sandbox size limit" in why:
        return "output_cut"
    if "no output" in why:
        return "no_output"
    if "blocked" in why or "jail" in why:
        return "blocked"
    return "target_still_failing"


def _verdict(row: dict, cat: str) -> str:
    if cat == "fixed":
        return "verified"
    if not row.get("patch"):
        return "no_patch"
    if cat == "context_invented":
        return "refused_before_vm"
    return "rejected"


def archive(out_dir, run_id: str, rows: List[dict], failures: List[dict],
            events: List[dict], meta: Dict[str, dict], run: Dict[str, object]) -> Optional[dict]:
    """Write one directory per attempt and append the index. Returns a summary
    (relative paths only - the event log ends up in reports)."""
    if not enabled() or not rows:
        return None
    root = Path(out_dir) / ROOT
    root.mkdir(parents=True, exist_ok=True)
    by_test = {f.get("test"): f for f in failures}
    counts: Dict[str, int] = {}
    with (root / "index.jsonl").open("a", encoding="utf-8") as index:
        for row in rows:
            test = row["test"]
            tev = [e for e in events if e.get("test") == test]
            cat = category(row, tev)
            d = root / slug(test)
            d.mkdir(parents=True, exist_ok=True)
            n = len([p for p in d.iterdir() if p.name.startswith(f"{run_id}-")]) + 1
            here = d / f"{run_id}-{n}"
            here.mkdir()
            f = by_test.get(test) or {}
            (here / "failure.txt").write_text(
                f"test: {test}\nerror: {f.get('error', '')}\n\n{f.get('context') or ''}",
                encoding="utf-8")
            if row.get("patch"):
                (here / "diff.patch").write_text(row["patch"], encoding="utf-8")
            if row.get("stdout") or row.get("stderr") or row.get("exit_code") is not None:
                (here / "pytest.log").write_text(
                    f"# exit code: {row.get('exit_code')}\n# --- stdout ---\n"
                    f"{row.get('stdout') or ''}\n# --- stderr ---\n{row.get('stderr') or ''}",
                    encoding="utf-8")
            rec = {
                "test": test, "run": run_id, "n": n,
                "verdict": _verdict(row, cat), "category": cat,
                "reason": row.get("reason", ""),
                "regressions": list(row.get("regressions") or []),
                "node": row.get("node"),
                "exit_code": row.get("exit_code"),
                "patch_chars": len(row.get("patch") or ""),
                **{k: v for k, v in (meta.get(test) or {}).items()},
                **run,
                "events": [e.get("kind") for e in tev],
                "dir": here.relative_to(root).as_posix(),
            }
            (here / "attempt.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
            index.write(json.dumps(rec) + "\n")
            counts[cat] = counts.get(cat, 0) + 1
    return {"dir": ROOT, "attempts": len(rows), "categories": counts}


def load(out_dir) -> List[dict]:
    """Every archived attempt under ``out_dir``, oldest first."""
    p = Path(out_dir) / ROOT / "index.jsonl"
    if not p.is_file():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
