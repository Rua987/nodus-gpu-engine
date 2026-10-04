"""Replay the shard whose output ContreeSDK cut, at both output limits.

The Compute Phase 3 hybrid run (evidence/report_20261004T031503Z) counted
``test_connect_mc`` - the head of ``test_connect_mcp_forwards_org_id_env`` - as
a failing test: shard 0's ``-v`` output outgrew the SDK's 64 KiB default and
the last ``FAILED`` line was cut mid-name. This runs that shard's exact command
in one Token Factory sandbox (no VM, no fleet) at the SDK default and at the
engine's limit, and prints what the engine parses from each.

    python -m bench.output_cut_replay --i-know-cost
"""
from __future__ import annotations

import argparse
import os
import re
import sys

CMD = ("pip install -q -r packages/nodus/requirements-ci.txt && PYTHONPATH=packages/nodus "
       "pytest packages/nodus/tests/test_demo_agentic_cinema.py "
       "packages/nodus/tests/test_nodus_agent.py packages/nodus/tests/test_nodus_grafana.py "
       "packages/nodus/tests/test_nodus_plan_slotfill.py packages/nodus/tests/test_nodus_policy.py "
       "packages/nodus/tests/test_nodus_verify.py packages/nodus/tests/test_ssrf_redirect.py "
       "-v --tb=short --junitxml=report.xml")
SDK_DEFAULT = 65535


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--i-know-cost", action="store_true",
                    help="two Token Factory sandbox runs (cents)")
    args = ap.parse_args(argv)
    if not args.i_know_cost:
        print("refusing: two live sandbox runs - pass --i-know-cost", file=sys.stderr)
        return 2

    from nge import config as _cfg
    from nge.orchestrator import NgeOrchestrator, _REPO_ROOT, _parse_failures
    from nge.sandbox import token_factory as tf
    from nge.sandbox.base import SandboxSpec

    cfg = _cfg.load(fleet_mode="mock", sandbox_mode="token_factory")
    payload = NgeOrchestrator(config=cfg)._payload_files("packages/nodus/tests",
                                                         ["packages/nodus"])
    req = "packages/nodus/requirements-ci.txt"
    payload[req] = (_REPO_ROOT / req).read_text(encoding="utf-8")

    for limit in (SDK_DEFAULT, tf.DEFAULT_OUTPUT_BYTES):
        os.environ["NGE_CONTREE_OUTPUT_BYTES"] = str(limit)
        sbx = tf.TokenFactorySandbox(cfg)
        sid = sbx.create(SandboxSpec(image=tf.DEFAULT_IMAGE))
        try:
            sbx.put_files(sid, payload)
            r = sbx.exec(sid, CMD, timeout=300)
        finally:
            sbx.destroy(sid)
        raw = re.findall(r"^FAILED\s+\S+::(\S+)", r.stdout, re.M)
        parsed = [f["test"].split("::")[-1] for f in
                  _parse_failures({"stdout": r.stdout, "truncated": r.truncated})]
        print(f"limit={limit} exit={r.exit_code} stdout_bytes={len(r.stdout.encode())} "
              f"truncated={r.truncated}")
        print(f"   raw FAILED ids : {raw}")
        print(f"   engine parses  : {parsed}")
        print(f"   tail           : {r.stdout[-90:]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
