"""Offline experiment: can a small model predict "this patch will verify"?

Motivation (2026-10-08): a typed-decision model such as Jev suggests filtering
costly calls with a small classifier trained on logged states. Before building
anything, this asks the one question whose label is *ground truth* rather than
an opinion: from what is known about a patch before a verification sandbox is
paid for, can its outcome (verified / not) be predicted better than a trivial
rule? No network, no spend - only the runs kept in ``out/thinking_ab``.

    python -m bench.verify_predictor
    python -m bench.verify_predictor --csv evidence/verify_predictor_20261009.csv

Rows are patches that PASSED the engine's existing pre-checks (context exists):
those are the ones that would cost a verification VM. Evaluation never lets a
bug appear in both train and test (leave-one-bug-out), and always reports the
trivial baselines next to the model.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
RUNS = ENGINE / "out" / "thinking_ab"
FEATURES = ["lines_added", "lines_removed", "hunks", "files", "chars", "touches_tests",
            "tests_only", "relocated", "arm_patch_off", "arm_8k"]


def _events(md: Path) -> list:
    t = md.read_text(encoding="utf-8")
    if "```json" not in t:
        return []
    return json.loads(t[t.index("```json") + 7:t.rindex("```")])


def _features(patch: str, relocated: bool, arm: str) -> dict:
    files = re.findall(r"^\+\+\+ b/(\S+)", patch, re.M)
    is_test = [("/tests/" in f) or Path(f).name.startswith("test_") for f in files]
    body = [l for l in patch.splitlines() if l[:1] in "+-" and l[:3] not in ("+++", "---")]
    return {
        "lines_added": sum(1 for l in body if l.startswith("+")),
        "lines_removed": sum(1 for l in body if l.startswith("-")),
        "hunks": len(re.findall(r"^@@", patch, re.M)),
        "files": len(set(files)),
        "chars": len(patch),
        "touches_tests": int(any(is_test)),
        "tests_only": int(bool(files) and all(is_test)),
        "relocated": int(relocated),
        "arm_patch_off": int("patch_off" in arm),
        "arm_8k": int("8k" in arm),
    }


def load(runs: Path = RUNS) -> list:
    rows = []
    for d in sorted(p for p in runs.iterdir() if p.is_dir()):
        mds = sorted(d.glob("report_*.md"))
        patches = {p.stem: p for p in (d / "fixes").glob("*.patch")} if (d / "fixes").is_dir() else {}
        if not mds or not patches:
            continue
        ev = _events(mds[-1])
        rs = next((e for e in ev if e["kind"] == "run_start"), {})
        if rs.get("sandbox_mode") != "token_factory":     # canned patches are not model output
            continue
        arm = re.sub(r"_\d+$", "", d.name)
        verified = {e["test"].split("::")[-1] for e in ev if e["kind"] == "fix_verified"}
        rejected = {e["test"].split("::")[-1] for e in ev if e["kind"] == "fix_rejected"}
        invented = {e["test"].split("::")[-1] for e in ev if e["kind"] == "fix_context_invented"}
        relocated = bool([e for e in ev if e["kind"] == "patch_relocated"])
        target = "bugbench" if "bugbench" in mds[-1].read_text(encoding="utf-8")[:4000] else "nodus"
        for name, path in patches.items():
            if name in invented:
                outcome = "refused_before_vm"          # the existing rule already catches it
            elif name in verified:
                outcome = "verified"
            elif name in rejected:
                outcome = "rejected"
            else:
                continue
            rows.append({"run": d.name, "bug": name, "target": target, "outcome": outcome,
                         **_features(path.read_text(encoding="utf-8", errors="replace"),
                                     relocated, arm)})
    return rows


def _auc(scores, labels) -> float:
    pos = [s for s, y in zip(scores, labels) if y == 1]
    neg = [s for s, y in zip(scores, labels) if y == 0]
    if not pos or not neg:
        return float("nan")
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def leave_one_bug_out(rows: list, with_target: bool, y_override=None):
    """(AUC, accuracy, majority-accuracy, per-bug predictions) of a logistic
    regression trained without the held-out bug. ``with_target``: also give it
    which suite the bug is from - the confound this experiment is about."""
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    cols = FEATURES + (["is_bugbench"] if with_target else [])
    X = np.array([[r[c] if c != "is_bugbench" else int(r["target"] == "bugbench")
                   for c in cols] for r in rows], dtype=float)
    y = (np.array(y_override) if y_override is not None
         else np.array([int(r["outcome"] == "verified") for r in rows]))
    bugs = np.array([r["bug"] for r in rows])
    pred = np.zeros(len(rows))
    for b in sorted(set(bugs)):
        te = bugs == b
        tr = ~te
        if len(set(y[tr])) < 2:
            pred[te] = y[tr].mean()
            continue
        sc = StandardScaler().fit(X[tr])
        m = LogisticRegression(max_iter=1000, class_weight="balanced").fit(sc.transform(X[tr]), y[tr])
        pred[te] = m.predict_proba(sc.transform(X[te]))[:, 1]
    hard = (pred >= 0.5).astype(int)
    return (_auc(pred, y), float((hard == y).mean()), float(max(y.mean(), 1 - y.mean())),
            pred)


def suite_only_auc(rows: list):
    """Leave-one-bug-out AUC of a predictor that knows only which suite the bug
    is from: the share of that suite's other bugs' patches that verified."""
    ys = [int(r["outcome"] == "verified") for r in rows]
    preds = []
    for r in rows:
        peers = [int(o["outcome"] == "verified") for o in rows
                 if o["target"] == r["target"] and o["bug"] != r["bug"]]
        preds.append(sum(peers) / len(peers) if peers else 0.5)
    return _auc(preds, ys)


def chance_auc(rows: list, n: int = 200, seed: int = 0):
    """AUC this protocol gives when the labels are shuffled: (mean, 2.5%, 97.5%).
    With a handful of rejected patches, leave-one-bug-out is itself noisy - an
    AUC far from 0.5 in either direction means nothing until it is compared
    with this."""
    import random
    import numpy as np
    rng = random.Random(seed)
    y = [int(r["outcome"] == "verified") for r in rows]
    aucs = []
    for _ in range(n):
        yy = y[:]
        rng.shuffle(yy)
        a = leave_one_bug_out(rows, False, y_override=yy)[0]
        if a == a:                                    # not NaN
            aucs.append(a)
    return float(np.mean(aucs)), float(np.percentile(aucs, 2.5)), float(np.percentile(aucs, 97.5))


def report(rows: list) -> str:
    out = []
    c = Counter(r["outcome"] for r in rows)
    out.append(f"patches from real-model runs: {len(rows)} -> {dict(c)}")
    ver = [r for r in rows if r["outcome"] != "refused_before_vm"]
    out.append(f"reaching a verification VM (existing pre-check passed): {len(ver)}")
    by = defaultdict(Counter)
    for r in ver:
        by[(r["target"], r["bug"])][r["outcome"]] += 1
    for (t, b), cc in sorted(by.items()):
        out.append(f"  {t:<9} {b:<46} verified {cc['verified']:>2}  rejected {cc['rejected']:>2}")
    out.append("")
    for tgt in ("bugbench", "nodus", "both"):
        sub = ver if tgt == "both" else [r for r in ver if r["target"] == tgt]
        ys = [int(r["outcome"] == "verified") for r in sub]
        if len(set(ys)) < 2:
            out.append(f"[{tgt}] one class only ({len(sub)} patches, {sum(ys)} verified): "
                       "nothing to predict")
            continue
        auc, acc, maj, _ = leave_one_bug_out(sub, with_target=False)
        m, lo, hi = chance_auc(sub)
        out.append(f"[{tgt}] {len(sub)} patches, {sum(ys)} verified | leave-one-bug-out: "
                   f"model AUC {auc:.2f}, accuracy {acc:.2f} | always-majority accuracy {maj:.2f}")
        out.append(f"        shuffled labels, same protocol: AUC {m:.2f} (95% of shuffles "
                   f"in {lo:.2f}-{hi:.2f}) -> the model is "
                   + ("inside the noise" if lo <= auc <= hi else
                      "above the noise" if auc > hi else "below the noise"))
        if tgt == "both":
            auc_t, acc_t, _, _ = leave_one_bug_out(sub, with_target=True)
            out.append(f"[both + suite id] AUC {auc_t:.2f}, accuracy {acc_t:.2f}")
            out.append(f"[suite id ALONE, no patch feature] AUC {suite_only_auc(sub):.2f} - the "
                       "pooled signal is which suite the bug is from (nodus's failures are "
                       "Windows-only tests no patch can fix), not anything about the patch")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--csv", default=None)
    args = ap.parse_args(argv)
    if not RUNS.is_dir():
        print(f"no runs at {RUNS} (out/ is not versioned)", file=sys.stderr)
        return 2
    rows = load()
    if not rows:
        print("no patches with outcomes found", file=sys.stderr)
        return 2
    print(report(rows))
    if args.csv:
        Path(args.csv).parent.mkdir(parents=True, exist_ok=True)
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"csv: {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
