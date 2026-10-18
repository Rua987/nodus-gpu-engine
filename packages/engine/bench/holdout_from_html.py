"""Held-out check of a live-film run, after the fact, from the diffs in its HTML.

The live film (``scenarios/bugbench_live.json``) re-checks each verified patch on
held-out cases and writes ``<report>.holdout.json`` - unless patch-ng is missing,
as in the conda Python the 2026-10-17 take was filmed from ("held-out: not
checked"). The patch files of a run are overwritten by the next one, but the
HTML keeps every diff, and its rendering is reversible: on a run that has both,
the diffs read back from the HTML were byte-identical to the patch files, 6/6.

    python -m bench.holdout_from_html out/report_20261017T064106Z.html

Writes ``<report>.holdout.json`` with ``"checked": "after the run, from the
diffs in its HTML"`` so it never passes for the film's own check.
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

_ROW = re.compile(r'<code>([^<]+::[^<]+)</code><details><summary>patch</summary>'
                  r'<pre class="diff">(.*?)</pre>', re.S)


def diffs_from_html(text: str) -> dict:
    """{test id: patch text} for every fix row that carries a diff."""
    out = {}
    for test, pre in _ROW.findall(text):
        lines = [html.unescape(re.sub(r'^<span class="\w+">|</span>$', "", ln))
                 for ln in pre.split("\n")]
        out[html.unescape(test)] = "\n".join(lines) + "\n"
    return out


def verified_tests(md_text: str) -> list:
    ev = json.loads(md_text[md_text.index("```json") + 7:md_text.rindex("```")])
    return [e["test"] for e in ev if e.get("kind") == "fix_verified"]


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python -m bench.holdout_from_html <report.html>", file=sys.stderr)
        return 2
    from bench.thinking_ab import holdout_check
    page = Path(args[0])
    patches = diffs_from_html(page.read_text(encoding="utf-8"))
    verified = verified_tests(page.with_suffix(".md").read_text(encoding="utf-8"))
    missing = [t for t in verified if t not in patches]
    if missing:
        print(f"refusing: no diff in the HTML for {missing}", file=sys.stderr)
        return 2
    rows = [{"test": t, "holdout_ok": holdout_check(patches[t], t)} for t in verified]
    judged = [r for r in rows if r["holdout_ok"] is not None]
    ok = sum(1 for r in judged if r["holdout_ok"])
    side = page.with_suffix(".holdout.json")
    side.write_text(json.dumps({"verified": len(rows), "judged": len(judged), "holdout_ok": ok,
                                "checked": "after the run, from the diffs in its HTML",
                                "rows": rows}, indent=2), encoding="utf-8")
    print(f"held-out: {ok}/{len(judged)} verified patch(es) also pass cases the model never saw")
    print(f"held-out: {side}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
