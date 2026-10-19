"""Real bugs, step 1: the fix loop on SWE-bench Verified tasks, test-guided.

Per task, three Token Factory sandboxes on the task's own image (one command
each - a ContreeSDK run is disposable), and two Nemotron calls:

  1. sandbox: add the task's tests, run the *visible* FAIL_TO_PASS tests,
     list the repository's source files;
  2. model (typed by a strict json_schema, enforced by Token Factory): from the
     issue, the failing output and the file list, pick up to 3 files to read;
  3. sandbox: print those files, numbered;
  4. model (reasoning on, the patch settings of the engine): write the diff,
     from the issue, the failing output and the exact numbered text;
  5. sandbox: add the tests, apply the diff (``git apply``, then with
     ``--ignore-whitespace``), run every test file the task touches.

Resolved = every FAIL_TO_PASS test passes and every PASS_TO_PASS test still
passes - the task's own criterion. Where a task has two or more FAIL_TO_PASS
tests, half are never shown to the model: they are the held-out check.

This is test-guided repair, easier than standard SWE-bench (the model sees the
failing tests): the number is not a SWE-bench score. See docs/REAL_BUGS.md.

    python -m bench.swebench_runner --i-know-cost --instances pallets__flask-5014
    python -m bench.swebench_runner --i-know-cost --repos psf/requests,pallets/flask --limit 5
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from bench.swebench_probe import DATASET, PY, image_for, outcomes, test_files

MAX_FILES = 3
FILE_LIST_CAP = 600
EXCERPT_LINES = 400          # a file this short is shown whole
SPAN = 60                    # otherwise this many lines around each line of interest
ISSUE_CAP = 6000
OUTPUT_CAP = 6000
PICK_SCHEMA = {
    "type": "object",
    "properties": {"files": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_FILES}},
    "required": ["files"],
    "additionalProperties": False,
}


# -- task data -----------------------------------------------------------------

def load_tasks(instances: Optional[List[str]] = None, repos: Optional[List[str]] = None,
               limit: int = 0, cache: Optional[Path] = None) -> List[dict]:
    import urllib.request
    rows: List[dict] = []
    if cache and cache.is_file():
        rows = json.loads(cache.read_text(encoding="utf-8"))
    else:
        off = 0
        while True:
            with urllib.request.urlopen(f"{DATASET}&offset={off}&length=100", timeout=60) as r:
                d = json.load(r)
            rows += [x["row"] for x in d["rows"]]
            off += 100
            if off >= d.get("num_rows_total", 0):
                break
        if cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(rows), encoding="utf-8")
    if instances:
        want = set(instances)
        rows = [r for r in rows if r["instance_id"] in want]
    if repos:
        rows = [r for r in rows if r["repo"] in set(repos)]
    rows.sort(key=lambda r: r["instance_id"])
    return rows[:limit] if limit else rows


def split_f2p(f2p: List[str]) -> Tuple[List[str], List[str]]:
    """(visible, hidden): with two or more FAIL_TO_PASS tests, the second half
    is never shown to the model."""
    if len(f2p) < 2:
        return list(f2p), []
    k = (len(f2p) + 1) // 2
    return list(f2p[:k]), list(f2p[k:])


# -- sandbox commands (one command per sandbox) -----------------------------------

def _mark(name: str) -> str:
    return f"echo ===NGE:{name} exit=$?==="


def sections(out: str) -> Dict[str, Tuple[str, int]]:
    parts = re.split(r"^===NGE:([\w./:-]+) exit=(\d+)===$", out or "", flags=re.M)
    return {parts[i + 1]: (parts[i], int(parts[i + 2])) for i in range(0, len(parts) - 2, 3)}


def baseline_cmd(visible: List[str]) -> str:
    tests = " ".join(_q(t) for t in visible)
    return " ; ".join([
        "cd /testbed", "git apply /tmp/test.patch", _mark("test_patch"),
        f"{PY} -m pytest -rA --tb=short -p no:cacheprovider {tests}", _mark("visible"),
        f"git ls-files '*.py' | grep -v -E '(^|/)(tests?|testing|docs?)/' | head -{FILE_LIST_CAP}",
        _mark("files"),
    ])


def cat_cmd(paths: List[str]) -> str:
    cmds = ["cd /testbed"]
    for p in paths:
        cmds += [f"cat {_q(p)}", _mark(f"file:{p}")]
    return " ; ".join(cmds)


def verify_cmd(files: List[str]) -> str:
    tests = " ".join(_q(f) for f in files)
    return " ; ".join([
        "cd /testbed", "git apply /tmp/test.patch", _mark("test_patch"),
        "(git apply --recount /tmp/model.patch && echo NGE_APPLIED:strict) || "
        "(git apply --recount --ignore-whitespace /tmp/model.patch && echo NGE_APPLIED:whitespace)",
        _mark("model_patch"),
        f"{PY} -m pytest -rA --tb=short -p no:cacheprovider {tests}", _mark("verify"),
    ])


def _q(s: str) -> str:
    import shlex
    return shlex.quote(s)


# -- what the model is shown --------------------------------------------------------

def excerpt(path: str, text: str, lines_of_interest: List[int]) -> str:
    lines = text.splitlines()
    if len(lines) <= EXCERPT_LINES or not lines_of_interest:
        lo_hi = [(0, min(len(lines), EXCERPT_LINES))]
    else:
        lo_hi = sorted((max(0, n - SPAN), min(len(lines), n + SPAN)) for n in lines_of_interest)
    parts = []
    for lo, hi in lo_hi:
        body = "\n".join(f"{i + 1:5d}| {lines[i]}" for i in range(lo, hi))
        parts.append(f"{path} (lines {lo + 1}-{hi} of {len(lines)}), exact text:\n{body}")
    return "\n\n".join(parts)


def lines_in_output(path: str, output: str) -> List[int]:
    return sorted({int(n) for n in re.findall(rf"{re.escape(path)}:(\d+)", output or "")})


def pick_prompt(task: dict, failing: str, files: List[str]) -> str:
    return (
        "A bug report and the output of its failing tests are below. Choose up to "
        f"{MAX_FILES} source files you need to read to fix it, from the list given.\n\n"
        f"Issue:\n{task['problem_statement'][:ISSUE_CAP]}\n\n"
        f"Failing tests output:\n{failing[-OUTPUT_CAP:]}\n\n"
        "Source files:\n" + "\n".join(files))


def patch_prompt(task: dict, failing: str, shown: str) -> str:
    return (
        "Fix the bug below. Reply with ONLY a unified diff (```diff fenced) - no prose.\n"
        "Paths are repo-relative (a/<path>, b/<path>). Every context line must be copied "
        "VERBATIM from the numbered source shown (without the number and the '| '), keeping "
        "its exact indentation; do not patch code that is not shown. Do not edit tests.\n\n"
        f"Issue:\n{task['problem_statement'][:ISSUE_CAP]}\n\n"
        f"Failing tests output:\n{failing[-OUTPUT_CAP:]}\n\n{shown}")


# -- aligning a diff to the real file ------------------------------------------------

_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$")


def align_to_source(patch: str, sources: Dict[str, str]) -> Tuple[str, List[str]]:
    """Rewrite each hunk's context and removed lines with the file's exact text.

    Seen in the archive (an engine run, 2026-10-18; flask-5014 here): the model
    retypes context lines with the wrong indentation and a wrong ``@@`` line,
    while the lines it ADDS are indented right. So: find the hunk's old lines
    in the file ignoring whitespace, replace them with the file's own lines,
    fix the start line, and leave every ``+`` line exactly as written. A hunk
    whose old lines are nowhere in the file is left as is.
    Returns (patch, notes).
    """
    lines, out, notes = patch.splitlines(), [], []
    src: Optional[List[str]] = None
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = re.match(r"^\+\+\+ b/(\S+)", ln)
        if m:
            text = sources.get(m.group(1))
            src = text.splitlines() if text is not None else None
            out.append(ln)
            i += 1
            continue
        hm = _HUNK.match(ln)
        if not hm or src is None:
            out.append(ln)
            i += 1
            continue
        body, j = [], i + 1
        while j < len(lines) and (lines[j][:1] in (" ", "-", "+", "\\") or lines[j] == ""):
            if lines[j] == "" and (j + 1 >= len(lines) or lines[j + 1][:1] not in (" ", "-", "+")):
                break
            body.append(lines[j] or " ")
            j += 1
        want = [b[1:].strip() for b in body if b[:1] in (" ", "-")]
        found = None
        for k in (range(len(src) - len(want) + 1) if want else ()):
            if all(src[k + t].strip() == want[t] for t in range(len(want))):
                found = k
                break
        if found is None:
            notes.append(f"hunk at line {hm.group(1)} not found in the file")
            out.append(ln)
            out.extend(body)
            i = j
            continue
        new, t = [], 0
        for b in body:
            if b[:1] in (" ", "-"):
                new.append(b[0] + src[found + t])
                t += 1
            else:
                new.append(b)
        if new != body or int(hm.group(1)) != found + 1:
            notes.append(f"hunk moved {hm.group(1)} -> {found + 1}, context retyped from the file")
        # git apply anchors a hunk with less context after than before to the
        # END of the file (and the reverse to its start): a hunk that ends on
        # an added line was refused at line 193 of a 621-line file. Balance the
        # context with the file's own neighbouring lines.
        start = found
        lead = next((k for k, b in enumerate(new) if b[:1] != " "), len(new))
        trail = next((k for k, b in enumerate(reversed(new)) if b[:1] != " "), len(new))
        n_old_lines = sum(b[:1] in (" ", "-") for b in new)
        while trail < lead and found + n_old_lines < len(src):
            new.append(" " + src[found + n_old_lines])
            n_old_lines += 1
            trail += 1
        while lead < trail and start > 0:
            start -= 1
            new.insert(0, " " + src[start])
            lead += 1
        if (lead, trail) != (0, 0) and len(new) != len(body):
            notes.append("context balanced from the file")
        n_old = sum(b[:1] in (" ", "-") for b in new)
        n_new = sum(b[:1] in (" ", "+") for b in new)
        out.append(f"@@ -{start + 1},{n_old} +{start + 1},{n_new} @@{hm.group(3)}")
        out.extend(new)
        i = j
    return "\n".join(out) + "\n", notes


# -- one task -----------------------------------------------------------------

def run_task(task: dict, sandbox_factory: Callable, chat: Callable, log=print,
             align: bool = True, retry_wait: float = 10.0) -> dict:
    """``sandbox_factory(image)`` -> object with put_files/exec/destroy and the id;
    ``chat(prompt, kind)`` -> message dict (kind: "pick" or "patch")."""
    from nge import llm_text
    f2p, p2p = json.loads(task["FAIL_TO_PASS"]), json.loads(task["PASS_TO_PASS"])
    visible, hidden = split_f2p(f2p)
    tfiles = test_files(task["test_patch"])
    image = image_for(task["instance_id"])
    rec = {"instance": task["instance_id"], "repo": task["repo"], "f2p": len(f2p),
           "visible": len(visible), "hidden": len(hidden), "p2p": len(p2p), "events": []}
    t0 = time.perf_counter()

    def one(cmd: str, files: Dict[str, str], timeout: int = 900):
        # one retry on a sandbox error: a ContreeImageStateError mid-run cost a
        # task in the step-1 smoke, and a fresh sandbox is cheap
        for attempt in (1, 2):
            sbx, sid = sandbox_factory(image)
            try:
                sbx.put_files(sid, files)
                return sbx.exec(sid, cmd, timeout=timeout)
            except Exception as exc:
                if attempt == 2:
                    raise
                rec["events"].append(f"sandbox_retry:{type(exc).__name__}")
                time.sleep(retry_wait)
            finally:
                try:
                    sbx.destroy(sid)
                except Exception:
                    pass

    base = one(baseline_cmd(visible), {"/tmp/test.patch": task["test_patch"]})
    sec = sections(base.stdout)
    failing = sec.get("visible", ("", -1))[0]
    listed = [l.strip() for l in sec.get("files", ("", 0))[0].splitlines() if l.strip()]
    vis_out = outcomes(failing)
    rec["visible_failing_before"] = sum(vis_out.get(t) in ("FAILED", "ERROR") for t in visible)

    # 2. which files to read (typed reply)
    pick = chat(pick_prompt(task, failing, listed), "pick")
    try:
        chosen = [f for f in json.loads(pick.get("content") or "{}").get("files", [])
                  if f in listed][:MAX_FILES]
    except (ValueError, AttributeError):
        chosen = []
        rec["events"].append("pick_unparsed")
    in_trace = [f for f in listed if f in failing and f not in chosen]
    chosen = (chosen + in_trace)[:MAX_FILES] or in_trace[:MAX_FILES]
    rec["files_chosen"] = chosen

    # 3. read them
    shown, texts = "", {}
    if chosen:
        cat = sections(one(cat_cmd(chosen), {}, timeout=300).stdout)
        texts = {p: cat[f"file:{p}"][0] for p in chosen if f"file:{p}" in cat}
        shown = "\n\n".join(excerpt(p, cat[f"file:{p}"][0], lines_in_output(p, failing))
                            for p in chosen if f"file:{p}" in cat)

    # 4. the patch
    msg = chat(patch_prompt(task, failing, shown), "patch") or {}
    rec.update(finish_reason=msg.get("finish_reason"), reasoning_tokens=msg.get("reasoning_tokens"))
    patch = llm_text.unified_diff(msg)
    if not patch:
        rec["events"].append("patch_truncated" if msg.get("finish_reason") == "length"
                             else "patch_unparsed" if (msg.get("content") or "").strip()
                             else "patch_empty")
        rec.update(patch="", resolved=False, reason="no patch proposed",
                   seconds=round(time.perf_counter() - t0, 1))
        return rec
    patch = patch if patch.endswith("\n") else patch + "\n"
    rec["patch_as_written"] = patch
    if align:
        patch, rec["align_notes"] = align_to_source(patch, texts)
    rec["patch"] = patch
    changes = [l for l in patch.splitlines()
               if l[:1] in "+-" and not l.startswith(("+++", "---"))]
    if not changes:
        # Seen with reasoning on (flask-5014, 2 of 3 runs): the fix written as
        # context lines, no + or - at all. Not "did not apply": it changes nothing.
        rec["events"].append("diff_changes_nothing")
        rec.update(applied="no", resolved=False, reason="diff changes nothing",
                   seconds=round(time.perf_counter() - t0, 1))
        return rec

    # 5. verify with the task's own tests
    ver = one(verify_cmd(tfiles), {"/tmp/test.patch": task["test_patch"], "/tmp/model.patch": patch})
    vs = sections(ver.stdout)
    applied = vs.get("model_patch", ("", 1))
    after = outcomes(vs.get("verify", ("", 0))[0])
    rec.update(
        applied=("strict" if "NGE_APPLIED:strict" in applied[0] else
                 "whitespace" if "NGE_APPLIED:whitespace" in applied[0] else "no"),
        visible_fixed=sum(after.get(t) == "PASSED" for t in visible),
        hidden_fixed=sum(after.get(t) == "PASSED" for t in hidden),
        p2p_passed=sum(after.get(t) == "PASSED" for t in p2p),
        regressions=[t for t in p2p if after.get(t) not in (None, "PASSED")][:20],
        verify_stdout=vs.get("verify", ("", 0))[0][-20000:], exit_code=ver.exit_code,
        stderr=ver.stderr[-4000:],
    )
    rec["resolved"] = (rec["applied"] != "no" and rec["visible_fixed"] == len(visible)
                       and rec["hidden_fixed"] == len(hidden) and rec["p2p_passed"] == len(p2p))
    rec["reason"] = ("resolved" if rec["resolved"] else
                     "patch did not apply" if rec["applied"] == "no" else
                     "broke " + ", ".join(rec["regressions"][:3]) if rec["regressions"] else
                     "held-out tests still failing" if rec["visible_fixed"] == len(visible)
                     else "target test still failing")
    rec["seconds"] = round(time.perf_counter() - t0, 1)
    return rec


def archive(out_dir: Path, run_id: str, rec: dict, failing_head: str, meta: dict) -> None:
    from nge import attempts
    row = {"test": rec["instance"], "patch": rec.get("patch") or None,
           "verified": rec.get("resolved", False), "reason": rec.get("reason", ""),
           "stdout": rec.get("verify_stdout", ""), "stderr": rec.get("stderr", ""),
           "exit_code": rec.get("exit_code"), "regressions": rec.get("regressions", [])}
    failures = [{"test": rec["instance"], "error": failing_head[:300], "context": failing_head}]
    events = [{"kind": k, "test": rec["instance"]} for k in rec.get("events", [])]
    attempts.archive(out_dir, run_id, [row], failures, events, {rec["instance"]: meta},
                     {"fleet_mode": "none", "sandbox_mode": "token_factory",
                      "target": "swebench:" + rec["repo"]})


# -- live wiring --------------------------------------------------------------------

def _live():
    from nge import config as _cfg
    from nge.backends import register
    from nge.backends.nebius import chat_nebius, resolve_patch_max_tokens, resolve_thinking
    from nge.sandbox.base import SandboxSpec
    from nge.sandbox.token_factory import TokenFactorySandbox
    cfg = _cfg.load(sandbox_mode="token_factory")
    register.apply()
    meta = {"source": "model", "model": cfg.nemotron_model, "max_tokens": resolve_patch_max_tokens(),
            "thinking": resolve_thinking("patch")}

    def sandbox_factory(image):
        sbx = TokenFactorySandbox(cfg)
        return sbx, sbx.create(SandboxSpec(image=image))

    def chat(prompt, kind):
        msgs = [{"role": "user", "content": prompt}]
        if kind == "pick":
            return chat_nebius(msgs, cfg.nemotron_model, None, max_tokens=512,
                               thinking=resolve_thinking("short"),
                               response_format={"type": "json_schema", "json_schema": {
                                   "name": "pick_files", "schema": PICK_SCHEMA, "strict": True}})
        return chat_nebius(msgs, cfg.nemotron_model, None, max_tokens=meta["max_tokens"],
                           thinking=meta["thinking"])
    return cfg, sandbox_factory, chat, meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--i-know-cost", action="store_true", help="Nemotron calls + sandbox time")
    ap.add_argument("--instances", default="", help="comma-separated instance ids")
    ap.add_argument("--repos", default="", help="comma-separated repos, e.g. psf/requests")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--csv", default="out/swebench/results.csv")
    ap.add_argument("--no-align", action="store_true",
                    help="apply the diff as the model wrote it (no context alignment)")
    args = ap.parse_args(argv)
    if not args.i_know_cost:
        print("refusing: live Nemotron and sandboxes - pass --i-know-cost", file=sys.stderr)
        return 2
    if not args.instances and not args.repos:
        print("refusing: name --instances or --repos (and --limit)", file=sys.stderr)
        return 2
    from datetime import datetime, timezone
    from nge.backends import usage as _usage
    cfg, sandbox_factory, chat, meta = _live()
    out_dir = cfg.out_dir / "swebench"
    _usage.reset_usage()
    tasks = load_tasks([i for i in args.instances.split(",") if i],
                       [r for r in args.repos.split(",") if r], args.limit,
                       cache=out_dir / "verified.json")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rows = []
    csv_path = Path(args.csv)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["instance", "repo", "f2p", "visible", "hidden", "p2p", "visible_failing_before",
              "files_chosen", "applied", "visible_fixed", "hidden_fixed", "p2p_passed", "resolved",
              "reason", "finish_reason", "reasoning_tokens", "align_notes", "events", "seconds"]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=fields).writeheader()
    for task in tasks:
        print(f"[swebench] {task['instance_id']} ...", flush=True)
        try:
            rec = run_task(task, sandbox_factory, chat, align=not args.no_align)
        except Exception as exc:                 # one broken task must not end the series
            rec = {"instance": task["instance_id"], "repo": task["repo"], "resolved": False,
                   "reason": f"harness error: {type(exc).__name__}: {str(exc)[:200]}", "events": []}
        archive(out_dir, run_id, rec, rec.get("verify_stdout", "")[:4000], meta)
        rows.append({k: rec.get(k) for k in fields})
        with csv_path.open("a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=fields).writerow(rows[-1])
        r = rows[-1]
        print(f"[swebench] {r['instance']}: {'RESOLVED' if r['resolved'] else 'not resolved'} - "
              f"{r['reason']} | files {r['files_chosen']} | applied {r['applied']} | {r['seconds']} s")
    print(f"[swebench] resolved {sum(bool(r['resolved']) for r in rows)}/{len(rows)} "
          f"(test-guided repair, not a SWE-bench score) | csv {csv_path}")
    print(_usage.format_summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
