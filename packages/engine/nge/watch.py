"""Live console view of a fleet run.

Plug it into the orchestrator as the telemetry sink
(``NgeOrchestrator(config, telemetry=ConsoleWatch())``): it redraws a fleet
table on every event - util / temp bars per node, the throttling node in red,
the shard migration - so the "agents self-manage their compute" moment is
visible instead of buried in a JSON log. Zero dependencies.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Optional, TextIO

_R = "\033[0m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_CYAN = "\033[36m"

_HEALTH_COLOR = {"ok": _GREEN, "warm": _YELLOW, "throttle": _RED}


def _enable_vt() -> None:
    if os.name == "nt":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            k.SetConsoleMode(k.GetStdHandle(-11), 7)
        except Exception:
            pass


def _bar(value: float, lo: float, hi: float, width: int = 12) -> str:
    frac = 0.0 if hi <= lo else max(0.0, min(1.0, (value - lo) / (hi - lo)))
    n = int(round(frac * width))
    return "█" * n + "░" * (width - n)


class ConsoleWatch:
    def __init__(self, stream: Optional[TextIO] = None, delay: float = 0.0,
                 color: Optional[bool] = None) -> None:
        self.out = stream or sys.stdout
        self.delay = delay
        if color is None:
            color = self.out.isatty() and os.environ.get("NO_COLOR") is None
        self.color = bool(color)
        if self.color:
            _enable_vt()
        self._nodes: dict[str, dict] = {}
        self._log: list[str] = []
        self._title = "fleet"
        self._done = False

    # -- colour helper --------------------------------------------------
    def _c(self, s: str, code: str) -> str:
        return f"{code}{s}{_R}" if self.color else s

    # -- telemetry sink ----------------------------------------------
    def record(self, kind: str, **f) -> None:
        if kind == "run_start":
            self._title = f"fleet  ({f.get('fleet_mode')}/{f.get('sandbox_mode')}, jail={f.get('jail')})"
            self._log.append("run start")
        elif kind == "plan":
            self._log.append(f"plan [{f.get('source')}]: {f.get('names')}")
        elif kind == "model_route":
            self._log.append(f"route  {f.get('decision'):<11} -> {f.get('tier')}")
        elif kind == "gpu_provision":
            for n in f.get("nodes", []):
                self._nodes[n["id"]] = {"state": "ready", "shard": None,
                                        "pressured": False, "migrated_from": None}
            self._log.append(f"provision x{f.get('provisioned')}: "
                             + ", ".join(n["id"] for n in f.get("nodes", [])))
        elif kind == "gpu_provision_replacement":
            nid = f["node_id"]
            self._nodes[nid] = {"state": "ready", "shard": f.get("for_shard"),
                                "pressured": False, "migrated_from": None}
            self._log.append(self._c(f"+ provision {nid}  (replacement for shard {f.get('for_shard')})", _CYAN))
        elif kind == "shard_start":
            nd = self._nodes.setdefault(f["node_id"], {})
            nd.update(state="running", shard=f["index"])
            self._log.append(f"shard #{f['index']} -> {f['node_id']}")
        elif kind == "gpu_status":
            t = f.get("telemetry") or {}
            if t.get("id") in self._nodes:
                self._nodes[t["id"]].update(t)
        elif kind == "gpu_pressure":
            nd = self._nodes.setdefault(f["node_id"], {})
            nd["pressured"] = True
            self._log.append(self._c(
                f"! pressure  shard {f['shard']} on {f['node_id']}: "
                f"{f['health']}  {f.get('temp_c')}C / {f.get('power_w')}W", _RED))
        elif kind == "gpu_remediation":
            src, dst = f["from"], f["to"]
            if src in self._nodes:
                self._nodes[src].update(state="released", shard=None)
            nd = self._nodes.setdefault(dst, {})
            nd.update(state="running", shard=f["shard"], migrated_from=src, pressured=False)
            self._log.append(self._c(
                f"↻ migrate  shard {f['shard']}:  {src}  ──▶  {dst}", _CYAN + _BOLD))
        elif kind == "gpu_release":
            for nid in f.get("released", []):
                if nid in self._nodes:
                    self._nodes[nid].update(state="released", shard=None)
            self._log.append(f"release: {', '.join(f.get('released', []))}")
        elif kind == "triage":
            self._log.append(f"triage: {f.get('unique_failures')} unique failure(s)")
        elif kind == "artifact":
            self._log.append(f"artifact: {f.get('path')}")
        elif kind == "run_end":
            self._done = True
            self._log.append(self._c("run complete", _GREEN + _BOLD))

        self._render()
        if self.delay and not self._done:
            time.sleep(self.delay)

    # -- render -------------------------------------------------------
    def _render(self) -> None:
        lines = []
        if self.color:
            lines.append("\033[H\033[J")           # cursor home + clear
        lines.append(self._c(f"  {self._title}", _BOLD))
        lines.append("  " + "─" * 76)
        for nid, nd in self._nodes.items():
            util = float(nd.get("util_pct", 0) or 0)
            temp = float(nd.get("temp_c", 0) or 0)
            power = float(nd.get("power_w", 0) or 0)
            health = nd.get("health", "-")
            state = nd.get("state", "-")
            shard = nd.get("shard")
            hc = _HEALTH_COLOR.get(health, "")
            released = state == "released"
            name = f"{nid:<12}"
            if released:
                row = self._c(f"  {name} {state:<9} (freed)", _DIM)
            else:
                tag = f"shard#{shard}" if shard is not None else ""
                if nd.get("migrated_from"):
                    tag += self._c(f"  <- {nd['migrated_from']}", _CYAN)
                row = (f"  {name} "
                       f"util {self._c(_bar(util, 0, 100), hc)} {util:5.1f}%  "
                       f"temp {self._c(_bar(temp, 30, 95), hc)} {temp:5.1f}C  "
                       f"{power:5.0f}W  {self._c(health.upper(), hc)}  {tag}")
            lines.append(row)
        lines.append("  " + "─" * 76)
        for msg in self._log[-9:]:
            lines.append(f"  {msg}")
        self.out.write("\n".join(lines) + "\n")
        self.out.flush()
