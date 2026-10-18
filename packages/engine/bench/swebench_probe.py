"""Step 0 towards real bugs: can a Token Factory sandbox run a SWE-bench task?

No model call. One SWE-bench Verified task is replayed with its own historical
fix (the "gold" patch): the sandbox starts from the task's Docker image, the
task's tests are added, the FAIL_TO_PASS tests must fail, then pass once the
gold patch is applied, with every PASS_TO_PASS test still passing. If this
holds, the environment, the test run and the verdict all work, and only the
model is left to plug in.

    python -m bench.swebench_probe --i-know-cost
    python -m bench.swebench_probe --i-know-cost --instance psf__requests-5414

Task data: SWE-bench Verified via the Hugging Face datasets server. Image:
``swebench/sweb.eval.x86_64.<id with __ -> _1776_>`` (Docker Hub).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request

DATASET = ("https://datasets-server.huggingface.co/rows?dataset=princeton-nlp/"
           "SWE-bench_Verified&config=default&split=test")
PY = "/opt/miniconda3/envs/testbed/bin/python"


def fetch_instance(instance_id: str) -> dict:
    off = 0
    while True:
        with urllib.request.urlopen(f"{DATASET}&offset={off}&length=100", timeout=60) as r:
            d = json.load(r)
        for x in d["rows"]:
            if x["row"]["instance_id"] == instance_id:
                return x["row"]
        off += 100
        if off >= d.get("num_rows_total", 0):
            raise SystemExit(f"no instance {instance_id!r} in SWE-bench Verified")


def image_for(instance_id: str) -> str:
    return f"swebench/sweb.eval.x86_64.{instance_id.replace('__', '_1776_')}:latest"


def test_files(test_patch: str) -> list:
    return sorted(set(re.findall(r"^\+\+\+ b/(\S+)", test_patch, re.M)))


def outcomes(pytest_rA: str) -> dict:
    """{test id: PASSED|FAILED|ERROR|SKIPPED} from ``pytest -rA`` summary lines."""
    out = {}
    for m in re.finditer(r"^(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS) (\S+)", pytest_rA, re.M):
        out[m.group(2)] = m.group(1)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--i-know-cost", action="store_true", help="Token Factory sandbox time")
    ap.add_argument("--instance", default="pallets__flask-5014")
    args = ap.parse_args(argv)
    if not args.i_know_cost:
        print("refusing: live sandbox - pass --i-know-cost", file=sys.stderr)
        return 2
    from nge import config as _cfg
    from nge.sandbox.base import SandboxSpec
    from nge.sandbox.token_factory import TokenFactorySandbox

    inst = fetch_instance(args.instance)
    f2p, p2p = json.loads(inst["FAIL_TO_PASS"]), json.loads(inst["PASS_TO_PASS"])
    files = test_files(inst["test_patch"])
    image = image_for(args.instance)
    print(f"[probe] {args.instance} ({inst['repo']} {inst['version']}): "
          f"FAIL_TO_PASS {len(f2p)}, PASS_TO_PASS {len(p2p)}, test files {files}")
    print(f"[probe] image {image}")

    sbx = TokenFactorySandbox(_cfg.load(sandbox_mode="token_factory"))
    t0 = time.perf_counter()
    sid = sbx.create(SandboxSpec(image=image))
    report = {"instance": args.instance, "image": image, "base_commit": inst["base_commit"],
              "create_s": round(time.perf_counter() - t0, 1)}
    print(f"[probe] sandbox ready in {report['create_s']} s")
    # One command per sandbox, like the engine: a ContreeSDK run is disposable,
    # so a second exec on the same session raises DisposableImageRunError.
    tests = " ".join(files)
    mark = "echo ===NGE:{0} exit=$?==="
    cmd = " ; ".join([
        "cd /testbed", "git rev-parse HEAD~1", "git log --oneline -3",
        f"git cat-file -t {inst['base_commit']} 2>&1", "ls -la /tmp/test.patch /tmp/gold.patch",
        mark.format("env"),
        "git apply /tmp/test.patch", mark.format("test_patch"),
        f"{PY} -m pytest -rA {tests} -p no:cacheprovider", mark.format("before"),
        "git apply /tmp/gold.patch", mark.format("gold_patch"),
        f"{PY} -m pytest -rA {tests} -p no:cacheprovider", mark.format("after"),
    ])
    sbx.put_files(sid, {"/tmp/test.patch": inst["test_patch"], "/tmp/gold.patch": inst["patch"]})
    try:
        t = time.perf_counter()
        r = sbx.exec(sid, cmd, timeout=900)
        report["run_s"] = round(time.perf_counter() - t, 1)
    finally:
        sbx.destroy(sid)
    out = r.stdout
    print(f"[probe] one run: exit {r.exit_code} in {report['run_s']} s"
          + (" (output cut)" if r.truncated else ""))
    parts = re.split(r"^===NGE:(\w+) exit=(\d+)===$", out, flags=re.M)
    sections = {parts[i + 1]: (parts[i], int(parts[i + 2])) for i in range(0, len(parts) - 2, 3)}
    env = sections.get("env", ("", -1))[0]
    print("[probe] environment:\n  " + "\n  ".join(env.strip().splitlines()[:8]))
    # the image adds one commit ("SWE-bench") on top of the task's base commit
    report["head_parent"] = env.split()[0] if env.split() else ""
    report["base_commit_ok"] = report["head_parent"] == inst["base_commit"]
    for k in ("test_patch", "gold_patch"):
        report[f"{k}_applied"] = sections.get(k, ("", -1))[1] == 0
    b = outcomes(sections.get("before", ("", 0))[0])
    a = outcomes(sections.get("after", ("", 0))[0])
    if not sections:
        print("[probe] no section markers in the output; stderr:", r.stderr[-800:])

    report.update({
        "f2p_failed_before": sum(b.get(t) in ("FAILED", "ERROR") for t in f2p),
        "f2p_passed_after": sum(a.get(t) == "PASSED" for t in f2p),
        "p2p_passed_after": sum(a.get(t) == "PASSED" for t in p2p),
        "f2p": len(f2p), "p2p": len(p2p),
        "unparsed_ids": [t for t in f2p + p2p if t not in a][:5],
    })
    ok = (report["base_commit_ok"] and report["test_patch_applied"] and report["gold_patch_applied"]
          and report["f2p_failed_before"] == len(f2p)
          and report["f2p_passed_after"] == len(f2p) and report["p2p_passed_after"] == len(p2p))
    report["ok"] = ok
    print(f"[probe] FAIL_TO_PASS failing before: {report['f2p_failed_before']}/{len(f2p)}, "
          f"passing with the gold patch: {report['f2p_passed_after']}/{len(f2p)}; "
          f"PASS_TO_PASS passing: {report['p2p_passed_after']}/{len(p2p)}")
    if report["unparsed_ids"]:
        print(f"[probe] ids not found in pytest output (first 5): {report['unparsed_ids']}")
    print(f"[probe] {'OK - the chain works end to end' if ok else 'NOT OK'}")
    print(json.dumps(report))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
