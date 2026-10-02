"""Self-contained HTML render of a fleet run - screenshotable, zero deps.

Control-room layout for judges (5-second read): hero, KPIs, node cards,
story timeline, then patches. Inline CSS only — no JS, no CDN.
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_CSS = """
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;font:13px/1.5 ui-sans-serif,Segoe UI,Roboto,sans-serif;
 background:#0a0a0a;color:#d4d4d4;padding:24px 28px;max-width:1100px;margin:0 auto}
h1{font-size:18px;margin:0 0 2px;letter-spacing:.02em}
.hero{color:#737373;font-size:12px;margin:0 0 16px;font-family:ui-monospace,Consolas,monospace}
h2{font-size:11px;margin:22px 0 8px;color:#a3a3a3;text-transform:uppercase;
 letter-spacing:.12em;border-bottom:1px solid #262626;padding-bottom:5px}
.sub{color:#737373;font-size:12px;margin:6px 0}
table{border-collapse:collapse;width:100%;font-size:12px;margin:6px 0;
 font-family:ui-monospace,Consolas,monospace}
th,td{border:1px solid #262626;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#141414;color:#a3a3a3;font-weight:600}
code{background:#141414;padding:1px 5px;border-radius:3px;font-size:11px}
.roles{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:6px 0}
.badge{display:inline-block;padding:2px 8px;border-radius:3px;font-size:11px;
 font-weight:600;margin:0;font-family:ui-monospace,Consolas,monospace}
.ultra{background:#3b0764;color:#e9d5ff} .super{background:#172554;color:#bfdbfe}
.nano{background:#14532d;color:#bbf7d0}
.ok{color:#4ade80} .warm{color:#fbbf24} .throttle{color:#f87171} .unknown{color:#737373}
.pill{border-left:3px solid #404040;padding:3px 10px;margin:2px 0;font-size:12px;
 font-family:ui-monospace,Consolas,monospace}
.pill.pressure{border-color:#ef4444;color:#fca5a5}
.pill.remediation{border-color:#38bdf8;color:#7dd3fc;font-weight:600}
.pill.fix{border-color:#22c55e}
.pill.place{border-color:#a78bfa;color:#ddd6fe}
pre.diff{background:#141414;border:1px solid #262626;border-radius:4px;
 padding:10px;overflow-x:auto;font-size:11px;margin:4px 0}
pre.diff .add{color:#4ade80} pre.diff .del{color:#f87171} pre.diff .hh{color:#737373}
details{margin-top:8px} summary{cursor:pointer;color:#737373;font-size:12px}
.kpi{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}
.kpi div{background:#141414;border:1px solid #262626;border-radius:6px;
 padding:10px 14px;min-width:110px}
.kpi b{display:block;font-size:22px;font-family:ui-monospace,Consolas,monospace}
.kpi span{color:#737373;font-size:10px;letter-spacing:.08em}
.cards{display:flex;gap:10px;flex-wrap:wrap;margin:8px 0 4px}
.card{background:#141414;border:1px solid #262626;border-radius:6px;
 padding:10px 12px;min-width:200px;flex:1}
.card.th{border-color:#7f1d1d;animation:pulse 1.6s ease-in-out infinite}
.card.okn{border-color:#14532d}
.card.rel{opacity:.55}
.card .id{font-family:ui-monospace,Consolas,monospace;font-weight:700;font-size:13px}
.card .st{font-size:10px;letter-spacing:.1em;margin:4px 0 8px}
.bar{height:6px;background:#262626;border-radius:3px;margin:3px 0 6px;overflow:hidden}
.bar>i{display:block;height:100%;border-radius:3px}
.bar.t>i{background:#f87171} .bar.u>i{background:#38bdf8}
.meta{font-family:ui-monospace,Consolas,monospace;font-size:10px;color:#a3a3a3}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(239,68,68,.0)}
 50%{box-shadow:0 0 0 4px rgba(239,68,68,.18)}}
"""


def _esc(x: Any) -> str:
    return html.escape(str(x), quote=False)


def _esc_attr(x: Any) -> str:
    return html.escape(str(x), quote=True)


def _diff_html(patch: str) -> str:
    out = []
    for ln in (patch or "").splitlines():
        cls = ("hh" if ln.startswith(("@@", "diff", "index", "--- ", "+++ "))
               else "add" if ln.startswith("+")
               else "del" if ln.startswith("-") else "")
        out.append(f'<span class="{cls}">{_esc(ln)}</span>' if cls else _esc(ln))
    return "\n".join(out)


def _event(events: List[dict], kind: str) -> dict:
    for e in events or []:
        if e.get("kind") == kind:
            return e
    return {}


def _last_telemetry(events: List[dict]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for e in events or []:
        if e.get("kind") != "gpu_status":
            continue
        t = e.get("telemetry") or {}
        nid = t.get("id") or e.get("node_id")
        if nid:
            out[str(nid)] = t
    return out


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
            if t.get("probe_kind") == "cpu-fallback":
                rows.append(
                    f'<div class="pill">telemetry <code>{_esc(t.get("id"))}</code> '
                    f'cpu-fallback — no GPU thermometer (not OK at 0&deg;C)</div>'
                )
            elif t:
                rows.append(f'<div class="pill">telemetry <code>{_esc(t.get("id"))}</code> '
                            f'util {t.get("util_pct")}% &middot; {t.get("temp_c")}&deg;C &middot; '
                            f'{t.get("power_w")} W &middot; '
                            f'<span class="{_esc_attr(t.get("health"))}">{_esc(str(t.get("health","")).upper())}</span></div>')
        elif k == "patch_truncated":
            rsn = e.get("reasoning_tokens")
            rows.append(
                f'<div class="pill">patch truncated <code>{_esc(e.get("test"))}</code> '
                f'{_esc(e.get("max_tokens"))} tokens, '
                f'{_esc(e.get("reply_chars", 0))}-char reply'
                + (f', {_esc(rsn)} spent reasoning' if rsn else "") + '</div>'
            )
        elif k == "slotfill_truncated":
            rsn = e.get("reasoning_tokens")
            rows.append(
                f'<div class="pill">slot-fill shard {_esc(e.get("shard"))} cut at '
                f'{_esc(e.get("max_tokens"))} tokens'
                + (f' ({_esc(rsn)} reasoning)' if rsn else "")
                + ' &rarr; template command</div>'
            )
        elif k == "gpu_pressure":
            rows.append(f'<div class="pill pressure">! pressure shard {e["shard"]} on '
                        f'<code>{_esc(e["node_id"])}</code>: {_esc(e["health"])} '
                        f'{e.get("temp_c")}&deg;C / {e.get("power_w")} W</div>')
        elif k == "gpu_placement":
            rows.append(f'<div class="pill place">placement shard {e.get("shard")}: '
                        f'pick <code>{_esc(e.get("chosen") or "none")}</code> '
                        f'score={_esc(e.get("score"))}</div>')
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
        elif k == "plan_gated_autofix":
            on = "ON" if e.get("allowed") else "OFF"
            rows.append(f'<div class="pill">plan gate autofix {on} '
                        f'plan={_esc(e.get("plan"))}</div>')
    return "\n".join(rows)


_STORY_KINDS = frozenset({
    "gpu_pressure", "gpu_placement", "gpu_placement_refused",
    "gpu_remediation", "gpu_provision_replacement",
    "fix_verified", "fix_rejected", "triage", "plan_gated_autofix",
})


def _story_events(events: List[dict], limit: int = 14) -> List[dict]:
    """Keep the judge plot (pressure → place → migrate → fix), not every poll."""
    out: List[dict] = []
    saw_provision = False
    saw_plan_route = False
    for e in events or []:
        k = e.get("kind")
        if k == "gpu_provision" and not saw_provision:
            out.append(e)
            saw_provision = True
        elif k == "model_route" and e.get("decision") == "plan" and not saw_plan_route:
            out.append(e)
            saw_plan_route = True
        elif k in _STORY_KINDS:
            if k == "gpu_placement" and not e.get("chosen") and len(out) > 2:
                # keep first refuse, skip later empty picks
                if any(x.get("kind") == "gpu_placement" and not x.get("chosen")
                       for x in out):
                    continue
            out.append(e)
        if len(out) >= limit:
            break
    return out


def _verify_nodes(fixes: List[dict]) -> List[str]:
    seen: List[str] = []
    for f in fixes or []:
        nid = f.get("node")
        if nid and str(nid) not in seen:
            seen.append(str(nid))
    return seen


def _truncations(events: List[dict]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for e in events or []:
        if e.get("kind") == "patch_truncated" and e.get("test"):
            out[str(e["test"])] = e
    return out


def _fix_subtitle(fixes: List[dict]) -> str:
    n_tried = len(fixes or [])
    n_kept = sum(1 for f in (fixes or []) if f.get("verified"))
    n_with_patch = sum(1 for f in (fixes or []) if f.get("patch"))
    n_rejected = sum(
        1 for f in (fixes or [])
        if f.get("patch") and not f.get("verified")
    )
    n_empty = n_tried - n_with_patch
    if n_tried == 0:
        return "No patches attempted (plan gate off, or nothing in scope)."
    if n_kept == n_tried:
        return f"{n_kept}/{n_tried} kept. All attempted patches re-tested green."
    if n_kept == 0 and n_rejected and n_empty:
        return (
            f"{n_kept}/{n_tried} kept: {n_rejected} patch(es) re-tested red, "
            f"{n_empty} no usable diff (truncated/empty) — honesty, not a hidden 2/3."
        )
    if n_kept == 0 and n_rejected:
        return (
            f"{n_kept}/{n_tried} kept. Patch(es) applied but still red "
            "after re-test — honesty, not a hidden 2/3."
        )
    if n_kept == 0:
        return (
            f"{n_kept}/{n_tried} kept. Super produced no usable diff "
            "(truncated or empty) — honesty, not a hidden 2/3."
        )
    return f"{n_kept}/{n_tried} kept. Less than all is honesty, not a miss."


def _node_cards(shards: List[dict], rems: List[dict],
                tele: Dict[str, dict],
                verify_ids: Optional[List[str]] = None,
                cpu_fallback: bool = False) -> str:
    released = {str(r.get("from")) for r in rems if r.get("from")}
    dests = {str(r.get("to")) for r in rems if r.get("to")}
    verify_ids = list(verify_ids or [])
    ids: List[str] = []
    for s in shards:
        mid = s.get("migrated_from")
        if mid and str(mid) not in ids:
            ids.append(str(mid))
        nid = s.get("node_id")
        if nid and str(nid) not in ids:
            ids.append(str(nid))
    for nid in dests:
        if nid not in ids:
            ids.append(nid)
    for nid in verify_ids:
        if nid not in ids:
            ids.append(nid)
    if not ids:
        return '<p class="sub">no nodes in this report</p>'
    cards = []
    for nid in ids:
        t = tele.get(nid) or {}
        shard = next((s for s in shards if s.get("node_id") == nid), None)
        if nid in released:
            # Still the hot house — don't grey it into "just freed".
            st, cls = "THROTTLED then released", "th"
        elif (t.get("health") or "") == "throttle":
            st, cls = "THROTTLED", "th"
        elif nid in dests:
            st, cls = "RUNNING", "okn"
        elif (t.get("health") or "") == "warm":
            st, cls = "WARM", "card"
        else:
            st, cls = (t.get("health") or "READY").upper(), "okn"
        temp = float(t.get("temp_c") or 0)
        util = float(t.get("util_pct") or 0)
        tw = min(100, max(0, temp))
        uw = min(100, max(0, util))
        sh = f"shard {shard['index']}" if shard else "—"
        fail_n = len((shard or {}).get("failures") or [])
        mig = ""
        if shard and shard.get("migrated_from"):
            mig = f' &larr; {_esc(shard["migrated_from"])}'
            st, cls = "MIGRATED IN", "okn"
        verify_only = (
            nid in verify_ids and shard is None
            and nid not in dests and nid not in released
        )
        if verify_only:
            st, cls = "VERIFY — fresh box", "okn"
            cards.append(
                f'<div class="card {cls}"><div class="id">{_esc(nid)}</div>'
                f'<div class="st">{_esc(st)}</div>'
                f'<div class="meta">sandbox (not a fleet GPU)</div>'
                f'<div class="meta">re-test after patch</div></div>'
            )
            continue
        cpu_node = (
            (t.get("probe_kind") == "cpu-fallback")
            or (cpu_fallback and nid not in released
                and (t.get("health") or "ok") not in ("throttle", "warm"))
        )
        if cpu_node:
            cards.append(
                f'<div class="card"><div class="id">{_esc(nid)}</div>'
                f'<div class="st">CPU — no GPU probe</div>'
                f'<div class="meta">probe=cpu-fallback (not an H100)</div>'
                f'<div class="meta">{_esc(sh)} &middot; {fail_n} fail'
                f'{"" if fail_n == 1 else "s"}</div></div>'
            )
            continue
        cards.append(
            f'<div class="card {cls}"><div class="id">{_esc(nid)}</div>'
            f'<div class="st {cls if cls in ("th",) else ""}">{_esc(st)}'
            f'{mig}</div>'
            f'<div class="meta">temp {temp:.0f}C</div>'
            f'<div class="bar t"><i style="width:{tw:.0f}%"></i></div>'
            f'<div class="meta">util {util:.0f}%</div>'
            f'<div class="bar u"><i style="width:{uw:.0f}%"></i></div>'
            f'<div class="meta">{_esc(sh)} &middot; {fail_n} fail'
            f'{"" if fail_n == 1 else "s"}</div></div>'
        )
    note = ""
    extra = [n for n in verify_ids if n not in dests
             and n not in {str(s.get("node_id") or "") for s in shards}
             and n not in {str(s.get("migrated_from") or "") for s in shards}]
    if extra:
        note = (
            '<p class="sub">Verify = fresh sandbox after the patch '
            f'(<code>{_esc(", ".join(extra))}</code>) — not a fleet H100.</p>'
        )
    if cpu_fallback:
        legend = (
            '<p class="sub">Contree CPU: no nvidia-smi. '
            'Green/red thermal colours do not apply. Heal gated.</p>'
        )
    else:
        legend = (
            '<p class="sub">Green = still working. Yellow = warm. '
            'Red pulse = overheated (we moved the job). '
            'Grey/faded is not used: a hot node stays red after release so you see why.</p>'
        )
    return f'<div class="cards">{"".join(cards)}</div>{note}{legend}'


def _run_ts(events: List[dict]) -> str:
    t = _event(events, "run_start").get("t")
    if t is not None:
        try:
            return datetime.fromtimestamp(float(t), timezone.utc).strftime(
                "%Y-%m-%d %H:%M UTC")
        except (OSError, OverflowError, ValueError):
            pass
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def render(rep: Dict[str, Any], path) -> Path:
    path = Path(path)
    plan = rep.get("plan", {})
    shards = rep.get("shards", [])
    fixes = rep.get("fixes", [])
    rems = rep.get("remediations", [])
    routes = rep.get("routes", [])
    fails = rep.get("failures", [])
    events = rep.get("events") or []
    ts = _run_ts(events)
    verified = [f for f in fixes if f.get("verified")]
    start = _event(events, "run_start")
    fleet = start.get("fleet_mode") or "?"
    sandbox = start.get("sandbox_mode") or "?"
    wall = round(sum(float(s.get("duration_s") or 0) for s in shards), 1)
    tele = _last_telemetry(events)
    probe = ""
    for e in events:
        if e.get("kind") == "capabilities":
            probe = e.get("expect_probe") or ""
            break
    cpu_fallback = probe == "cpu-fallback"
    trunc = _truncations(events)

    tiers: Dict[str, set] = {}
    for r in routes:
        tiers.setdefault(r["tier"], set()).add(r["decision"])
    # Local planner (324M / heuristic) did the plan: Ultra was routed, not billed.
    ultra_route_only = (
        "ultra" in tiers
        and (plan.get("source") or "") in ("heuristic", "nodus-324m")
    )
    # Space between spans so copy/paste cannot glue "plansuper" / "triagenano".
    badge_bits = []
    for t in ("ultra", "super", "nano"):
        if t not in tiers:
            continue
        note = " (route only)" if t == "ultra" and ultra_route_only else ""
        badge_bits.append(
            f'<span class="badge {t}">{t} &rarr; {", ".join(sorted(tiers[t]))}'
            f'{_esc(note)}</span>'
        )
    badges = (f'<div class="roles">{" ".join(badge_bits)}</div>'
              if badge_bits else "")

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
        urg = (f.get("urgency") or "").lower()
        urg_cls = {"high": "throttle", "medium": "warm", "low": "ok"}.get(urg, "unknown")
        urg_badge = (f'<span class="{urg_cls}">urgency:{_esc(urg or "?")}</span>'
                     if urg else "")
        diff = (f'<details><summary>patch</summary><pre class="diff">{_diff_html(f["patch"])}</pre></details>'
                if f.get("patch") else "")
        why = f.get("reason") or ""
        tr = trunc.get(f.get("test") or "")
        if tr and not f.get("patch"):
            rsn = tr.get("reasoning_tokens")
            why = (
                f"Super truncated ({tr.get('max_tokens')} tokens, "
                f"{tr.get('reply_chars', 0)}-char reply"
                + (f", {rsn} spent reasoning" if rsn else "") + ")"
            )
        why = _esc(why)
        extras = ""
        if f.get("cause"):
            extras += f'<div class="sub">{_esc(f["cause"])}</div>'
        if f.get("fragility"):
            extras += f'<div class="sub">{_esc(f["fragility"])}</div>'
        fix_rows += (
            f'<tr><td><code>{_esc(f["test"])}</code>{diff}</td>'
            f'<td>{mark} {urg_badge}</td>'
            f'<td>{why}{extras}</td></tr>'
        )

    # Duplicate of gpu_remediation in the story; only keep the empty case.
    if rems:
        rem_rows = ""
    elif cpu_fallback:
        rem_rows = (
            '<div class="pill">no remediation — heal gated '
            '(cpu-fallback, no GPU thermometer)</div>'
        )
    else:
        rem_rows = (
            '<div class="pill">no remediation - every node stayed within budget</div>'
        )

    fail_rows = "".join(
        f'<tr><td><code>{_esc(f["test"])}</code></td><td><code>{_esc(f["error"])}</code></td>'
        f'<td>{_esc(f.get("proposed_fix",""))}</td></tr>' for f in fails) or \
        '<tr><td colspan="3">no failures</td></tr>'
    fix_tests = {f.get("test") for f in fixes if f.get("test")}
    fail_tests = {f.get("test") for f in fails if f.get("test")}
    fail_dup = bool(fails and fix_tests and fail_tests & fix_tests)
    if fail_dup:
        fail_block = (
            f'<details><summary>Failures ({len(fails)} tests — already in Auto-fixes)</summary>'
            f'<table><tr><th>test</th><th>error</th><th>hint</th></tr>'
            f'{fail_rows}</table></details>'
        )
    else:
        fail_block = (
            f'<h2>Failures</h2>'
            f'<table><tr><th>test</th><th>error</th><th>hint</th></tr>'
            f'{fail_rows}</table>'
        )

    honest = ""
    if fleet == "mock" or probe == "synthetic":
        honest = "Mock telemetry (synthetic H100). Same loop as live; Contree live is CPU — heal gated."
    elif probe == "cpu-fallback":
        honest = "Live Token Factory Contree: probe=cpu-fallback. Thermal heal gated (not a physical GPU)."
    if cpu_fallback:
        story_sub = (
            "This run: Contree shard &rarr; triage &rarr; Super patch attempt. "
            "No pressure/migrate (heal gated)."
        )
    else:
        story_sub = (
            "Short plot only (pressure &rarr; place &rarr; migrate &rarr; patch). "
            "Full log below."
        )

    doc = f"""<!doctype html><meta charset="utf-8">
<title>Fleet run - {ts}</title><style>{_CSS}</style>
<h1>Nodus-GPU Engine &mdash; control room</h1>
<p class="hero">Not a chatbot. Plan &rarr; shard tests &rarr; place/migrate &rarr; patch &rarr; keep only green.<br>
{ts} &middot; fleet <code>{_esc(fleet)}</code> / sandbox <code>{_esc(sandbox)}</code>
 &middot; plan <code>{_esc(plan.get('source'))}</code> {_esc(plan.get('names'))}
{('<br>' + _esc(honest)) if honest else ''}</p>

<div class="kpi">
 <div><b>{len(shards)}</b><span>SHARDS</span></div>
 <div><b>{wall}s</b><span>SHARD WALL (SUM)</span></div>
 <div><b>{len(fails)}</b><span>UNIQUE FAILURES</span></div>
 <div><b>{len(verified)}/{len(fixes)}</b><span>PATCHES KEPT</span></div>
 <div><b>{len(rems)}</b><span>MIGRATIONS</span></div>
</div>

<h2>Fleet</h2>
{_node_cards(shards, rems, tele, _verify_nodes(fixes), cpu_fallback)}

<h2>Nemotron roles</h2>{badges or '<span class="sub">none</span>'}

<h2>Story</h2>
<p class="sub">{story_sub}</p>
{rem_rows}
{_timeline(_story_events(events))}

<h2>Shards</h2>
<table><tr><th>#</th><th>node</th><th>exit</th><th>dur (s)</th><th>failures</th></tr>{shard_rows}</table>

<h2>Auto-fixes</h2>
<p class="sub">Symptom &rarr; why kept or skipped &rarr; urgency. {_esc(_fix_subtitle(fixes))}</p>
<table><tr><th>test</th><th>outcome</th><th>why / cause / fragility</th></tr>{fix_rows or '<tr><td colspan=3>none</td></tr>'}</table>

{fail_block}

<details><summary>full event timeline</summary>
{_timeline(events)}
</details>
<details><summary>raw event log (JSON)</summary>
<pre class="diff">{_esc(json.dumps(events, indent=2))}</pre></details>
"""
    path.write_text(doc, encoding="utf-8")
    return path
