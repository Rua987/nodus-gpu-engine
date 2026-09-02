"""Self-contained HTML render of a fleet run - screenshotable, zero deps.

``render(report_dict, path)`` writes a single .html file (inline CSS, no JS)
next to the Markdown report: routing badges, an event timeline, the shard
table with migrations, the auto-fix table with diffs, and the failures.
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

_CSS = """
:root{color-scheme:light dark}
*{box-sizing:border-box}
body{margin:0;font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;
 background:#0d1117;color:#c9d1d9;padding:32px;max-width:1000px;margin:0 auto}
h1{font-size:20px;margin:0 0 4px} h2{font-size:15px;margin:28px 0 10px;
 border-bottom:1px solid #30363d;padding-bottom:6px}
.sub{color:#8b949e;font-size:12px;margin-bottom:20px}
table{border-collapse:collapse;width:100%;font-size:13px;margin:6px 0}
th,td{border:1px solid #30363d;padding:6px 9px;text-align:left;vertical-align:top}
th{background:#161b22;font-weight:600}
code{background:#161b22;padding:1px 5px;border-radius:4px;font-size:12px}
.badge{display:inline-block;padding:2px 9px;border-radius:12px;font-size:12px;
 font-weight:600;margin:2px 4px 2px 0}
.ultra{background:#5a2a8a;color:#e9d5ff} .super{background:#1f5a8a;color:#d5eaff}
.nano{background:#2a6a3a;color:#d5f5df}
.ok{color:#3fb950} .warm{color:#d29922} .throttle{color:#f85149} .unknown{color:#8b949e}
.pill{border-left:3px solid #30363d;padding:4px 10px;margin:3px 0;font-size:12.5px}
.pill.pressure{border-color:#f85149;color:#f8a49e}
.pill.remediation{border-color:#58a6ff;color:#a5d0ff;font-weight:600}
.pill.fix{border-color:#3fb950}
pre.diff{background:#161b22;border:1px solid #30363d;border-radius:6px;
 padding:10px;overflow-x:auto;font-size:12px;margin:4px 0}
pre.diff .add{color:#3fb950} pre.diff .del{color:#f85149} pre.diff .hh{color:#8b949e}
details{margin-top:8px} summary{cursor:pointer;color:#8b949e;font-size:12px}
.kpi{display:flex;gap:14px;flex-wrap:wrap;margin:10px 0}
.kpi div{background:#161b22;border:1px solid #30363d;border-radius:8px;
 padding:10px 16px;min-width:120px}
.kpi b{display:block;font-size:22px} .kpi span{color:#8b949e;font-size:11px}
"""


def _esc(x: Any) -> str:
    return html.escape(str(x), quote=False)


def _diff_html(patch: str) -> str:
    out = []
    for ln in (patch or "").splitlines():
        cls = ("hh" if ln.startswith(("@@", "diff", "index", "--- ", "+++ "))
               else "add" if ln.startswith("+")
               else "del" if ln.startswith("-") else "")
        out.append(f'<span class="{cls}">{_esc(ln)}</span>' if cls else _esc(ln))
    return "\n".join(out)


def _timeline(events) -> str:
    rows = []
    for e in events:
        k = e.get("kind")
        if k == "model_route":
            rows.append(f'<div class="pill">route <code>{_esc(e["decision"])}</code> '
                        f'&rarr; <b>{_esc(e["tier"])}</b></div>')
        elif k == "gpu_provision":
            ids = ", ".join(n["id"] for n in e.get("nodes", []))
            rows.append(f'<div class="pill">provision &times;{e.get("provisioned")}: '
                        f'<code>{_esc(ids)}</code></div>')
        elif k == "gpu_provision_replacement":
            rows.append(f'<div class="pill remediation">+ replacement '
                        f'<code>{_esc(e["node_id"])}</code> for shard {e.get("for_shard")}</div>')
        elif k == "shard_start":
            rows.append(f'<div class="pill">shard #{e["index"]} &rarr; '
                        f'<code>{_esc(e["node_id"])}</code></div>')
        elif k == "gpu_status":
            t = e.get("telemetry") or {}
            if t:
                rows.append(f'<div class="pill">telemetry <code>{_esc(t.get("id"))}</code> '
                            f'util {t.get("util_pct")}% &middot; {t.get("temp_c")}&deg;C &middot; '
                            f'{t.get("power_w")} W &middot; '
                            f'<span class="{t.get("health")}">{_esc(str(t.get("health","")).upper())}</span></div>')
        elif k == "gpu_pressure":
            rows.append(f'<div class="pill pressure">! pressure shard {e["shard"]} on '
                        f'<code>{_esc(e["node_id"])}</code>: {_esc(e["health"])} '
                        f'{e.get("temp_c")}&deg;C / {e.get("power_w")} W</div>')
        elif k == "gpu_remediation":
            rows.append(f'<div class="pill remediation">&#8635; migrate shard {e["shard"]}: '
                        f'<code>{_esc(e["from"])}</code> &rarr; <code>{_esc(e["to"])}</code></div>')
        elif k == "fix_verified":
            rows.append(f'<div class="pill fix">fix OK <code>{_esc(e["test"])}</code> '
                        f'(re-tested green on {_esc(e.get("node"))})</div>')
        elif k == "fix_rejected":
            rows.append(f'<div class="pill">fix rejected <code>{_esc(e["test"])}</code></div>')
        elif k == "gpu_release":
            rows.append(f'<div class="pill">release: <code>{_esc(", ".join(e.get("released", [])))}</code></div>')
        elif k == "triage":
            rows.append(f'<div class="pill">triage: {e.get("unique_failures")} unique failure(s)</div>')
    return "\n".join(rows)


def render(rep: Dict[str, Any], path) -> Path:
    path = Path(path)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    plan = rep.get("plan", {})
    shards = rep.get("shards", [])
    fixes = rep.get("fixes", [])
    rems = rep.get("remediations", [])
    routes = rep.get("routes", [])
    fails = rep.get("failures", [])
    verified = [f for f in fixes if f.get("verified")]

    tiers: Dict[str, set] = {}
    for r in routes:
        tiers.setdefault(r["tier"], set()).add(r["decision"])
    badges = "".join(
        f'<span class="badge {t}">{t} &rarr; {", ".join(sorted(tiers[t]))}</span>'
        for t in ("ultra", "super", "nano") if t in tiers)

    shard_rows = ""
    for s in shards:
        node = f'<code>{_esc(s["node_id"])}</code>'
        if s.get("migrated_from"):
            node += f' <span class="throttle">&larr; migrated from {_esc(s["migrated_from"])}</span>'
        shard_rows += (f'<tr><td>{s["index"]}</td><td>{node}</td>'
                       f'<td>{s["exit_code"]}</td><td>{s["duration_s"]}</td>'
                       f'<td>{len(s.get("failures", []))}</td></tr>')

    fix_rows = ""
    for f in fixes:
        mark = ('<span class="ok">&#10003; verified</span>' if f.get("verified")
                else '<span class="unknown">no patch</span>' if not f.get("patch")
                else '<span class="throttle">&#10007; still red</span>')
        diff = (f'<details><summary>patch</summary><pre class="diff">{_diff_html(f["patch"])}</pre></details>'
                if f.get("patch") else "")
        fix_rows += f'<tr><td><code>{_esc(f["test"])}</code>{diff}</td><td>{mark}</td></tr>'

    rem_rows = "".join(
        f'<div class="pill remediation">shard {r["shard"]}: <code>{_esc(r["from"])}</code> '
        f'{_esc(r["reason"])} ({r.get("temp_c")}&deg;C, {r.get("power_w")} W) &rarr; '
        f'<code>{_esc(r["to"])}</code></div>' for r in rems) or \
        '<div class="pill">no remediation - every node stayed within budget</div>'

    fail_rows = "".join(
        f'<tr><td><code>{_esc(f["test"])}</code></td><td><code>{_esc(f["error"])}</code></td>'
        f'<td>{_esc(f.get("proposed_fix",""))}</td></tr>' for f in fails) or \
        '<tr><td colspan="3">no failures</td></tr>'

    doc = f"""<!doctype html><meta charset="utf-8">
<title>Fleet run - {ts}</title><style>{_CSS}</style>
<h1>Nodus-GPU Engine &mdash; fleet run</h1>
<div class="sub">{ts} &middot; fleet <code>{_esc((rep.get('events') or [{}])[0].get('fleet_mode','?'))}</code>
 / sandbox <code>{_esc((rep.get('events') or [{}])[0].get('sandbox_mode','?'))}</code>
 &middot; plan <code>{_esc(plan.get('source'))}</code>: {_esc(plan.get('names'))}</div>

<div class="kpi">
 <div><b>{len(shards)}</b><span>SHARDS</span></div>
 <div><b>{len(fails)}</b><span>UNIQUE FAILURES</span></div>
 <div><b>{len(verified)}/{len(fixes)}</b><span>AUTO-FIXED &amp; VERIFIED</span></div>
 <div><b>{len(rems)}</b><span>GPU REMEDIATIONS</span></div>
</div>

<h2>Model routing (Nemotron tiers)</h2>{badges or '<span class="sub">none</span>'}

<h2>Shards</h2>
<table><tr><th>#</th><th>node</th><th>exit</th><th>dur (s)</th><th>failures</th></tr>{shard_rows}</table>

<h2>Self-managed compute</h2>{rem_rows}

<h2>Auto-fixes (code agent)</h2>
<table><tr><th>test</th><th>outcome</th></tr>{fix_rows or '<tr><td colspan=2>none</td></tr>'}</table>

<h2>Consolidated failures</h2>
<table><tr><th>test</th><th>error</th><th>heuristic hint</th></tr>{fail_rows}</table>

<h2>Event timeline</h2>{_timeline(rep.get('events', []))}

<details><summary>raw event log (JSON)</summary>
<pre class="diff">{_esc(json.dumps(rep.get('events', []), indent=2))}</pre></details>
"""
    path.write_text(doc, encoding="utf-8")
    return path
