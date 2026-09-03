"""Assertions a --live run must satisfy, for CI.

A live run that "succeeds" proves very little on its own. Every bug found the
day the sandboxes were switched on produced a run that exited 0:

* the sandbox had no pytest, so every shard came back exit=127 having tested
  nothing - and a shard that ran zero tests reports ``0 failure(s)``, exactly
  like a shard where everything passed;
* the model invented ``--html``, pytest exited 4 before running, same summary;
* a jail rejection surfaced as exit=126, same summary;
* the fix sandbox began with ``git``, which the image does not have, so every
  patch was reported "rejected" without ever being applied.

So the checks below look at *evidence of work*, not at the exit code:
the sandbox mode actually used, whether commands ran at all, whether tests
were really executed, and whether the fleet was released.

``verify()`` returns a list of problems - empty means the run is trustworthy.
Pure and offline, so CI tests it without credentials.
"""
from __future__ import annotations

from typing import Any, Dict, List

# exit codes that mean "nothing ran", not "tests failed"
NOTHING_RAN = {
    126: "blocked by the capability jail",
    127: "command not found in the sandbox",
    4: "pytest usage error (unknown option)",
}


def _events(rep: Dict[str, Any], kind: str) -> List[dict]:
    return [e for e in rep.get("events", []) if e.get("kind") == kind]


def verify(rep: Dict[str, Any], expect_sandbox: str = "token_factory",
           require_tests_ran: bool = True) -> List[str]:
    """Problems with a RunReport dict. Empty list means it holds up."""
    bad: List[str] = []

    if not rep.get("ok"):
        bad.append("run did not complete (ok is false)")
    for e in _events(rep, "run_error"):
        bad.append(f"run_error: {e.get('error')}")

    # the run must have used the backend we think it used
    starts = _events(rep, "run_start")
    if starts:
        mode = starts[0].get("sandbox_mode")
        if mode != expect_sandbox:
            bad.append(f"sandbox_mode was {mode!r}, expected {expect_sandbox!r}")

    shards = rep.get("shards") or []
    if not shards:
        bad.append("no shards ran")

    for s in shards:
        code = s.get("exit_code")
        if code in NOTHING_RAN:
            bad.append(f"shard {s.get('index')}: exit={code} "
                       f"({NOTHING_RAN[code]}) - nothing was tested")

    # a shard that really ran pytest took some time and produced output
    if require_tests_ran and shards:
        ran = [s for s in shards
               if s.get("exit_code") not in NOTHING_RAN
               and _looks_like_a_test_run(s.get("stdout") or "")]
        if not ran:
            bad.append("no shard produced pytest output - the sandbox may be "
                       "empty even though the run exited cleanly")

    # the fleet must always be handed back
    if not _events(rep, "gpu_release"):
        bad.append("no gpu_release event - the fleet may still be billing")

    return bad


def _looks_like_a_test_run(stdout: str) -> bool:
    """True when pytest actually collected and ran something."""
    if not stdout:
        return False
    markers = ("passed", "failed", "error", "no tests ran", "collected")
    return any(m in stdout.lower() for m in markers)


def summary(rep: Dict[str, Any]) -> str:
    """One-line human summary for the CI log."""
    shards = rep.get("shards") or []
    fixes = rep.get("fixes") or []
    verified = len([f for f in fixes if f.get("verified")])
    codes = ", ".join(str(s.get("exit_code")) for s in shards)
    return (f"shards={len(shards)} exit=[{codes}] "
            f"failures={len(rep.get('failures') or [])} "
            f"fixes={verified}/{len(fixes)} verified")


def main(argv=None) -> int:
    """``python -m nge.live_check <report.json>`` - CI entry point."""
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser(description="Check a --live RunReport")
    ap.add_argument("report", help="RunReport JSON (from --json)")
    ap.add_argument("--sandbox", default="token_factory")
    ap.add_argument("--allow-no-tests", action="store_true",
                    help="do not require evidence that pytest ran")
    args = ap.parse_args(argv)

    try:
        with open(args.report, encoding="utf-8") as f:
            rep = json.load(f)
    except (OSError, ValueError) as exc:
        print(f"cannot read {args.report}: {exc}", file=sys.stderr)
        return 2

    print(summary(rep))
    problems = verify(rep, expect_sandbox=args.sandbox,
                      require_tests_ran=not args.allow_no_tests)
    for p in problems:
        print(f"  FAIL  {p}", file=sys.stderr)
    if not problems:
        print("  live run holds up")
    return 1 if problems else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
