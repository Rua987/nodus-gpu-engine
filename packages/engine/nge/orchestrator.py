"""NgeOrchestrator - the runtime that turns a scenario into a fleet run.

Flow (deterministic infra frame around the Nodus plan):

    plan(task)                      # Nodus 324M -> ordered tool names
    gpu_provision(n = shards)       # stand up the Nebius GPU fleet
    for each shard:
        run_in_sandbox(cmd)        # Token Factory sandbox on a pinned node
        gpu_status(node)           # telemetry -> event annotations
    triage(shard outputs)          # consolidate failures + proposed fixes
    gpu_release()                  # stop billing
    write <out>/report_<ts>.md     # the delivered artifact

``chat_fn`` (optional) is the Nemotron slot-fill hook:
``chat_fn(messages, model, tools) -> assistant message dict`` (Ollama-style).
When absent (mock / CI) a deterministic command template is used instead.
"""
from __future__ import annotations

import json
import re
import shlex
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from nge import config as _cfg
from nge import llm_text
from nge.tools import handlers

# packages/engine/nge/orchestrator.py -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]

# A pytest node id, minus every shell metacharacter. `kw` is derived from this
# and interpolated into a sandbox command, so a stdout line reading
# `FAILED t.py::test_a;whoami - x` must not parse at all rather than smuggle a
# second command through (shlex.quote is the other half of that belt).
_TEST_ID = r"[^\s;&|`$(){}<>'\"\\]+"
_FAILED_RE = re.compile(rf"^FAILED\s+({_TEST_ID})\s+-\s+(.*)$", re.M)
# files a unified diff touches: "--- a/path" / "+++ b/path"
_PATCH_FILE_RE = re.compile(r"^(?:---|\+\+\+)\s+[ab]/(\S+)", re.M)

_FIX_HINTS = [
    ("not unique", "Make `old_string` unique or pass replace_all=True."),
    ("out of order", "Sort plan names to match executor step order before asserting."),
    ("KeyError", "Guard the missing env var with a default / skip when unset."),
    ("expected [None", "carry_previous_path_targets: propagate the read target to the edit step."),
    ("memory entry missing", "Flush the memory append before asserting the round-trip."),
]


def _proposed_fix(msg: str) -> str:
    for needle, hint in _FIX_HINTS:
        if needle in msg:
            return hint
    return "Reproduce locally, bisect the last change touching this module."


@dataclass
class ShardResult:
    index: int
    node_id: str
    command: str
    exit_code: int
    duration_s: float
    failures: List[dict] = field(default_factory=list)
    migrated_from: Optional[str] = None


@dataclass
class RunReport:
    ok: bool
    artifact_path: Optional[str]
    plan_names: List[str]
    plan_source: str
    shards: List[ShardResult]
    failures: List[dict]
    events: List[dict]
    html_path: Optional[str] = None
    routes: List[dict] = field(default_factory=list)
    remediations: List[dict] = field(default_factory=list)
    fixes: List[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok, "artifact_path": self.artifact_path,
            "html_path": self.html_path,
            "plan": {"names": self.plan_names, "source": self.plan_source},
            "shards": [s.__dict__ for s in self.shards],
            "failures": self.failures,
            "routes": self.routes,
            "remediations": self.remediations,
            "fixes": self.fixes,
            "events": self.events,
        }


class NgeOrchestrator:
    # trigger a remediation when a node throttles or drops below this efficiency
    MIN_EFFICIENCY = 0.25
    # how many distinct failures the code agent tries to auto-fix per run
    MAX_FIXES = 3

    def __init__(self, config: Optional[_cfg.Config] = None,
                 chat_fn: Optional[Callable] = None, telemetry=None) -> None:
        self.config = config or _cfg.load()
        self.chat_fn = chat_fn
        self.telemetry = telemetry          # duck-typed: record(kind, **fields)
        self.events: List[dict] = []
        self.routes: List[dict] = []
        self.remediations: List[dict] = []
        self.fixes: List[dict] = []

    # -- event log ---------------------------------------------------------
    def _emit(self, kind: str, **fields) -> None:
        evt = {"t": round(time.time(), 3), "kind": kind, **fields}
        self.events.append(evt)
        if self.telemetry is not None:
            try:
                self.telemetry.record(kind, **fields)
            except Exception:
                pass

    # -- slot-fill -------------------------------------------------------
    # -- model routing -------------------------------------------------
    def _route(self, decision: str) -> str:
        """Pick the Nemotron tier for a decision and log it. Returns model id."""
        from nge import router
        rec = router.route(decision, self.config)
        self.routes.append(rec)
        self._emit("model_route", **rec)
        return rec["model"]

    # -- slot-fill -------------------------------------------------------
    def _shard_command(self, task: str, plan_names: List[str], target: str,
                       index: int, shards: int) -> str:
        base = f"python -m pytest {target} -q -p no:cacheprovider"
        model = self._route("slotfill")
        if self.chat_fn is None:
            return f"NGE_SHARD={index}/{shards} {base}"
        prompt = (
            "Fill ONE shell command for this shard of a distributed test run.\n"
            f"Task: {task}\nPlan: {plan_names}\n"
            f"Shard {index} of {shards}. Target path: {target}\n"
            "Reply with ONLY the command."
        )
        fallback = f"NGE_SHARD={index}/{shards} {base}"
        try:
            msg = self.chat_fn([{"role": "user", "content": prompt}], model, None)
        except Exception as exc:                     # a flaky model must not
            self._emit("slotfill_error", shard=index,   # take the run down
                       error=f"{type(exc).__name__}: {exc}")
            return fallback
        cmd = llm_text.first_command(msg)
        if not cmd:
            self._emit("slotfill_empty", shard=index)
            return fallback
        return cmd

    # -- feedback loop : agents self-manage their GPU compute ----------
    def _react_to_pressure(self, sr: "ShardResult", tele: Optional[dict],
                           target: str, collect: list,
                           gpu_type: str = "H100") -> None:
        """If the shard's node is throttling / inefficient, migrate the shard
        onto a freshly provisioned healthy node. Bounded to one remediation
        per shard.

        ``tele`` is the telemetry reading already taken by the run loop for this
        node - reused verbatim so the pressure event, the remediation record and
        the report all quote the exact same numbers (no second poll).
        """
        if sr.migrated_from is not None or not tele:
            return
        pressured = (tele["health"] == "throttle"
                     or tele["efficiency"] < self.MIN_EFFICIENCY)
        if not pressured:
            return

        self._route("healthcheck")   # telemetry reasoning -> Nano tier
        self._emit("gpu_pressure", shard=sr.index, node_id=sr.node_id,
                   health=tele["health"], efficiency=tele["efficiency"],
                   temp_c=tele["temp_c"], power_w=tele["power_w"])

        repl = handlers.gpu_provision(n=1, gpu_type=gpu_type)["nodes"][-1]["id"]
        self._emit("gpu_provision_replacement", node_id=repl, for_shard=sr.index)
        handlers.gpu_allocate(job=f"shard-{sr.index}-retry")
        res = handlers.run_in_sandbox(command=sr.command, node_id=repl,
                                      collect=collect, timeout=180)
        old_node = sr.node_id
        sr.migrated_from = old_node
        sr.node_id = repl
        sr.exit_code = res["exit_code"]
        sr.duration_s = res["duration_s"]
        sr.failures = [{"test": m.group(1), "error": m.group(2)}
                       for m in _FAILED_RE.finditer(res["stdout"])]
        rec = {"shard": sr.index, "from": old_node, "to": repl,
               "reason": tele["health"], "efficiency": tele["efficiency"],
               "temp_c": tele["temp_c"], "power_w": tele["power_w"]}
        self.remediations.append(rec)
        self._emit("gpu_remediation", **rec)

        # telemetry of the replacement (so a watcher sees it running healthy)
        rst = handlers.gpu_status(node_id=repl)["nodes"]
        self._emit("gpu_status", node_id=repl, telemetry=rst[0] if rst else None)
        handlers.gpu_release(node_ids=[old_node])

    # -- main -----------------------------------------------------------
    def run(self, scenario: dict) -> RunReport:
        task = scenario["task"]
        shards = int(scenario.get("shards", 1))
        gpu_type = scenario.get("gpu_type", "H100")
        target = scenario.get("target", "packages/nodus/tests")
        collect = scenario.get("collect", [])

        handlers.reset_state(self.config)
        self.events.clear()
        self.routes.clear()
        self.remediations.clear()
        self.fixes.clear()
        self._emit("run_start", task=task, shards=shards, gpu_type=gpu_type,
                   fleet_mode=self.config.fleet_mode, sandbox_mode=self.config.sandbox_mode,
                   jail=self.config.jail)

        # 1) plan (Nodus brain) - high-level reasoning routes to Ultra
        self._route("plan")
        from nge import planner
        pr = planner.plan(task)
        self._emit("plan", names=pr.names, source=pr.source, note=pr.note)

        # 2) provision fleet
        prov = handlers.gpu_provision(n=shards, gpu_type=gpu_type)
        node_ids = [n["id"] for n in prov["nodes"]]
        self._emit("gpu_provision", **prov)

        shard_results: List[ShardResult] = []
        failures: List[dict] = []
        fixes: List[dict] = []
        try:
            self._fan_out_and_fix(scenario, pr, node_ids, shard_results,
                                  failures, fixes)
        except BaseException as exc:                    # incl. KeyboardInterrupt
            self._emit("run_error", error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            # Release the fleet no matter what. A crash anywhere above would
            # otherwise leave live GPU nodes allocated - and billing.
            rel = handlers.gpu_release()
            self._emit("gpu_release", **rel)

        # deliver artifact
        artifact = self._write_report(task, pr, shard_results, failures, fixes)
        self._emit("artifact", path=str(artifact))
        self._emit("run_end", ok=True)

        return RunReport(
            ok=True, artifact_path=str(artifact),
            html_path=str(self._html_path) if getattr(self, "_html_path", None) else None,
            plan_names=pr.names, plan_source=pr.source,
            shards=shard_results, failures=failures, events=list(self.events),
            routes=list(self.routes), remediations=list(self.remediations),
            fixes=list(self.fixes),
        )

    def _fan_out_and_fix(self, scenario: dict, pr, node_ids: List[str],
                         shard_results: List["ShardResult"],
                         failures: List[dict], fixes: List[dict]) -> None:
        """Shards -> triage -> auto-fix. Results are appended in place so the
        caller can still write a report if this raises."""
        task = scenario["task"]
        shards = int(scenario.get("shards", 1))
        gpu_type = scenario.get("gpu_type", "H100")
        target = scenario.get("target", "packages/nodus/tests")
        collect = scenario.get("collect", [])
        # mission intents - default on, an engineer can turn either off
        self_heal = bool(scenario.get("self_heal", True))
        auto_fix = bool(scenario.get("auto_fix", True))

        # 3) fan out
        for i, node_id in enumerate(node_ids):
            handlers.gpu_allocate(job=f"shard-{i}")
            cmd = self._shard_command(task, pr.names, target, i, shards)
            self._emit("shard_start", index=i, node_id=node_id, command=cmd)
            res = handlers.run_in_sandbox(command=cmd, node_id=node_id,
                                          collect=collect, timeout=180)
            fails = [{"test": m.group(1), "error": m.group(2)}
                     for m in _FAILED_RE.finditer(res["stdout"])]
            shard_results.append(ShardResult(
                index=i, node_id=node_id, command=cmd,
                exit_code=res["exit_code"], duration_s=res["duration_s"], failures=fails,
            ))
            st = handlers.gpu_status(node_id=node_id)["nodes"]
            tele = st[0] if st else None
            self._emit("gpu_status", node_id=node_id, telemetry=tele)

            # feedback loop: react if this node is throttling / inefficient
            # (same telemetry reading - no second poll)
            if self_heal:
                self._react_to_pressure(shard_results[-1], tele, target,
                                        collect, gpu_type)

            sr = shard_results[-1]
            self._emit("shard_done", index=i, node_id=sr.node_id,
                       migrated_from=sr.migrated_from,
                       exit_code=sr.exit_code, failures=len(sr.failures))

        # 4) triage (consolidate + dedupe)
        seen = set()
        for sr in shard_results:
            for f in sr.failures:
                if f["test"] in seen:
                    continue
                seen.add(f["test"])
                failures.append({**f, "shard": sr.index, "node": sr.node_id,
                                 "proposed_fix": _proposed_fix(f["error"])})
        self._emit("triage", unique_failures=len(failures))

        # 5) code agent: propose a patch per failure, apply + re-test in a
        #    fresh sandbox, keep only the verified ones
        if auto_fix:
            fixes.extend(self._attempt_fixes(failures, target, gpu_type))
        else:
            self._emit("autofix_skipped", reason="disabled by mission",
                       would_have_tried=min(len(failures), self.MAX_FIXES))

    # -- code agent : propose fix -> apply + re-test in a fresh sandbox ----
    def _propose_patch(self, failure: dict, model: str) -> Optional[str]:
        """Return a unified diff that should fix ``failure``.

        ``--mock``: the canned patch from the fixture catalogue.
        ``--local`` / ``--live``: ask the model (Nemotron Super tier) for a diff.
        """
        if self.chat_fn is None:
            from nge import _fixtures
            return _fixtures.canned_patch(failure["test"])

        prompt = (
            "A test is failing. Reply with ONLY a unified diff (```diff fenced) "
            "that fixes it - no prose.\n"
            f"Test: {failure['test']}\nError: {failure['error']}\n"
        )
        try:
            msg = self.chat_fn([{"role": "user", "content": prompt}], model, None)
        except Exception as exc:
            self._emit("patch_error", test=failure.get("test"),
                       error=f"{type(exc).__name__}: {exc}")
            return None
        return llm_text.unified_diff(msg)

    def _sources_for_patch(self, patch: str) -> Dict[str, str]:
        """Read the repo files a patch touches, so ``git apply`` has something
        to apply to *inside* the sandbox.

        Without this the sandbox holds only ``fix.patch`` and the verification
        can never succeed against a real Token Factory sandbox. Paths are
        resolved and confined to the repo - the patch is model-written, so
        ``--- a/../../etc/passwd`` must not read outside the tree.
        """
        out: Dict[str, str] = {}
        for m in _PATCH_FILE_RE.finditer(patch or ""):
            rel = m.group(1)
            if rel in ("/dev/null", "dev/null") or rel in out:
                continue
            try:
                p = (_REPO_ROOT / rel).resolve()
                p.relative_to(_REPO_ROOT)          # refuse path escape
                if p.is_file():
                    out[rel] = p.read_text(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                continue
        return out

    def _attempt_fixes(self, failures: List[dict], target: str,
                       gpu_type: str = "H100") -> List[dict]:
        fixes: List[dict] = []
        for f in failures[: self.MAX_FIXES]:
            model = self._route("triage")          # slot-fill / triage -> Super
            patch = self._propose_patch(f, model)
            self._emit("fix_attempt", test=f["test"], has_patch=bool(patch))
            if not patch:
                fixes.append({"test": f["test"], "verified": False,
                              "patch": None, "reason": "no patch proposed"})
                continue

            node = handlers.gpu_provision(n=1, gpu_type=gpu_type)["nodes"][-1]["id"]
            handlers.gpu_allocate(job=f"fix-{f['test'].split('::')[-1]}")
            kw = f["test"].split("::")[-1]
            # ship the touched sources next to the patch, and make the sandbox a
            # git work tree so `git apply` has a repo to act on
            files = {"fix.patch": patch}
            sources = self._sources_for_patch(patch)
            files.update(sources)
            self._emit("fix_sources", test=f["test"], files=sorted(sources))
            res = handlers.run_in_sandbox(
                command=("git init -q && git add -A && git apply fix.patch"
                         f" && python -m pytest {shlex.quote(target)}"
                         f" -q -k {shlex.quote(kw)}"),
                node_id=node, files=files, timeout=120,
            )
            verified = res["exit_code"] == 0 and not res.get("blocked")
            self._emit("fix_verified" if verified else "fix_rejected",
                       test=f["test"], node=node)
            fixes.append({"test": f["test"], "patch": patch, "verified": verified,
                          "node": node, "stdout": res["stdout"]})
            handlers.gpu_release(node_ids=[node])
        self.fixes = fixes
        return fixes

    # -- artifact -------------------------------------------------------
    def _write_report(self, task, pr, shard_results, failures, fixes=None) -> Path:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = self.config.out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"report_{ts}.md"

        lines = [
            f"# Fleet test triage - {ts}",
            "",
            f"**Task:** {task}",
            "",
            f"- Plan ({pr.source}): `{pr.names}`",
            f"- Fleet mode: `{self.config.fleet_mode}` | Sandbox: `{self.config.sandbox_mode}`",
            f"- Shards: {len(shard_results)} | Unique failures: {len(failures)}"
            f" | Auto-fixed: {len([x for x in (fixes or []) if x.get('verified')])}",
            "",
            "## Shards",
            "",
            "| # | node | exit | dur (s) | failures |",
            "|---|------|------|---------|----------|",
        ]
        for sr in shard_results:
            node = f"`{sr.node_id}`"
            if sr.migrated_from:
                node += f" _(migrated from `{sr.migrated_from}`)_"
            lines.append(f"| {sr.index} | {node} | {sr.exit_code} | "
                         f"{sr.duration_s} | {len(sr.failures)} |")

        lines += ["", "## Self-managed compute", ""]
        seen_tiers = {}
        for r in self.routes:
            seen_tiers.setdefault(r["tier"], set()).add(r["decision"])
        lines.append("**Model routing (Nemotron tiers):**")
        lines.append("")
        for tier in ("ultra", "super", "nano"):
            if tier in seen_tiers:
                lines.append(f"- `{tier}` → {', '.join(sorted(seen_tiers[tier]))}")
        lines += ["", "**GPU pressure remediations:**", ""]
        if not self.remediations:
            lines.append("_None — every node stayed within thermal / efficiency budget._")
        for rm in self.remediations:
            lines.append(
                f"- shard {rm['shard']}: `{rm['from']}` {rm['reason']} "
                f"(temp {rm.get('temp_c')}°C, {rm['power_w']} W, eff {rm['efficiency']}) "
                f"→ re-provisioned + migrated to `{rm['to']}`")

        # -- auto-fixes ------------------------------------------------------
        fixes = fixes or []
        verified = [x for x in fixes if x.get("verified")]
        lines += ["", "## Auto-fixes (code agent)", "",
                  f"Attempted {len(fixes)} / {len(failures)} failure(s) · "
                  f"**{len(verified)} patched & re-tested green** in a fresh sandbox.", ""]
        if fixes:
            lines += ["| test | patch | verified |", "|---|---|---|"]
            fix_dir = out_dir / "fixes"
            for x in fixes:
                pf = "-"
                if x.get("patch"):
                    fix_dir.mkdir(parents=True, exist_ok=True)
                    fn = x["test"].split("::")[-1] + ".patch"
                    (fix_dir / fn).write_text(x["patch"], encoding="utf-8")
                    pf = f"`fixes/{fn}`"
                mark = "✅" if x.get("verified") else ("—" if not x.get("patch") else "❌ still red")
                lines.append(f"| `{x['test']}` | {pf} | {mark} |")

        lines += ["", "## Consolidated failures", ""]
        if not failures:
            lines.append("_No failures._")
        for f in failures:
            fx = next((x for x in fixes if x["test"] == f["test"]), None)
            status = ("auto-fixed & verified" if fx and fx.get("verified")
                      else "patch rejected" if fx and fx.get("patch")
                      else "needs a human")
            lines += [
                f"### `{f['test']}`",
                f"- Error: `{f['error']}`",
                f"- Seen on: shard {f['shard']} / node `{f['node']}`",
                f"- Heuristic hint: {f['proposed_fix']}",
                f"- Agent outcome: **{status}**",
                "",
            ]
        lines += ["## Event log", "", "```json",
                  json.dumps(self.events, indent=2, ensure_ascii=False), "```", ""]
        path.write_text("\n".join(lines), encoding="utf-8")

        # sibling self-contained HTML (screenshotable)
        try:
            from nge import report_html
            self._html_path = report_html.render({
                "plan": {"names": pr.names, "source": pr.source},
                "shards": [s.__dict__ for s in shard_results],
                "failures": failures, "routes": self.routes,
                "remediations": self.remediations, "fixes": fixes or [],
                "events": self.events,
            }, path.with_suffix(".html"))
        except Exception:
            self._html_path = None
        return path
