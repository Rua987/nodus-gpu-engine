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
        self._expect_cpu = False      # capabilities said: no GPU in these nodes
        self._sandbox = ""            # from run_start; "mock" times are made up

    # -- colour helper --------------------------------------------------
    def _c(self, s: str, code: str) -> str:
        return f"{code}{s}{_R}" if self.color else s

    # -- telemetry sink ----------------------------------------------
    def record(self, kind: str, **f) -> None:
        if kind == "capabilities":
            self._expect_cpu = f.get("expect_probe") == "cpu-fallback"
            heal = "heal ON" if f.get("heal_enabled") else "heal gated"
            self._log.append(self._c(
                f"capabilities  host={f.get('host_summary')}  "
                f"expect={f.get('expect_probe')}  {heal}",
                _GREEN if f.get("heal_enabled") else _YELLOW))
        elif kind == "run_start":
            self._title = f"fleet  ({f.get('fleet_mode')}/{f.get('sandbox_mode')}, jail={f.get('jail')})"
            self._sandbox = f.get("sandbox_mode") or ""
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
            pk = t.get("probe_kind")
            if pk and pk not in ("synthetic",):
                self._log.append(self._c(
                    f"probe  {t.get('id')}  {pk}"
                    + (f"  {t.get('gpu_name')}" if t.get("gpu_name") else "")
                    + (f"  class={t.get('gpu_class')}" if t.get("gpu_class") else ""),
                    _YELLOW if pk != "nvidia-smi" else _GREEN))
        elif kind == "gpu_telemetry_non_gpu":
            self._log.append(self._c(
                f"probe non-GPU  {f.get('node_id')}  "
                f"{f.get('probe_kind')} — heal skipped ({f.get('why')})",
                _YELLOW))
        elif kind in ("gpu_load_induced", "gpu_load_not_induced"):
            if kind == "gpu_load_induced":
                self._log.append(self._c(
                    f"! induced load (declared)  {f.get('node_id')}: GPU burn for "
                    f"{f.get('seconds')} s", _YELLOW + _BOLD))
            else:
                self._log.append(self._c(
                    f"induced load NOT started  {f.get('node_id')}: "
                    f"{f.get('why') or f.get('error')}", _RED))
        elif kind == "gpu_pressure":
            nd = self._nodes.setdefault(f["node_id"], {})
            nd["pressured"] = True
            util = f" util {f['util_pct']}%" if f.get("util_pct") is not None else ""
            self._log.append(self._c(
                f"! pressure  shard {f['shard']} on {f['node_id']}: "
                f"{f['health']}{util}  {f.get('temp_c')}C / {f.get('power_w')}W", _RED))
            if f.get("gpu_processes"):
                self._log.append(self._c(f"  on the GPU: {f['gpu_processes']}", _RED))
        elif kind == "gpu_placement":
            chosen = f.get("chosen") or "(none)"
            self._log.append(self._c(
                f"placement  shard {f.get('shard')}: pick {chosen}  "
                f"score={f.get('score')}  ({f.get('reason')})", _CYAN))
        elif kind == "gpu_placement_refused":
            self._log.append(self._c(
                f"placement REFUSED  shard {f.get('shard')}: {f.get('reason')}",
                _RED))
        elif kind == "gpu_remediation":
            src, dst = f["from"], f["to"]
            if src in self._nodes:
                self._nodes[src].update(state="released", shard=None)
            nd = self._nodes.setdefault(dst, {})
            nd.update(state="running", shard=f["shard"], migrated_from=src, pressured=False)
            took = ""
            # a simulated sandbox's times are made up: no "faster here" in the mock film
            if (self._sandbox != "mock" and f.get("duration_before_s") is not None
                    and f.get("duration_after_s") is not None):
                took = f"  ({f['duration_before_s']}s there, {f['duration_after_s']}s here)"
            self._log.append(self._c(
                f"↻ migrate  shard {f['shard']}:  {src}  ──▶  {dst}{took}", _CYAN + _BOLD))
        elif kind == "gpu_release":
            for nid in f.get("released", []):
                if nid in self._nodes:
                    self._nodes[nid].update(state="released", shard=None)
            self._log.append(f"release: {', '.join(f.get('released', []))}")
        elif kind == "triage":
            self._log.append(f"triage: {f.get('unique_failures')} unique failure(s)")
        elif kind == "plan_gated_autofix":
            if f.get("allowed"):
                self._log.append(self._c(
                    f"plan gate OK  autofix on  ({', '.join(f.get('because') or [])})",
                    _GREEN))
            else:
                self._log.append(self._c(
                    f"plan gate  autofix OFF  plan={f.get('plan')}  "
                    f"(need edit_file|write_file)", _YELLOW))
        elif kind == "patch_truncated":
            rsn = f.get("reasoning_tokens")
            self._log.append(self._c(
                f"patch truncated  {f.get('test')}  "
                f"(max_tokens={f.get('max_tokens')}"
                + (f", reasoning={rsn}" if rsn else "") + ")", _YELLOW))
        elif kind == "slotfill_truncated":
            rsn = f.get("reasoning_tokens")
            self._log.append(self._c(
                f"slot-fill shard {f.get('shard')} cut at {f.get('max_tokens')} tokens"
                + (f" (reasoning={rsn})" if rsn else "") + " -> template", _YELLOW))
        elif kind == "model_unavailable":
            self._log.append(self._c(
                f"model unavailable  {f.get('model')}  "
                f"HTTP {f.get('status')}", _RED))
        elif kind == "fix_attempt":
            self._log.append(f"fix?  {f.get('test')}  "
                             + ("patch proposed" if f.get("has_patch") else "no patch"))
        elif kind == "fix_verified":
            self._log.append(self._c(f"fix OK  {f.get('test')}  (patched + re-tested green on {f.get('node')})", _GREEN))
        elif kind == "fix_rejected":
            self._log.append(self._c(f"fix KO  {f.get('test')}  (still red after patch)", _YELLOW))
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
            elif nd.get("probe_kind") == "cpu-fallback" or (
                    self._expect_cpu and not nd.get("probe_kind")):
                # Live film: a Token Factory sandbox has no GPU. Bars at 0 C
                # marked OK read as a healthy, idle H100 - say what it is.
                tag = f"shard#{shard}" if shard is not None else ""
                row = (f"  {name} {self._c('cpu sandbox', _YELLOW)}  "
                       f"no GPU telemetry - heal gated  {tag}")
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
