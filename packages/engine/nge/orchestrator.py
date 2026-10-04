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
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Optional, Sequence

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
# The " - <message>" tail is optional: with plain `-q` pytest prints only
# `FAILED <nodeid>`, which is exactly what the first working live run
# produced - 3 real failures that parsed as zero.
_FAILED_RE = re.compile(rf"^FAILED\s+({_TEST_ID})(?:\s+-\s+(.*))?$", re.M)
# files a unified diff touches: "--- a/path" / "+++ b/path"
_PATCH_FILE_RE = re.compile(r"^(?:---|\+\+\+)\s+[ab]/(\S+)", re.M)
# @@ -old,n +new,m @@ trailer
_HUNK_HDR_RE = re.compile(r"^@@\s+-(\d+),(\d+)\s+\+\d+,(\d+)\s+@@(.*)$")

# pytest options that need no plugin. A model that reaches for pytest-html
# (`--html=... --self-contained-html`) or an invented `--gpu` costs the whole
# shard: pytest exits 4 on an unrecognised argument, before running anything.
_PYTEST_FLAGS = frozenset("""
-q -qq -v -vv -vvv -x -s -l -ra -rA -rf -rE -rs --quiet --verbose --exitfirst
--tb --maxfail --durations --junitxml --junit-xml --rootdir --capture --color
-k -m -p --deselect --ignore --ignore-glob --co --collect-only --no-header
--no-summary --strict-markers --strict-config --disable-warnings -W --lf -ff
--last-failed --failed-first --cache-clear --showlocals --full-trace --pdb
--basetemp --import-mode --continue-on-collection-errors -c --override-ini -o
""".split())

# Known to pytest, but they change *what runs*, not how it is reported. Live,
# once slot-fill stopped being starved by reasoning, Nemotron added `-x` on
# every shard (the prompt listed it as allowed): each shard stopped at its
# first failure, the run saw 2 failures instead of 5, and the whole-suite
# re-run during verification then blamed patches for the 3 it had hidden.
# `--pdb` would park the sandbox on a prompt until the timeout.
_NARROWING_FLAGS = frozenset("""
-x --exitfirst --maxfail -k -m --deselect --ignore --ignore-glob --co
--collect-only --lf --last-failed --ff -ff --failed-first --sw --stepwise
--pdb --trace
""".split())

_TB_STYLES = frozenset({"auto", "long", "short", "line", "native", "no"})

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
    stdout: str = ""            # kept so triage can quote the traceback


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
    # cap on the source tree shipped into a sandbox (bytes)
    PAYLOAD_MAX_BYTES = 4 * 1024 * 1024
    # backoff between patch attempts when the model answers nothing
    RETRY_DELAY_S = 2.0
    # plan names that mean "change the tree" - without them autofix stays off
    FIX_TOOLS = frozenset({"edit_file", "write_file"})

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
        from nge.backends import usage as _usage
        rec = router.route(decision, self.config)
        self.routes.append(rec)
        self._emit("model_route", **rec)
        _usage.record_route(rec["tier"], decision)
        return rec["model"]

    def _invoke_chat(self, messages, model, tools=None,
                     max_tokens: Optional[int] = None,
                     decision: Optional[str] = None,
                     thinking: Optional[bool] = None):
        """Call ``chat_fn``; on Nano/Ultra 429/5xx, one hop to Super (logged)."""
        if self.chat_fn is None:
            raise RuntimeError("chat_fn is not set")
        from nge.backends.nebius import ModelUnavailableError
        from nge.backends import usage as _usage
        from nge import router
        from nge.backends.usage import guess_tier

        def _call(mdl):
            # chat_fn may predate either keyword; drop what it does not take
            if thinking is not None:
                try:
                    return self.chat_fn(messages, mdl, tools,
                                        max_tokens=max_tokens, thinking=thinking)
                except TypeError:
                    pass
            try:
                return self.chat_fn(messages, mdl, tools, max_tokens=max_tokens)
            except TypeError:
                return self.chat_fn(messages, mdl, tools)

        try:
            return _call(model)
        except ModelUnavailableError as exc:
            _usage.record_error(getattr(exc, "model", model) or model,
                                getattr(exc, "status", None))
            tier = router.tier_for(decision) if decision else guess_tier(model)
            if tier == "super":
                raise
            super_m = self.config.nemotron_super
            self._emit("model_failover", decision=decision or "?",
                       from_tier=tier, from_model=model, to_model=super_m,
                       status=getattr(exc, "status", None),
                       error=str(exc))
            _usage.record_failover(model, super_m, decision or "")
            try:
                return _call(super_m)
            except ModelUnavailableError as exc2:
                _usage.record_error(getattr(exc2, "model", super_m) or super_m,
                                    getattr(exc2, "status", None))
                raise

    # -- slot-fill -------------------------------------------------------
    def _shard_command(self, task: str, plan_names: List[str], target: str,
                       index: int, shards: int,
                       own: Optional[List[str]] = None) -> str:
        # what this shard is actually responsible for
        paths = " ".join(shlex.quote(p) for p in own) if own else shlex.quote(target)
        base = (f"pip install -q pytest && "
                f"python -m pytest {paths} -q --tb=short -p no:cacheprovider")
        model = self._route("slotfill")
        if self.chat_fn is None:
            return f"NGE_SHARD={index}/{shards} {base}"
        from nge.backends.nebius import (SLOT_MAX_TOKENS, ModelUnavailableError,
                                         resolve_thinking)
        prompt = (
            "Fill ONE shell command for this shard of a distributed test run.\n"
            f"Task: {task}\nPlan: {plan_names}\n"
            f"Shard {index} of {shards}. Target path: {target}\n"
            + (f"This shard runs EXACTLY these files, all of them and nothing "
               f"else: {' '.join(own)}\n" if own else "")
            + "The sandbox has plain pytest and no plugins: use only core "
              "output options (-q, -v, --tb=short, --junitxml=report.xml). "
              "Every test in those "
              "files must run: no -x, --maxfail, -k, -m or deselection. No "
              "--html, no invented flags, no $(...) or backticks.\n"
              "Reply with ONLY the command."
        )
        fallback = f"NGE_SHARD={index}/{shards} {base}"
        try:
            msg = self._invoke_chat([{"role": "user", "content": prompt}],
                                    model, None, max_tokens=SLOT_MAX_TOKENS,
                                    decision="slotfill",
                                    thinking=resolve_thinking("short"))
        except ModelUnavailableError as exc:
            self._emit("model_unavailable", shard=index,
                       model=getattr(exc, "model", model),
                       status=getattr(exc, "status", None),
                       error=str(exc))
            return fallback
        except Exception as exc:                     # a flaky model must not
            self._emit("slotfill_error", shard=index,   # take the run down
                       error=f"{type(exc).__name__}: {exc}")
            return fallback
        cmd = llm_text.first_command(msg)
        if not cmd:
            # Cut by the ceiling is a budget problem, not a model that had
            # nothing to say - live, every such reply was 256/256 reasoning.
            if (msg or {}).get("finish_reason") == "length":
                self._emit("slotfill_truncated", shard=index,
                           max_tokens=SLOT_MAX_TOKENS,
                           reasoning_tokens=(msg or {}).get("reasoning_tokens"))
            else:
                self._emit("slotfill_empty", shard=index)
            return fallback
        # The model is free to phrase the command, not to change the work.
        # Live, Nemotron answered `pytest packages/nodus/tests -v --gpu` for a
        # shard that owned 4 named files: it silently un-did the split (every
        # shard back to the whole suite) and invented a --gpu flag, exit=4.
        if own:
            missing = [p for p in own if p not in cmd]
            if missing:
                self._emit("slotfill_off_target", shard=index, command=cmd,
                           missing=len(missing))
                return fallback
        bad = self._unknown_pytest_flags(cmd)
        if bad:
            self._emit("slotfill_bad_flags", shard=index, command=cmd,
                       flags=sorted(bad))
            return fallback
        narrowed = self._narrowing_pytest_flags(cmd)
        if narrowed:
            self._emit("slotfill_narrowed", shard=index, command=cmd,
                       flags=sorted(narrowed))
            return fallback
        # A command the jail will refuse costs the whole shard (exit 126, zero
        # tests run). Vet it here and keep the deterministic template instead -
        # the first live run lost every shard to $(...) the model invented.
        if self.config.jail:
            from nge import policy
            ok, reason = policy.check_command(cmd, strict=True)
            if not ok:
                self._emit("slotfill_rejected", shard=index, command=cmd,
                           reason=reason)
                return fallback
        return cmd

    @staticmethod
    def _failure_context(stdout: str, test: str, limit: int = 1500) -> str:
        """The traceback pytest printed for ``test``.

        Without this the code agent was handed `Error: (no message; see shard
        output)` and had to invent a patch from the test name alone - every
        one of them failed to apply.
        """
        if not stdout:
            return ""
        name = test.split("::")[-1]
        lines = stdout.splitlines()
        start = None
        for i, ln in enumerate(lines):
            # pytest heads each failure block with `___ test_name ___`
            if ln.startswith("_") and name in ln:
                start = i
                break
        if start is None:
            for i, ln in enumerate(lines):
                if name in ln and ("Error" in ln or "assert" in ln):
                    start = max(0, i - 4)
                    break
        if start is None:
            return ""
        out = []
        for ln in lines[start:start + 60]:
            if out and ln.startswith("_") and name not in ln:
                break                                   # next failure block
            out.append(ln)
        return "\n".join(out)[:limit]

    _TB_LOC_ALL = re.compile(r"^([\w./-]+\.py):(\d+)", re.M)

    def _source_excerpt(self, context: str, span: int = 12) -> str:
        """The real lines around the failure, quoted from the repo.

        A model that only sees a traceback has to guess the indentation, and
        it guesses wrong: Nemotron produced a hunk with 4 spaces for a line
        that has 8 (a method inside a class), so patch-ng refused every patch
        with "hunk no.1 doesn't match source file". Showing it the actual text
        removes the guess.
        """
        hits = self._TB_LOC_ALL.findall(context or "")
        if not hits:
            return ""
        parts = []
        for rel, line_s in hits[:3]:
            part = self._one_excerpt(rel, int(line_s), span)
            if part and part not in parts:
                parts.append(part)
        return "\n\n".join(parts)

    @staticmethod
    def _one_excerpt(rel: str, line: int, span: int) -> str:
        try:
            f = (_REPO_ROOT / rel).resolve()
            f.relative_to(_REPO_ROOT)
            if not f.is_file():
                return ""
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except (OSError, ValueError):
            return ""
        lo, hi = max(0, line - span), min(len(lines), line + span)
        body = "\n".join(f"{i + 1:5d}| {lines[i]}" for i in range(lo, hi))
        return f"{rel} (lines {lo + 1}-{hi}), exact text:\n{body}"

    def _relocate_hunks(self, patch: str) -> str:
        """Move each hunk to where its context actually is in the file.

        The model guesses the ``@@`` start line the same way it guessed the
        indentation and the counts. patch-ng then refuses with "hunk no.1
        doesn't match source file at line 35", quoting a line from somewhere
        else entirely. We have the file, so this is decidable: search for the
        hunk's own context/removed lines and rewrite the offset.

        A hunk whose context cannot be found anywhere is left untouched - the
        patch is simply wrong, and the sandbox will say so.
        """
        if not patch:
            return patch
        lines = patch.splitlines()
        out: List[str] = []
        src: Optional[List[str]] = None
        i = 0
        while i < len(lines):
            ln = lines[i]
            m = _PATCH_FILE_RE.match(ln)
            if m:                                   # entering a file section
                try:
                    f = (_REPO_ROOT / m.group(1)).resolve()
                    f.relative_to(_REPO_ROOT)
                    src = (f.read_text(encoding="utf-8", errors="replace")
                           .splitlines()) if f.is_file() else None
                except (OSError, ValueError):
                    src = None
                out.append(ln)
                i += 1
                continue

            hm = _HUNK_HDR_RE.match(ln)
            if not hm or src is None:
                out.append(ln)
                i += 1
                continue

            body, j = [], i + 1
            while j < len(lines) and lines[j][:1] in (" ", "-", "+", "\\"):
                body.append(lines[j])
                j += 1
            want = [b[1:] for b in body if b[:1] in (" ", "-")]
            new_start = int(hm.group(1))
            if want:
                found = None
                for k in range(len(src) - len(want) + 1):
                    if src[k:k + len(want)] == want:
                        found = k + 1               # diffs are 1-based
                        break
                if found is not None and found != new_start:
                    self._emit("patch_relocated", claimed=new_start, actual=found)
                    new_start = found
            out.append(f"@@ -{new_start},{hm.group(2)} "
                       f"+{new_start},{hm.group(3)} @@{hm.group(4)}")
            out.extend(body)
            i = j
        return "\n".join(out) + "\n"

    def _under_test(self, failure: dict, source_root: str = "") -> str:
        """Source of the functions the failing test calls, for the prompt.

        ``<file>::<Class>::<test>`` -> parse the test statically, follow its
        imports, and quote the definitions it invokes. Nothing is imported or
        executed, so a module that needs torch is still resolvable.
        """
        test_id = failure.get("test") or ""
        if "::" not in test_id:
            return ""
        rel_file, name = test_id.split("::")[0], test_id.split("::")[-1]
        try:
            f = (_REPO_ROOT / rel_file).resolve()
            f.relative_to(_REPO_ROOT)
            if not f.is_file():
                return ""
        except (OSError, ValueError):
            return ""

        roots = [_REPO_ROOT / source_root] if source_root else []
        roots += [f.parent, f.parent.parent, _REPO_ROOT]
        try:
            from nge import symbols
            found = symbols.sources_under_test(f, name, _REPO_ROOT, roots)
        except Exception as exc:                    # never break a run over this
            self._emit("under_test_error", test=test_id,
                       error=f"{type(exc).__name__}: {exc}")
            return ""
        if found:
            self._emit("under_test", test=test_id,
                       resolved=[f"{r}:{ln}" for r, ln, _ in found])
        return symbols.render(found)

    def _patch_context_missing(self, patch: str) -> List[str]:
        """Hunks whose context appears nowhere in the file they claim to edit.

        Relocating a hunk only helps when its context is real. Live, Nemotron
        wrote a patch for nodus_tools.py quoting

            dirname, filename = os.path.split(tail)
            filename = '_' + filename

        neither of which exists: the function it meant is at line 1200 and
        looks nothing like that. The model had never seen the module - the
        traceback only named the test file - so it wrote plausible fiction.

        Such a patch can never apply. Catching it here means saying so instead
        of provisioning a GPU to discover it.
        """
        bad: List[str] = []
        lines = (patch or "").splitlines()
        src: Optional[List[str]] = None
        rel = ""
        i = 0
        while i < len(lines):
            m = _PATCH_FILE_RE.match(lines[i])
            if m:
                rel = m.group(1)
                try:
                    f = (_REPO_ROOT / rel).resolve()
                    f.relative_to(_REPO_ROOT)
                    src = (f.read_text(encoding="utf-8", errors="replace")
                           .splitlines()) if f.is_file() else None
                except (OSError, ValueError):
                    src = None
                i += 1
                continue
            if not _HUNK_HDR_RE.match(lines[i]) or src is None:
                i += 1
                continue
            body, j = [], i + 1
            while j < len(lines) and lines[j][:1] in (" ", "-", "+", "\\"):
                body.append(lines[j])
                j += 1
            want = [b[1:] for b in body if b[:1] in (" ", "-") and b[1:].strip()]
            if want and not any(w in src for w in want):
                bad.append(rel)
            i = j
        return bad

    # -- sharding --------------------------------------------------------
    def _discover_test_files(self, target: str) -> List[str]:
        """Test files under ``target``, repo-relative, sorted (deterministic)."""
        try:
            base = (_REPO_ROOT / target).resolve()
            base.relative_to(_REPO_ROOT)
        except (OSError, ValueError):
            return []
        if base.is_file():
            return [base.relative_to(_REPO_ROOT).as_posix()]
        if not base.is_dir():
            return []
        out = []
        for f in sorted(base.rglob("test_*.py")) + sorted(base.rglob("*_test.py")):
            if "__pycache__" in f.parts:
                continue
            rel = f.relative_to(_REPO_ROOT).as_posix()
            if rel not in out:
                out.append(rel)
        return sorted(out)

    def _shard_targets(self, files: List[str], index: int, shards: int) -> List[str]:
        """Round-robin the test files over the shards.

        Without this every shard ran the *same* `pytest <target>`: three GPUs
        doing the identical suite three times. NGE_SHARD was in the command
        but nothing ever read it.
        """
        return files[index::shards] if files else []

    # -- what the tests need in order to import -------------------------
    @staticmethod
    def _source_root(target: str) -> str:
        """The importable root for ``target``.

        Shipping only ``packages/nodus/tests`` gave
        ``ModuleNotFoundError: No module named 'demo_agentic_cinema'`` - the
        tests import modules that live one level up. Walk out of the tests
        directory to find the root that has to be on PYTHONPATH.
        """
        p = PurePosixPath(target.replace("\\", "/"))
        while p.name in ("tests", "test", "testing") and str(p.parent) != ".":
            p = p.parent
        return str(p) if str(p) != "." else target

    @staticmethod
    def _requirements_file(root: str) -> Optional[str]:
        """A requirements file under ``root``, CI-flavoured first.

        The bare image has no third-party packages either: once the import
        path was fixed the next error was `No module named 'requests'`.
        """
        for name in ("requirements-ci.txt", "requirements-test.txt",
                     "requirements-dev.txt", "requirements.txt"):
            try:
                cand = (_REPO_ROOT / root / name).resolve()
                cand.relative_to(_REPO_ROOT)
            except (OSError, ValueError):
                continue
            if cand.is_file():
                return f"{root}/{name}"
        return None

    @staticmethod
    def _ensure_runner(cmd: str, source_root: str = "",
                       requirements: Optional[str] = None,
                       extra: tuple = ()) -> str:
        """Guarantee the runner, the deps and the import path.

        A Token Factory sandbox has no pytest, no third-party packages and no
        PYTHONPATH pointing at our code. Asking the model nicely in the prompt
        is not a guarantee - the first live run came back exit=127 on every
        shard because Nemotron wrote a bare `pytest ...` despite being told to
        install it first. Environment setup is the orchestrator's job.
        """
        install = (f"pip install -q -r {shlex.quote(requirements)}"
                   if requirements else "pip install -q pytest")
        if extra:
            install += " " + " ".join(shlex.quote(e) for e in extra)
        body = cmd
        if "pip install" in body:               # model already tried; use ours
            parts = [seg for seg in body.split("&&")
                     if "pip install" not in seg]
            body = "&&".join(parts).strip() or body
        if source_root and "PYTHONPATH=" not in body:
            body = f"PYTHONPATH={shlex.quote(source_root)} {body}"
        return f"{install} && {body}"

    @staticmethod
    def _pytest_args(cmd: str) -> List[str]:
        """Arguments given to pytest - only those *after* the pytest word, so
        the ``-m`` of ``python -m pytest`` is not read as pytest's ``-m``."""
        from nge import policy
        out: List[str] = []
        for seg in policy.split_segments(cmd):
            toks = shlex.split(seg)
            at = next((i for i, t in enumerate(toks)
                       if t == "pytest" or t.endswith("/pytest")), None)
            if at is not None:
                out += toks[at + 1:]
        return out

    @classmethod
    def _pytest_option_names(cls, cmd: str) -> set:
        return {t.split("=", 1)[0] for t in cls._pytest_args(cmd)
                if t.startswith("-") and t != "-"}

    @classmethod
    def _narrowing_pytest_flags(cls, cmd: str) -> set:
        """Options that would make a shard run less than the files it owns.
        (A bundle such as ``-xvs`` is already refused as an unknown option.)"""
        return cls._pytest_option_names(cmd) & _NARROWING_FLAGS

    @staticmethod
    def _unknown_pytest_flags(cmd: str) -> set:
        """Options in the pytest segment that plain pytest does not know.

        Live, Nemotron asked for `--html=report.html --self-contained-html`
        (pytest-html, not installed) and earlier for `--gpu`. Either one makes
        pytest exit 4 without running a single test, so the shard is lost.
        """
        bad = {n for n in NgeOrchestrator._pytest_option_names(cmd)
               if n not in _PYTEST_FLAGS}
        # A known option with an unusable value is just as fatal. Live, the
        # model copied the prompt's own placeholder `--tb=` verbatim: pytest
        # exited 4 on that shard, ran nothing, and two seeded bugs went unseen.
        args = NgeOrchestrator._pytest_args(cmd)
        for i, tok in enumerate(args):
            if not tok.startswith("-"):
                continue
            name, eq, val = tok.partition("=")
            if eq and not val:
                bad.add(tok)
            if name == "--tb":
                if not eq:
                    val = args[i + 1] if i + 1 < len(args) else ""
                if val not in _TB_STYLES:
                    bad.add(f"--tb={val}")
        return bad

    # -- feedback loop : agents self-manage their GPU compute ----------
    def _react_to_pressure(self, sr: "ShardResult", tele: Optional[dict],
                           target: str, collect: list,
                           gpu_type: str = "H100",
                           reserved_ids: Optional[Sequence[str]] = None,
                           gpu_workload: bool = False) -> None:
        """If the shard's node is throttling / inefficient, migrate the shard
        onto a freshly provisioned healthy node. Bounded to one remediation
        per shard.

        ``tele`` is the telemetry reading already taken by the run loop for this
        node - reused verbatim so the pressure event, the remediation record and
        the report all quote the exact same numbers (no second poll).

        ``reserved_ids``: nodes already earmarked for shards the fan-out loop
        has not reached yet. They report ``state=ready`` (nothing has called
        gpu_allocate on them so far) but are not spare capacity - picking one
        as a replacement here starves that later shard's own allocate() once
        every genuinely-idle node is gone. Regression: with more hot nodes
        than slack (padding beyond ``shards``), the fan-out loop hit
        "no ready node in fleet" a few shards before the end, because earlier
        migrations had already claimed later shards' nodes.
        """
        if sr.migrated_from is not None or not tele:
            return
        # Token Factory CPU sandboxes report power=0 → efficiency=0. That is a
        # *setup* (no nvidia-smi), not a throttling H100. Only remediate when
        # metrics are from a real GPU probe or the synthetic mock fleet.
        from nge.fleet import telemetry as _tele
        if not _tele.has_real_gpu_metrics(tele):
            self._emit("gpu_telemetry_non_gpu", shard=sr.index,
                       node_id=sr.node_id,
                       probe_kind=tele.get("probe_kind"),
                       gpu_class=tele.get("gpu_class"),
                       why="no nvidia-smi metrics — skip efficiency heal")
            return
        hot = tele["health"] == "throttle"
        inefficient = tele["efficiency"] < self.MIN_EFFICIENCY
        if (inefficient and not hot and tele.get("probe_kind") == _tele.PROBE_NVIDIA
                and not gpu_workload):
            # Efficiency is useful work per watt. On a real GPU that carries no
            # GPU work - the pytest shards run in Token Factory sandboxes - it
            # is 0 by construction: the real idle L40S read 27 C, 0 %, 67.8 W,
            # efficiency 0.0, and this rule would have migrated shards off a
            # perfectly healthy node. Heat and power still count.
            self._emit("gpu_efficiency_skipped", shard=sr.index,
                       node_id=sr.node_id, efficiency=tele["efficiency"],
                       why="no GPU workload declared - an idle GPU reads efficiency 0")
            inefficient = False
        pressured = hot or inefficient
        if not pressured:
            return

        self._route("healthcheck")   # telemetry reasoning -> Nano tier
        self._emit("gpu_pressure", shard=sr.index, node_id=sr.node_id,
                   health=tele["health"], efficiency=tele["efficiency"],
                   temp_c=tele["temp_c"], power_w=tele["power_w"])

        from nge.fleet import placement as _place
        needs = _place.WorkloadNeeds()
        reserved = set(reserved_ids or ())
        # Don't move fire→fire, and don't move fire→a house someone else is
        # about to move into: score ready nodes minus the ones still reserved
        # for shards the fan-out loop hasn't reached, provision only if none fit.
        repl = None
        decision = None
        for attempt in (1, 2):
            ready = [n for n in handlers.gpu_status()["nodes"]
                     if (n.get("state") or "") == "ready"
                     and n.get("id") != sr.node_id
                     and n.get("id") not in reserved]
            decision = _place.pick_replacement(
                ready, needs=needs, exclude_ids=[sr.node_id])
            self._emit("gpu_placement", shard=sr.index, attempt=attempt,
                       chosen=decision.node_id, score=decision.score,
                       reason=decision.reason,
                       refused=decision.refused[:8])
            if decision.node_id:
                repl = decision.node_id
                break
            # No cool house free — open one more, then re-score (mock
            # replacements are healthy; Compute must still pass the filter).
            handlers.gpu_provision(n=1, gpu_type=gpu_type)

        if not repl:
            self._emit("gpu_placement_refused", shard=sr.index,
                       from_node=sr.node_id,
                       reason=(decision.reason if decision
                               else "no destination"),
                       refused=(decision.refused[:8] if decision else []))
            return

        self._emit("gpu_provision_replacement", node_id=repl, for_shard=sr.index)
        handlers.gpu_allocate(job=f"shard-{sr.index}-retry", node_id=repl)
        res = handlers.run_in_sandbox(command=sr.command, node_id=repl,
                                      collect=collect, timeout=180)
        old_node = sr.node_id
        sr.migrated_from = old_node
        sr.node_id = repl
        sr.exit_code = res["exit_code"]
        sr.duration_s = res["duration_s"]
        sr.failures = [{"test": m.group(1), "error": m.group(2) or "(no message; see shard output)"}
                       for m in _FAILED_RE.finditer(res["stdout"])]
        rec = {"shard": sr.index, "from": old_node, "to": repl,
               "reason": tele["health"], "efficiency": tele["efficiency"],
               "temp_c": tele["temp_c"], "power_w": tele["power_w"],
               "placement_score": decision.score if decision else None}
        self.remediations.append(rec)
        self._emit("gpu_remediation", **rec)

        # telemetry of the replacement (so a watcher sees it running healthy)
        rst = handlers.gpu_status(node_id=repl)["nodes"]
        self._emit("gpu_status", node_id=repl, telemetry=rst[0] if rst else None)
        if rst and rst[0].get("health") in ("warm", "throttle"):
            self._emit("replacement_node_pressure_warning",
                       node_id=repl, health=rst[0].get("health"),
                       reason="replacement node itself under pressure")
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

        from nge.fleet.capabilities import preflight
        caps = preflight(self.config, emit=self._emit)
        # Always visible even without --watch (avoid blind live starts)
        try:
            from nge.fleet.capabilities import format_banner
            print(format_banner(caps), flush=True)
        except Exception:
            pass

        self._emit("run_start", task=task, shards=shards, gpu_type=gpu_type,
                   fleet_mode=self.config.fleet_mode, sandbox_mode=self.config.sandbox_mode,
                   jail=self.config.jail)

        # 1) plan (Nodus brain) - high-level reasoning routes to Ultra
        self._route("plan")
        from nge import planner
        pr = planner.plan(task, config=self.config)
        self._emit("plan", names=pr.names, source=pr.source, note=pr.note,
                   degraded=pr.degraded)
        if pr.degraded:
            self._emit("plan_degraded", source=pr.source, reason=pr.note)

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
        # do the shards put work on the GPU? pytest shards do not
        gpu_workload = bool(scenario.get("gpu_workload", False))

        # Split the work. The planner's vocabulary decides *how*: glob/grep
        # mean "go look first", so the file list is discovered from the tree;
        # otherwise the whole target goes to every shard (the old behaviour,
        # kept only as an explicit, logged choice rather than an accident).
        # Auto-fix is also plan-gated: without edit_file/write_file the
        # planner never asked to change code, so we triage only (see
        # _plan_allows_autofix). That makes the 324M (or heuristic) decide
        # something visible - not just fill a report field.
        wants_discovery = bool({"glob", "grep"} & set(pr.names))
        test_files = self._discover_test_files(target) if wants_discovery else []
        if wants_discovery:
            self._emit("plan_decision", decision="discover_test_files",
                       because=[n for n in pr.names if n in ("glob", "grep")],
                       files=len(test_files))
        if not test_files:
            # no plan hint (or nothing found): still split, so shards do not
            # all repeat the identical suite
            test_files = self._discover_test_files(target)
            if test_files:
                self._emit("shard_split", strategy="round-robin-files",
                           files=len(test_files), shards=shards)

        # The sandbox starts from a bare image, so every shard needs the code
        # under test, the modules it imports, and its dependencies.
        source_root = scenario.get("source_root") or self._source_root(target)
        requirements = (scenario.get("requirements")
                        or self._requirements_file(source_root))
        payload = self._payload_files(
            target, [source_root, *(scenario.get("payload") or [])])
        if requirements:
            try:
                payload[requirements] = (_REPO_ROOT / requirements).read_text(
                    encoding="utf-8", errors="replace")
            except OSError:
                requirements = None
        self._emit("sandbox_env", source_root=source_root,
                   requirements=requirements, payload_files=len(payload))
        if payload:
            self._emit("payload", files=len(payload),
                       bytes=sum(len(v) for v in payload.values()))

        # 3) fan out
        covered: set = set()
        for i, node_id in enumerate(node_ids):
            own = self._shard_targets(test_files, i, shards)
            if test_files and not own:
                # more shards than test files - do not burn a sandbox on a
                # duplicate of the whole suite
                self._emit("shard_empty", index=i, node_id=node_id)
                continue
            handlers.gpu_allocate(job=f"shard-{i}")
            cmd = self._ensure_runner(
                self._shard_command(task, pr.names, target, i, shards, own),
                source_root, requirements)
            self._emit("shard_start", index=i, node_id=node_id, command=cmd)
            res = handlers.run_in_sandbox(command=cmd, node_id=node_id,
                                          files=payload, collect=collect,
                                          timeout=180)
            fails = [{"test": m.group(1), "error": m.group(2) or "(no message; see shard output)"}
                     for m in _FAILED_RE.finditer(res["stdout"])]
            shard_results.append(ShardResult(
                index=i, node_id=node_id, command=cmd,
                exit_code=res["exit_code"], duration_s=res["duration_s"], failures=fails,
                stdout=(res["stdout"] or "")[-20000:],
            ))
            st = handlers.gpu_status(node_id=node_id)["nodes"]
            tele = st[0] if st else None
            self._emit("gpu_status", node_id=node_id, telemetry=tele)

            # feedback loop: react if this node is throttling / inefficient
            # (same telemetry reading - no second poll)
            if self_heal:
                self._react_to_pressure(shard_results[-1], tele, target,
                                        collect, gpu_type,
                                        reserved_ids=node_ids[i + 1:],
                                        gpu_workload=gpu_workload)

            sr = shard_results[-1]
            # a shard that produced pytest output is a usable baseline for its
            # files; one that died (126/127/4) is not
            if (sr.stdout or "").strip() and sr.exit_code not in (126, 127, 4):
                covered.update(own or test_files or [])
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
                                 "context": self._failure_context(sr.stdout, f["test"]),
                                 "proposed_fix": _proposed_fix(f["error"])})
        self._emit("triage", unique_failures=len(failures))
        # prioritize complex failures (longer error messages) - more likely to be systemic

        # 5) code agent: propose a patch per failure, apply + re-test in a
        #    fresh sandbox, keep only the verified ones - but only when the
        #    *plan* asked to edit/write. Mission can still disable autofix.
        if not auto_fix:
            self._emit("autofix_skipped", reason="disabled by mission",
                       would_have_tried=min(len(failures), self.MAX_FIXES))
        elif not self._plan_allows_autofix(pr.names):
            self._emit("plan_gated_autofix", allowed=False, plan=list(pr.names),
                       source=pr.source, need=sorted(self.FIX_TOOLS))
            self._emit("autofix_skipped", reason="plan_has_no_edit_tools",
                       plan=list(pr.names), source=pr.source,
                       would_have_tried=min(len(failures), self.MAX_FIXES))
        else:
            self._emit("plan_gated_autofix", allowed=True, plan=list(pr.names),
                       source=pr.source,
                       because=[n for n in pr.names if n in self.FIX_TOOLS])
            fixes.extend(self._attempt_fixes(
                failures, target, gpu_type, source_root, requirements,
                payload, covered))

    @classmethod
    def _plan_allows_autofix(cls, names) -> bool:
        return bool(cls.FIX_TOOLS & set(names or ()))

    # -- code agent : propose fix -> apply + re-test in a fresh sandbox ----
    def _propose_patch(self, failure: dict, model: str) -> Optional[str]:
        """Return a unified diff that should fix ``failure``.

        ``--mock``: the canned patch from the fixture catalogue.
        ``--local`` / ``--live``: ask the model (Nemotron Super tier) for a diff.
        """
        if self.chat_fn is None:
            from nge import _fixtures
            return _fixtures.canned_patch(failure["test"])

        excerpt = self._source_excerpt(failure.get("context") or "")
        # The traceback names the test file; the module it exercises appears
        # nowhere in it. Without this the model invents that module's contents.
        under_test = failure.get("under_test") or ""
        prompt = (
            "A test is failing. Reply with ONLY a unified diff (```diff fenced) "
            "that fixes it - no prose.\n"
            "Paths must be repo-relative (a/<path>, b/<path>) and match the "
            "traceback below.\n"
            "Every context line must be copied VERBATIM from the source shown "
            "below - do not retype or reformat it, and do not patch code that "
            "is not shown.\n"
            f"Test: {failure['test']}\nError: {failure['error']}\n"
            + (f"\nTraceback:\n{(failure.get('context') or '').strip()}\n"
               if failure.get("context") else "")
            + (f"\n{excerpt}\n" if excerpt else "")
            + (f"\n{under_test}\n" if under_test else "")
        )
        # Nemotron intermittently answers this prompt with an empty string -
        # the same request that produced a valid diff a run earlier. Two runs
        # in a row lost fixes to `has_patch: False` while a one-line prompt to
        # the same model answered fine, so this is flakiness, not refusal.
        # One retry, then give up honestly.
        from nge.backends.nebius import (ModelUnavailableError,
                                         resolve_patch_max_tokens,
                                         resolve_thinking)
        patch_cap = resolve_patch_max_tokens()
        patch_thinking = resolve_thinking("patch")
        for attempt in (1, 2, 3, 4):
            if attempt > 1:
                # Retrying instantly just spends the flaky window; wait it
                # out. Four attempts, not three: measured over 20 real calls
                # (bench/retry_distribution.py), 70% answer first try, 95% by
                # the second, and one needed a *fourth*. Nothing was recovered
                # at five or six, so a fifth attempt buys nothing.
                time.sleep(self.RETRY_DELAY_S * (attempt - 1))
            try:
                msg = self._invoke_chat([{"role": "user", "content": prompt}],
                                        model, None, max_tokens=patch_cap,
                                        decision="triage",
                                        thinking=patch_thinking)
            except ModelUnavailableError as exc:
                self._emit("model_unavailable", test=failure.get("test"),
                           attempt=attempt, model=getattr(exc, "model", model),
                           status=getattr(exc, "status", None),
                           error=str(exc))
                return None
            except Exception as exc:
                self._emit("patch_error", test=failure.get("test"),
                           attempt=attempt, error=f"{type(exc).__name__}: {exc}")
                return None
            # Hit the output ceiling: do not treat as empty-flake retry.
            if (msg or {}).get("finish_reason") == "length":
                text = llm_text.content_of(msg)
                reasoning = (msg or {}).get("reasoning_tokens")
                self._emit("patch_truncated", test=failure.get("test"),
                           attempt=attempt, max_tokens=patch_cap,
                           reply_chars=len(text),
                           reply_head=text.strip()[:200],
                           reasoning_tokens=reasoning,
                           why=("reasoning used the whole budget"
                                if reasoning and not text.strip()
                                else "finish_reason=length"))
                return None
            patch = llm_text.unified_diff(msg)
            if patch:
                if attempt > 1:
                    self._emit("patch_retry_succeeded", test=failure.get("test"))
                return patch
            # "no diff" has two very different causes: the model said nothing
            # at all (flakiness, worth a retry) or it answered in prose with no
            # diff in it (it declined, or wrote a format we do not parse).
            # Live these were logged under one name, and a 681-character reply
            # was reported as "patch_empty".
            text = llm_text.content_of(msg)
            if not text.strip():
                kind, why = "patch_empty", "model returned nothing"
            elif llm_text.has_hunks_without_header(text):
                # hunks but no `--- a/<path>`: which file to patch is unknown,
                # and guessing would apply the diff to the wrong one
                kind, why = "patch_unparsed", "hunks with no file header"
            else:
                kind, why = "patch_unparsed", "no diff in the reply"
            self._emit(kind, test=failure.get("test"), attempt=attempt,
                       why=why, reply_chars=len(text),
                       reply_head=text.strip()[:200])
            # Only an empty answer is worth another call. A refusal or a
            # headerless diff is a considered reply - asking again just spends
            # a request to get the same thing.
            if kind != "patch_empty":
                return None
        return None

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

    def _payload_files(self, target: str, extra=None) -> Dict[str, str]:
        """The repo files a shard needs in its sandbox.

        A Token Factory sandbox starts from a bare image: no pytest, and none
        of our code. Until this existed a --live shard ran `pytest <target>`
        against an empty container and came back exit=127, which the mock
        sandbox had been hiding by simulating the whole run.

        Ships the ``*.py`` under ``target`` (plus any ``payload`` paths from
        the scenario), capped, and confined to the repo.
        """
        out: Dict[str, str] = {}
        roots = [target, *(extra or [])]
        budget = self.PAYLOAD_MAX_BYTES
        for rel in roots:
            try:
                base = (_REPO_ROOT / rel).resolve()
                base.relative_to(_REPO_ROOT)           # refuse path escape
            except (OSError, ValueError):
                continue
            if not base.exists():
                continue
            files = [base] if base.is_file() else sorted(base.rglob("*.py"))
            for f in files:
                if "__pycache__" in f.parts or not f.is_file():
                    continue
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")
                    key = f.relative_to(_REPO_ROOT).as_posix()
                except (OSError, ValueError):
                    continue
                if key in out:
                    continue
                budget -= len(text.encode("utf-8", "replace"))
                if budget < 0:
                    self._emit("payload_truncated", at=key, root=rel)
                    return out
                out[key] = text
        return out

    def _attempt_fixes(self, failures: List[dict], target: str,
                       gpu_type: str = "H100", source_root: str = "",
                       requirements: Optional[str] = None,
                       payload: Optional[Dict[str, str]] = None,
                       covered: Optional[set] = None) -> List[dict]:
        # graver failures (longer error messages) are attempted first
        failures = sorted(failures,
                         key=lambda f: len(f.get("error", "")), reverse=True)
        fixes: List[dict] = []
        for f in failures[: self.MAX_FIXES]:
            model = self._route("triage")          # slot-fill / triage -> Super
            f.setdefault("under_test", self._under_test(f, source_root))
            patch = self._propose_patch(f, model)
            self._emit("fix_attempt", test=f["test"], has_patch=bool(patch))
            if not patch:
                from nge.fix_cause import annotate_fix
                row = {"test": f["test"], "verified": False,
                       "patch": None, "reason": "no patch proposed"}
                row.update(annotate_fix(
                    f, reason="no patch proposed", verified=False,
                    has_patch=False, all_failures=failures))
                fixes.append(row)
                continue

            patch = self._relocate_hunks(patch)
            missing = self._patch_context_missing(patch)
            if missing:
                self._emit("fix_context_invented", test=f["test"], files=missing)
                from nge.fix_cause import annotate_fix
                why = ("patch context does not exist in "
                       + ", ".join(sorted(set(missing))))
                row = {"test": f["test"], "patch": patch, "verified": False,
                       "reason": why}
                row.update(annotate_fix(
                    f, reason=why, verified=False, has_patch=True,
                    all_failures=failures))
                fixes.append(row)
                continue

            node = handlers.gpu_provision(n=1, gpu_type=gpu_type)["nodes"][-1]["id"]
            handlers.gpu_allocate(job=f"fix-{f['test'].split('::')[-1]}")
            kw = f["test"].split("::")[-1]
            # ship the touched sources next to the patch, and make the sandbox a
            # git work tree so `git apply` has a repo to act on
            # The verification sandbox needs exactly what a shard needs -
            # it was getting only the patched files, and its command started
            # with `git`, which python:3.12-slim does not ship (nor `patch`).
            # Every fix came back "rejected" on `git: not found`, so 0/N
            # verified said nothing about the patches at all.
            files = dict(payload or {})
            files["fix.patch"] = patch
            sources = self._sources_for_patch(patch)
            files.update(sources)
            self._emit("fix_sources", test=f["test"], files=sorted(sources))
            # Re-run the WHOLE suite, not the failing test and not even just
            # its file. `-k <test>` only answers "does this one pass now", and
            # a patch edits a module other files import too - scoping the check
            # to the test's own file still lets a fix break its neighbours
            # elsewhere. The shards already ran everything, so `before` is the
            # complete set of failures this run knows about; anything outside
            # it afterwards is damage this patch did.
            #
            # The exit code cannot be the criterion: the suite legitimately has
            # other red tests. Compare the failure sets instead.
            before = {str(x.get("test", "")) for x in failures}
            cmd = self._ensure_runner(
                f"python -m patch_ng --strip 1 fix.patch"
                # the mock sandbox needs to know which test is under repair;
                # harmless in a real one
                f" && NGE_FIX_TEST={shlex.quote(kw)}"
                f" python -m pytest {shlex.quote(target)} -q --tb=short"
                f" -p no:cacheprovider",
                source_root, requirements, extra=("patch-ng",))
            res = handlers.run_in_sandbox(
                command=cmd, node_id=node, files=files, timeout=300,
            )
            out = res["stdout"] or ""
            after = {m.group(1) for m in _FAILED_RE.finditer(out)}
            # A shard that was skipped or died (exit 126/127) never produced a
            # baseline for its files, so a pre-existing failure there would
            # look like damage. Only judge files the shards really ran.
            new = after - before
            if covered:
                unknown = {t for t in new if t.split("::")[0] not in covered}
                if unknown:
                    self._emit("fix_unjudged", test=f["test"],
                               files=sorted({t.split("::")[0] for t in unknown}))
                new -= unknown
            regressions = sorted(new)
            # With no output nothing ran, so "the test is not in the failure
            # list" is vacuous - the shape of the `git: not found` bug, where
            # an empty stdout looked exactly like a clean pass.
            ran = bool(out.strip())
            target_fixed = ran and f["test"] not in after
            verified = (target_fixed and not regressions
                        and not res.get("blocked"))
            if regressions:
                self._emit("fix_regression", test=f["test"], broke=regressions)
            self._emit("fix_verified" if verified else "fix_rejected",
                       test=f["test"], node=node,
                       target_fixed=target_fixed, regressions=len(regressions))
            if regressions:
                why = "broke " + ", ".join(regressions)
            elif verified:
                why = "re-tested green in a fresh sandbox"
            elif not ran:
                why = "sandbox produced no output - nothing ran"
            else:
                why = "target test still failing"
            from nge.fix_cause import annotate_fix
            row = {"test": f["test"], "patch": patch, "verified": verified,
                   "node": node, "stdout": res["stdout"],
                   "regressions": regressions, "reason": why}
            row.update(annotate_fix(
                f, reason=why, verified=verified, has_patch=True,
                regressions=regressions, all_failures=failures))
            fixes.append(row)
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
            f"- Plan ({pr.source}): `{pr.names}`"
            + ("  **- not the 324M planner**" if pr.degraded else ""),
            *([f"  - {pr.note}"] if pr.note else []),
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
        gated = [e for e in self.events if e.get("kind") == "plan_gated_autofix"]
        gate = gated[-1] if gated else None
        lines += ["", "## Auto-fixes (code agent)", ""]
        if gate is not None and not gate.get("allowed"):
            lines += [
                f"_Skipped — plan `{gate.get('plan')}` has no "
                f"`edit_file`/`write_file` (source={gate.get('source')}). "
                f"The planner did not ask to change code, so the engine "
                f"triages only._",
                "",
            ]
        lines += [
                  f"Attempted {len(fixes)} / {len(failures)} failure(s) · "
                  f"**{len(verified)} patched & re-tested green** in a fresh sandbox.", ""]
        if fixes:
            lines += ["| test | patch | verified | urgency | why |",
                      "|---|---|---|---|---|"]
            fix_dir = out_dir / "fixes"
            for x in fixes:
                pf = "-"
                if x.get("patch"):
                    fix_dir.mkdir(parents=True, exist_ok=True)
                    fn = x["test"].split("::")[-1] + ".patch"
                    (fix_dir / fn).write_text(x["patch"], encoding="utf-8")
                    pf = f"`fixes/{fn}`"
                mark = "✅" if x.get("verified") else ("—" if not x.get("patch") else "❌ still red")
                why = (x.get("reason") or "").replace("|", "/")
                lines.append(
                    f"| `{x['test']}` | {pf} | {mark} | "
                    f"**{x.get('urgency', '?')}** | {why} |")
                if x.get("cause"):
                    lines.append(f"| | | | | _{x['cause']}_ · {x.get('fragility', '')} |")

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
