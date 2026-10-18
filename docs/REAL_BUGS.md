# Real bugs — measuring the loop on bugs we did not write

> Started 2026-10-18. Steps 0 and 1 done (step 1 smoke-tested on 2 tasks); steps 2–3 after the
> submission (2026-10-30).

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

## Step 1 — the adapter, smoke-tested on 2 tasks

`bench/swebench_runner.py`, per task: (1) a sandbox on the task's image adds its tests,
runs the visible `FAIL_TO_PASS` tests and lists the source files; (2) Nemotron picks up to
3 files to read - a reply typed by a strict `json_schema`, which Token Factory enforces;
(3) a sandbox prints them, numbered; (4) Nemotron writes the diff from the issue, the
failing output and that exact text; (5) a sandbox adds the tests, applies the diff and
runs every test file the task touches. Resolved = the task's own criterion. Every attempt
goes to the archive (`out/swebench/attempts/`).

Two tasks, seven passes (`evidence/swebench_smoke_20261018.csv`, attempt index
`evidence/swebench_attempts_20261018.jsonl`):

| patch setting | alignment | `flask-5014` | `requests-5414` |
|---|---|---|---|
| reasoning on, 8 192 tokens | — | no diff: reasoning used all 8 192 | no diff, same |
| reasoning on, 32 768 | — | refused by `git apply` | wrong cause, test still fails |
| reasoning off, 8 192 | — | refused by `git apply` | wrong cause, test still fails |
| reasoning on, 32 768 | context retyped | refused | wrong cause |
| reasoning off, 8 192 | context retyped | **resolved** | wrong cause |
| reasoning on, 32 768 | retyped + balanced | refused: the diff changes nothing | wrong cause |
| reasoning off, 8 192 | retyped + balanced | **resolved** | sandbox error (`ContreeImageStateError`) |

What it showed:
- **Reasoning eats the patch budget on real code**, as it did in September: at 8 192
  tokens both diffs were all reasoning. At 32 768 a diff comes, but twice of three the
  flask fix was written as *context* - no `+` or `-` line - which now reads « diff changes
  nothing ». With reasoning off the diff comes in ~10 s, for a third of the cost.
- **The model found the fix; the format lost it.** Its `flask-5014` diff was right, at
  « line 1 » with context typed 4 spaces too shallow, while the lines it *added* were
  indented right (the same pattern as the archived engine run of 2026-10-18). The adapter
  now retypes context and removed lines from the file (ignoring whitespace to find them),
  fixes the start line, and never touches added lines. Replayed on the archived flask
  diffs without a new model call, 3 of 4 then applied; the fourth changes nothing.
- **`git apply` anchors a hunk with less context after than before to the end of the
  file**: a diff ending on an added line was refused at line 193 of 621. The adapter
  balances the context with the file's own lines.
- **`requests-5414` needs the right cause**: the model edited `adapters.py`, then the IDNA
  encoding; the real fix rejects a host starting with `.` in `prepare_url`. No format
  repair helps there.
- One `ContreeImageStateError` mid-run: the adapter caught it and went on; the sandbox
  layer does not retry that error class yet.

Not a result yet: two tasks, a handful of samples, one resolved task. The alignment lives
in the adapter only - the engine's loop and the film are unchanged.

## Next steps (after 2026-10-30)

| step | what | cost |
|---|---|---|
| 1. Adapter | done, smoke-tested (above) | — |
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
