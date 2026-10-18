# Real bugs — measuring the loop on bugs we did not write

> Started 2026-10-18. Step 0 done; steps 1–3 after the submission (2026-10-30).

Why: the live film is proven on six bugs we seeded ourselves (`bench/bugbench`), and
it is saturated — 7 runs, 37/42 verified, 37/37 hold the hidden cases. No change to
the loop can show a gain there, and seeded bugs say little about real ones.

## The exercise: test-guided repair on SWE-bench Verified

Each SWE-bench task is a bug once fixed in a real project: the repository frozen at
the commit before the fix, the issue, the tests the real fix added (`FAIL_TO_PASS`)
and the ones that must not break (`PASS_TO_PASS`), and a Docker image per task.

The engine starts from failing tests, so the exercise is **test-guided repair**: the
model sees the issue *and* the failing tests. That is easier than standard SWE-bench,
where the model sees the issue only — the number will not be comparable to the
leaderboard and must not be presented as a SWE-bench score. Where a task has two or
more `FAIL_TO_PASS` tests, some stay hidden from the model and serve as the held-out
check, as in bugbench.

## Step 0 — can a Token Factory sandbox run a real task? Yes

`bench/swebench_probe.py` replays a task with its **historical fix** (no model call):
the task's tests are added, `FAIL_TO_PASS` must fail; the real fix is applied, it
must pass, with every `PASS_TO_PASS` test still green.
`evidence/swebench_probe_20261018.txt`:

| task | image ready | whole run | `FAIL_TO_PASS` fails, then passes | `PASS_TO_PASS` |
|---|---|---|---|---|
| `pallets__flask-5014` | 0.4 s | 14.4 s | 1/1 → 1/1 | 59/59 |
| `psf__requests-5414` | 0.4 s | 26.5 s | 1/1 → 1/1 | 130/130 |

What it took:
- The official image (`swebench/sweb.eval.x86_64.<id>`, ~1.1 GB on Docker Hub) is used as
  the sandbox image as-is; the repository is in `/testbed`, the task's Python in
  `/opt/miniconda3/envs/testbed`.
- **One command per sandbox.** A ContreeSDK run is disposable: a second command on the
  same session raises `DisposableImageRunError`. The engine already works this way;
  the first probe did not, and failed on its second step.
- The image adds one commit (« SWE-bench ») on top of the task's base commit: the base
  is `HEAD~1`, which the probe now checks.

## Next steps (after 2026-10-30)

| step | what | cost |
|---|---|---|
| 1. Adapter | `bench/swebench_runner.py`: task image → failing tests → the engine's fix loop (patch applied in `/testbed`, the issue text in the prompt) → verification on `FAIL_TO_PASS` + `PASS_TO_PASS` → attempt archive | 1–2 days |
| 2. First number | 20–30 tasks from light projects (requests, flask, pytest, pylint) | a few dollars of Nemotron |
| 3. Use it | the attempt archive names why each failure failed; that decides which step of the self-repair plan (typed verdict, self-repair, best-of-N, test check) comes first | 0 |

## What this does not do

- It does not measure standard SWE-bench: the model is shown the failing tests.
- Contamination: Verified's bugs predate 2023; Nemotron may have seen their fixes. A
  good score there would flatter the loop. Newer tasks (SWE-bench Pro) come later.
- Step 0 ran two tasks from small projects. Large ones (django, sympy) have heavier
  images and test suites; their run times are unmeasured.
- Repository navigation is not built: today the model sees the traceback and the
  files it touches, which is likely to be the first limit on real bugs.
