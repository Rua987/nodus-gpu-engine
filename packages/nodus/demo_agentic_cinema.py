#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NODUS demo — task → plan → tools → deliver (Cloud Storage) → Grafana Cloud.

Shows the whole Nodus pipeline end to end, deterministically:

  1. a natural-language task arrives (media & entertainment workflows included:
     the `media` task is a shoot-day brief — read the script, write the brief,
     deliver it to Google Cloud Storage)
  2. NODUS (the 324M local planner) turns it into an *ordered list of tool
     names* — the real model when `checkpoints/checkpoint_sft_plan_v5.pt` is
     present, a deterministic gold plan otherwise (the demo always runs)
  3. the harness fills the arguments and executes each tool (simulated, zero
     side effects) then verifies the result — and delivers the final artifact
     via `gcs_upload` (Google Cloud Storage, mock-first)
  4. every step is streamed to Grafana Cloud as annotations:
        task → plan → tool_call → tool_result → result

Telemetry is controlled by $NODUS_GRAFANA (see `nodus_grafana.py`):
    NODUS_GRAFANA=mock                 print the timeline (default, no token)
    NODUS_GRAFANA=jsonl:run.jsonl      mock + persist events to JSONL
    NODUS_GRAFANA=mcp                  push live annotations to Grafana Cloud
                                       (needs GRAFANA_URL + GRAFANA_SERVICE_ACCOUNT_TOKEN)
    NODUS_GRAFANA=off                  disable telemetry

GCS delivery is controlled by $NODUS_GCLOUD (see `nodus_gcloud.py`):
    NODUS_GCLOUD=mock                  deterministic gs:// URIs (default, no creds)
    NODUS_GCLOUD=real                  real upload (needs GCLOUD_BUCKET +
                                       GOOGLE_APPLICATION_CREDENTIALS)
    NODUS_GCLOUD=off                   disable delivery

Usage:
    python demo_agentic_cinema.py                 # default multi-step task
    python demo_agentic_cinema.py --list-tasks    # show the curated tasks
    python demo_agentic_cinema.py --task-key media # media workflow (shoot-day brief)
    python demo_agentic_cinema.py --task "Save a new file out.txt with a stub"
    python demo_agentic_cinema.py --contrast      # plan vs no-plan side by side
    python demo_agentic_cinema.py --no-nodus      # force the gold plan (skip real NODUS)
    python demo_agentic_cinema.py --live --model vertex:gemini-2.5-flash --task-key media
        # live: Vertex AI executor + real GCS + Grafana (see AGENTIC_CINEMA.md)
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Make the repo importable when run from any directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from nodus_grafana import GrafanaSink, sink_from_env  # noqa: E402
from nodus_backends import HACKATHON_DEFAULT_MODEL  # noqa: E402

_HERE = Path(__file__).resolve().parent

# ── Curated demo tasks ────────────────────────────────────────────────────
# `plan` is the ordered (tool_name, args) sequence the harness would execute —
# i.e. what NODUS is trained to output (the tool names) plus the args the
# harness fills. `workspace` is the synthetic repo the demo executes against.

DEMO_TASKS: Dict[str, dict] = {
    "inspect": {
        "task": "Read src/utils.py, then save a new file config_demo.yaml with a stub, then verify it exists.",
        "plan": [
            ("read_file", {"path": "src/utils.py"}),
            ("write_file", {"path": "config_demo.yaml", "content": "# demo stub config\nmode: default\n"}),
            ("bash", {"command": "ls config_demo.yaml"}),
        ],
        "workspace": {
            "src/main.py": "import utils\n\nif __name__ == '__main__':\n    print(utils.helper())\n",
            "src/utils.py": "def helper():\n    return 42\n",
            "config.yaml": "debug: true\n",
        },
        "note": "read → write → verify: the multi-step shape NODUS generalizes best on.",
    },
    "tune": {
        "task": "Find where 'debug' is configured, then update it to 'false'.",
        "plan": [
            ("grep", {"pattern": "debug", "path": "."}),
            ("edit_file", {"path": "config.yaml", "old": "debug: true", "new": "debug: false"}),
        ],
        "workspace": {"config.yaml": "debug: true\nport: 8080\n"},
        "note": "search then edit — the grep→edit signature NODUS learned to plan.",
    },
    "create": {
        "task": "Save a new file CHANGELOG_demo.md with a stub.",
        "plan": [
            ("write_file", {"path": "CHANGELOG_demo.md", "content": "# CHANGELOG\n\n- (stub)\n"}),
        ],
        "workspace": {},
        "note": "single-step create.",
    },
    "media": {
        "task": (
            "Read script.txt, then save a new file shoot_day_brief.md with the "
            "shoot-day brief, then upload it to Google Cloud Storage, then verify."
        ),
        "plan": [
            ("read_file", {"path": "script.txt"}),
            ("write_file", {
                "path": "shoot_day_brief.md",
                "content": (
                    "# Shoot-day brief — Scene 3\n\n"
                    "INT. EDIT BAY — DAY\n\n"
                    "- Set: edit bay, 4 monitors, one hero monitor\n"
                    "- Camera: ARRI ALEXA Mini LF · 35mm lens\n"
                    "- Call: 06:30 crew · 07:00 first setup · 11:00 wrap\n"
                    "- Deliverable: dailies → production/shoot_day_brief.md\n"
                ),
            }),
            ("gcs_upload", {
                "local_path": "shoot_day_brief.md",
                "destination": "production/shoot_day_brief.md",
                "bucket": "nodus-media-demo",
            }),
            ("bash", {"command": "ls shoot_day_brief.md"}),
        ],
        "workspace": {
            "script.txt": (
                "SCENE 3\n\n"
                "INT. EDIT BAY — DAY\n\n"
                "The editor pulls up the dailies on the hero monitor. "
                "Sound is rough, picture is clean. (CONTINUES)\n"
            ),
        },
        "note": "media workflow: read the script → write the shoot-day brief → "
                "deliver to Google Cloud Storage (harness capability) → verify.",
    },
}

_NAIVE_STEPS: List[Tuple[str, dict]] = [
    ("bash", {"command": "echo step1"}),
    ("bash", {"command": "echo step2"}),
    ("bash", {"command": "echo step3"}),
]


def _out(text: str) -> None:
    """Print that never crashes on a cp1252 Windows console (→ ✓ ∘ ↳ ●)."""
    s = str(text) + "\n"
    try:
        sys.stdout.write(s)
        sys.stdout.flush()
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        sys.stdout.buffer.write(s.encode(enc, "replace"))


def _force_utf8_stdout() -> None:
    """Best-effort: render the timeline glyphs on UTF-8 terminals (CI, video)."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass  # older Python or redirected stream — _out() still guards


_force_utf8_stdout()


# ── Real NODUS planner ────────────────────────────────────────────────────

def _real_nodus_plan(task: str) -> Optional[List[str]]:
    """Plan via the real 324M NODUS model — only when the checkpoint exists."""
    env_ckpt = os.environ.get("NODUS_PLAN_CKPT", "").strip()
    ckpt = Path(env_ckpt) if env_ckpt else _HERE / "checkpoints" / "checkpoint_sft_plan_v5.pt"
    if not ckpt.exists():
        return None  # no weights → deterministic gold fallback
    try:
        from nodus_plan_local import try_plan_tool_names

        return try_plan_tool_names(task, ckpt_path=str(ckpt))
    except Exception:
        return None


def _plan_device_label() -> str:
    """Device reel du planificateur local (auto → cuda si dispo, sinon cpu)."""
    try:
        from nodus_plan_local import resolve_plan_device

        return resolve_plan_device()
    except Exception:
        return "auto"


# ── Deterministic mock executor ───────────────────────────────────────────

def _glob_match(pattern: str, path: str) -> bool:
    return fnmatch.fnmatch(path, pattern)


def mock_execute(name: str, args: dict, ws: Dict[str, str]) -> Tuple[bool, str]:
    """Execute `name` against the synthetic workspace `ws`.

    Deterministic, side-effect free: this is the *harness* in miniature
    (fills args, executes, verifies). Returns (success, output_text).
    """
    if name == "read_file":
        p = args.get("path", "")
        if p in ws:
            return True, ws[p]
        return False, f"read_file: {p} not found"
    if name == "write_file":
        p = args.get("path", "out.txt")
        c = args.get("content", "")
        ws[p] = c
        return True, f"wrote {len(c)} bytes -> {p}"
    if name == "edit_file":
        p = args.get("path", "config.yaml")
        old, new = args.get("old"), args.get("new")
        if p not in ws:
            return False, f"edit_file: {p} not found"
        if old and old in ws[p]:
            ws[p] = ws[p].replace(old, new)
            return True, f"edited {p} (1 replacement)"
        return False, f"edit_file: pattern not found in {p}"
    if name == "glob":
        pat = args.get("pattern", "*")
        hits = [f for f in ws if _glob_match(pat, f)]
        if hits:
            return True, "\n".join(hits)
        return False, f"glob: no match for {pat}"
    if name == "grep":
        pat = args.get("pattern", "")
        path_filter = args.get("path", ".")
        hits = [
            f"{f}:{n}: {ln}"
            for f, content in ws.items()
            if path_filter in (".", f)
            for n, ln in enumerate(content.splitlines(), 1)
            if pat in ln
        ]
        if hits:
            return True, "\n".join(hits)
        return False, f"grep: no match for '{pat}'"
    if name == "bash":
        cmd = args.get("command", "echo done")
        if cmd.startswith("ls"):
            target = cmd.split()[-1] if len(cmd.split()) > 1 else "."
            if target in ws:
                return True, f"{target} exists"
            return True, "\n".join(sorted(ws)) if ws else "no files (empty workspace)"
        return True, f"[simulated] {cmd}"
    if name == "web_fetch":
        return True, f"[simulated] fetched {args.get('url', '')} (200, 12KB)"
    if name == "brave_search":
        return True, f"[simulated] 5 results for \"{args.get('query', '')}\""
    if name == "gcs_upload":
        # Livraison mock-first via le vrai module nodus_gcloud : l'artefact écrit
        # dans le workspace devient le contenu uploadé (URI gs:// déterministe).
        from nodus_gcloud import gcs_from_env

        lp = args.get("local_path") or ""
        content = args.get("content")
        if content is None and lp and lp in ws:
            content = ws[lp]
        with gcs_from_env() as client:
            ok, out = client.upload(
                local_path=lp or None,
                destination=args.get("destination", "production/artifact"),
                bucket=args.get("bucket"),
                content=content,
            )
        return ok, out
    return False, f"unknown tool {name}"


# ── Argument filling (the harness's job) ──────────────────────────────────

def _first_existing_path(task: str, ws: Dict[str, str], fallback: str) -> str:
    for token in re.findall(r"[A-Za-z0-9_./\\-]+\.[A-Za-z0-9]+", task):
        if token in ws:
            return token
    return fallback


def _first_new_path(task: str, ws: Dict[str, str], fallback: str) -> str:
    for token in re.findall(r"[A-Za-z0-9_./\\-]+\.[A-Za-z0-9]+", task):
        if token not in ws:
            return token
    return fallback


def _default_args(name: str, task: str, ws: Dict[str, str]) -> dict:
    """Fill deterministic args when NODUS only returned the tool *names*."""
    if name == "read_file":
        return {"path": _first_existing_path(task, ws, "src/main.py")}
    if name == "write_file":
        p = _first_new_path(task, ws, "output_demo.txt")
        # Le workflow media écrit le vrai shoot-day brief (même livrable que le
        # plan gold) — pas un stub générique.
        if "brief" in p or "brief" in task.lower():
            content = (
                "# Shoot-day brief — Scene 3\n\n"
                "INT. EDIT BAY — DAY\n\n"
                "- Set: edit bay, 4 monitors, one hero monitor\n"
                "- Camera: ARRI ALEXA Mini LF · 35mm lens\n"
                "- Call: 06:30 crew · 07:00 first setup · 11:00 wrap\n"
                "- Deliverable: dailies → production/shoot_day_brief.md\n"
            )
        else:
            content = "# stub generated by Nodus\n"
        return {"path": p, "content": content}
    if name == "edit_file":
        p = _first_existing_path(task, ws, "config.yaml")
        content = ws.get(p, "")
        if "debug" in content and "config" in p:
            return {"path": p, "old": "debug: true", "new": "debug: false"}
        lines = [ln for ln in content.splitlines() if ln.strip()]
        old = lines[0] if lines else "stub"
        return {"path": p, "old": old, "new": old + "  # edited by Nodus"}
    if name == "glob":
        return {"pattern": "*.py" if "py" in task.lower() else "*"}
    if name == "grep":
        q = "debug" if "debug" in task.lower() else "def"
        return {"pattern": q, "path": "."}
    if name == "bash":
        return {"command": "ls"}
    if name == "web_fetch":
        return {"url": "https://example.com/docs"}
    if name == "brave_search":
        q = task.replace("search", "").replace("internet", "").strip()[:60] or "agent"
        return {"query": q}
    if name == "gcs_upload":
        # Dépose l'artefact que l'étape write_file a produit (nom tiré de la tâche).
        lp = _first_new_path(task, ws, "shoot_day_brief.md")
        return {
            "local_path": lp,
            "destination": "production/" + lp,
            "bucket": "nodus-media-demo",
        }
    return {}


def _naive_steps() -> List[Tuple[str, dict]]:
    """The no-plan baseline: the executor ad-libs bash without a plan."""
    return [(n, dict(a)) for n, a in _NAIVE_STEPS]


def _make_answer(task: str, steps: List[Tuple[str, dict]], ws: Dict[str, str]) -> str:
    wrote = [a.get("path", "") for n, a in steps if n == "write_file" and a.get("path") in ws]
    edited = [a.get("path", "") for n, a in steps if n == "edit_file"]
    uploaded = [a.get("destination", "") for n, a in steps
                if n == "gcs_upload" and a.get("destination")]
    bits = []
    if wrote:
        bits.append(f"wrote {', '.join(wrote)}")
    if edited:
        bits.append(f"edited {', '.join(edited)}")
    if uploaded:
        bits.append(f"uploaded {', '.join(uploaded)}")
    if not bits and not any(n in ("write_file", "edit_file") for n, _ in steps):
        bits.append(f"{len(steps)} tool step(s) executed")
    return "Done: " + "; ".join(bits) + "." if bits else "Done."


# ── Run one plan through the sink ─────────────────────────────────────────

def run_plan(sink, task: str, steps: List[Tuple[str, dict]], ws: Dict[str, str], source: str) -> str:
    """Record task → plan → tool_call → tool_result → result in the sink.

    Returns the human-readable timeline (sink.summary()).
    """
    sink.record("task", task=task, model="nodus-324m", plan_source=source)
    names = [n for n, _ in steps]
    sink.record("plan", source=source, names=names, steps=len(names))
    for name, args in steps:
        sink.record("tool_call", name=name, args=json.dumps(args, ensure_ascii=False)[:400])
        ok, output = mock_execute(name, args, ws)
        sink.record("tool_result", name=name, success=ok, output=output[:300])
    answer = _make_answer(task, steps, ws)
    sink.record("result", answer=answer, tool_calls=len(steps), rounds=1, stopped_reason="done")
    return sink.summary()


def run_demo(
    sink,
    task_key: Optional[str] = None,
    task_text: Optional[str] = None,
    use_real_nodus: bool = True,
) -> dict:
    """Run a demo task. Returns {"task", "summary", "source", "workspace"}."""
    if task_key is None and task_text is None:
        task_key = "inspect"  # default: the multi-step demo task
    if task_key is not None:
        spec = DEMO_TASKS[task_key]
        task, ws = spec["task"], dict(spec["workspace"])
        steps, source = list(spec["plan"]), "demo-gold"
        if use_real_nodus:
            names = _real_nodus_plan(task)
            if names:
                steps = [(n, _default_args(n, task, ws)) for n in names]
                source = "nodus"
                # Le 324M garde son vocabulaire de 8 outils : pour le workflow
                # media, la LIVRAISON GCS est un capability tool du harnais —
                # on append l'étape gcs_upload après l'écriture de l'artefact.
                if task_key == "media" and "gcs_upload" not in names:
                    steps.append(("gcs_upload", _default_args("gcs_upload", task, ws)))
        return {
            "task": task,
            "summary": run_plan(sink, task, steps, ws, source),
            "source": source,
            "workspace": ws,
        }

    task = task_text or DEMO_TASKS["inspect"]["task"]
    ws: Dict[str, str] = {}
    steps, source = [], "none"
    if use_real_nodus:
        names = _real_nodus_plan(task)
        if names:
            steps = [(n, _default_args(n, task, ws)) for n in names]
            source = "nodus"
    if not steps:
        steps, source = _naive_steps(), "naive"
    return {
        "task": task,
        "summary": run_plan(sink, task, steps, ws, source),
        "source": source,
        "workspace": ws,
    }


def run_contrast(task_key: str = "inspect") -> Tuple[str, str, str]:
    """Plan vs no-plan, side by side, on the same task."""
    spec = DEMO_TASKS[task_key]
    task = spec["task"]
    with GrafanaSink(mode="mock") as plan_sink:
        plan_summary = run_plan(plan_sink, task, list(spec["plan"]), dict(spec["workspace"]), "nodus")
    with GrafanaSink(mode="mock") as naive_sink:
        naive_summary = run_plan(naive_sink, task, _naive_steps(), {}, "naive")
    return task, plan_summary, naive_summary


# ── CLI ───────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Nodus demo: task -> plan -> tools -> Grafana Cloud.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--list-tasks", action="store_true", help="list the curated demo tasks")
    ap.add_argument("--task-key", choices=list(DEMO_TASKS), default=None, help="run a curated demo task")
    ap.add_argument("--task", default=None, help="custom task text (NODUS plans it when the checkpoint is present)")
    ap.add_argument("--no-nodus", action="store_true", help="force the deterministic gold plan (skip real NODUS)")
    ap.add_argument("--contrast", action="store_true", help="show plan vs no-plan side by side")
    ap.add_argument("--live", action="store_true", help="run Vertex/Gemini executor end to end (see AGENTIC_CINEMA.md)")
    ap.add_argument(
        "--model", "-m",
        default=None,
        help=f"Executor model (default with --live: {HACKATHON_DEFAULT_MODEL})",
    )
    ap.add_argument(
        "--text-tools",
        action="store_true",
        help="With --live: JSON-text tools for models without native function calling",
    )
    args = ap.parse_args()

    if args.list_tasks:
        for k, spec in DEMO_TASKS.items():
            _out(f"[{k}] {spec['task']}")
            _out(f"       plan: {[n for n, _ in spec['plan']]}  - {spec['note']}")
        return 0

    if args.live:
        os.environ.setdefault("NODUS_HACKATHON", "1")
        if not args.model:
            args.model = HACKATHON_DEFAULT_MODEL
        spec = DEMO_TASKS.get(args.task_key) if args.task_key else None
        task = spec["task"] if spec else (args.task or DEMO_TASKS["inspect"]["task"])
        names = [n for n, _ in spec["plan"]] if spec else None
        try:
            from nodus_agent import run_agent
        except ImportError as exc:  # pragma: no cover
            _out(f"--live requires nodus_agent.py: {exc}")
            return 1
        # In --live the executor is real (real filesystem): materialize the
        # task workspace (e.g. script.txt) in a temp dir passed as cwd — script
        # read → artifact written → gcs_upload anchored there, and the repo is
        # never polluted (the dir is removed afterwards).
        ws_dir = None
        if spec and spec.get("workspace"):
            import shutil
            import tempfile
            ws_dir = tempfile.mkdtemp(prefix="nodus_ws_")
            for fname, content in spec["workspace"].items():
                with open(os.path.join(ws_dir, fname), "w", encoding="utf-8") as fh:
                    fh.write(content)
        try:
            with sink_from_env() as sink:
                kwargs = {
                    "plan": True,
                    "plan_source": "nodus",
                    "plan_names": names,
                    "telemetry": sink,
                    "model": args.model,
                }
                if args.text_tools:
                    kwargs["text_tools"] = True
                if ws_dir:
                    kwargs["cwd"] = ws_dir
                res = run_agent(task, **kwargs)
        finally:
            if ws_dir:
                shutil.rmtree(ws_dir, ignore_errors=True)
        _out(f"answer: {res.answer}")
        _out("")
        _out(sink.summary())
        if sink.mode == "mcp":
            n_ok = getattr(sink, "pushed", len(sink.events))
            _out(f"[grafana] pushed {n_ok}/{len(sink.events)} annotations (tags: nodus, agentic-cinema)")
            if getattr(sink, "errors", None):
                _out(f"[grafana] {len(sink.errors)} push error(s): {sink.errors[0][:90]}")
        else:
            _out("telemetry: mock mode — run with NODUS_GRAFANA=mcp (plus GRAFANA_URL and")
            _out("  GRAFANA_SERVICE_ACCOUNT_TOKEN) to push live annotations to Grafana Cloud")
        return 0

    sink = sink_from_env()
    try:
        if args.contrast:
            task, plan_summary, naive_summary = run_contrast(args.task_key or "inspect")
            _out(f"task: {task}")
            _out("")
            _out("-- WITH NODUS PLAN --")
            _out(plan_summary)
            _out("")
            _out("-- NO PLAN (ad-hoc bash) --")
            _out(naive_summary)
            _out("")
            _out("-> NODUS plans the ordered tool names; the ad-hoc path flails without creating the file.")
            return 0
        with sink:
            meta = run_demo(
                sink,
                task_key=args.task_key,
                task_text=args.task,
                use_real_nodus=not args.no_nodus,
            )
        _out(meta["summary"])
        _out("")
        if meta["source"] == "nodus":
            _out(f"plan source: real NODUS 324M (local planner, device={_plan_device_label()})")
        elif meta["source"] == "demo-gold":
            _out("plan source: deterministic gold plan (add checkpoints/checkpoint_sft_plan_v5.pt for the real 324M planner)")
        else:
            _out("plan source: none (ad-hoc bash) — set NODUS_PLAN_CKPT or use --task-key for a real plan")
        if sink.mode == "mcp":
            n_ok = getattr(sink, "pushed", len(sink.events))
            _out(f"[grafana] pushed {n_ok}/{len(sink.events)} annotations (tags: nodus, agentic-cinema)")
            if getattr(sink, "errors", None):
                _out(f"[grafana] {len(sink.errors)} push error(s): {sink.errors[0][:90]}")
        else:
            _out("telemetry: mock mode — run with NODUS_GRAFANA=mcp (plus GRAFANA_URL and")
            _out("  GRAFANA_SERVICE_ACCOUNT_TOKEN) to push live annotations to Grafana Cloud")
    finally:
        sink.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
