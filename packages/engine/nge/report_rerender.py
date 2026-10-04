"""Re-render a run's HTML control room from its Markdown report.

The ``.md`` the orchestrator writes carries the full run-time event log plus
the shard table and the consolidated failures - everything the HTML needs
for a run without fix attempts. So a renderer improvement can be shown on an
old run without re-running it (and without paying for its VMs again), and the
result is reproducible, unlike the hand-made ``_honest`` re-render of
2026-09-13.

    python -m nge.report_rerender evidence/report_20261004T031503Z.md \\
        evidence/report_20261004T031503Z_rerender.html

Refuses a run that attempted fixes: patch bodies and verdict rows are not in
the event log, and a control room without them would misstate the run.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

_SHARD_ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*`([^`]+)`.*?\|\s*(-?\d+)\s*\|\s*([\d.]+)\s*\|\s*(\d+)\s*\|\s*$",
                        re.M)
_FAILURE = re.compile(r"^### `([^`]+)`\n- Error: `(.*)`\n- Seen on: shard (\d+) / node `([^`]+)`"
                      r"(?:\n- Heuristic hint: (.*))?", re.M)


def from_markdown(text: str) -> Dict[str, Any]:
    """The ``report_html.render`` input, rebuilt from a Markdown report."""
    events: List[dict] = json.loads(text[text.index("```json") + 7:text.rindex("```")])
    if any(e.get("kind") in ("fix_attempt", "fix_verified", "fix_rejected") for e in events):
        raise ValueError("run attempted fixes: patches and verdicts are not in the event log")
    plan = next((e for e in events if e.get("kind") == "plan"), {})
    failures = [{"test": test, "error": err, "shard": int(shard), "node_id": node,
                 "proposed_fix": hint.strip()}
                for test, err, shard, node, hint in _FAILURE.findall(text)]
    migrated = {e.get("shard"): e.get("from") for e in events
                if e.get("kind") == "gpu_remediation"}
    shards = []
    for idx, node, code, dur, n in _SHARD_ROW.findall(text.split("## Shards", 1)[1]
                                                     .split("\n## ", 1)[0]):
        i = int(idx)
        own = [f for f in failures if f["shard"] == i]
        if len(own) != int(n):
            raise ValueError(f"shard {i}: table says {n} failures, the list has {len(own)}")
        shards.append({"index": i, "node_id": node, "exit_code": int(code),
                       "duration_s": float(dur), "failures": own,
                       "migrated_from": migrated.get(i)})
    return {
        "plan": {"names": plan.get("names", []), "source": plan.get("source", "")},
        "shards": shards,
        "failures": failures,
        "routes": [{"decision": e["decision"], "tier": e["tier"], "model": e.get("model")}
                   for e in events if e.get("kind") == "model_route"],
        "remediations": [{k: v for k, v in e.items() if k not in ("t", "kind")}
                         for e in events if e.get("kind") == "gpu_remediation"],
        "fixes": [],
        "events": events,
    }


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: python -m nge.report_rerender <report.md> <out.html>", file=sys.stderr)
        return 2
    from nge import report_html
    src, out = Path(args[0]), Path(args[1])
    try:
        rep = from_markdown(src.read_text(encoding="utf-8"))
    except ValueError as exc:
        print(f"refusing: {exc}", file=sys.stderr)
        return 2
    print(report_html.render(rep, out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
