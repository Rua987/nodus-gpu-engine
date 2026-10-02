# The auto-fix loop, and why it verifies the way it does

The code agent proposes a patch, applies it in a fresh sandbox, and re-runs the
tests. Every rule below was added because a live run broke without it — this
file keeps the evidence, since run artefacts (`packages/engine/out/`) are
gitignored and the reasoning is otherwise invisible in the code.

## Verification runs the whole suite

Not `pytest -k <the failing test>`, and not even that test's own file.

On 2026-09-03 Nemotron produced this patch for
`test_nodus_tools.py::TestRepairLlmFilePath::test_drive_underscore_prefix`:

```diff
--- a/packages/nodus/nodus_tools.py
@@ -1240,9 +1240,10 @@
-    s = _collapse_doubled_first_segment(s)
-    s = _strip_spurious_basename_underscore(s)
-    return s
+    s = _collapse_doubled_first_segment(s)
+    s_norm = s.replace('\\', '/')
+    s = _strip_spurious_basename_underscore(s_norm)
+    return s
```

It normalises `\` to `/` and never restores the separators, so
`repair_llm_file_path` starts returning forward-slash paths. That function sits
upstream of all path confinement, and the patch broke **28 tests**:

| broken | what it guards |
|---|---|
| `TestConfine` (3) | path confinement |
| `TestDispatchConfinement` (9) | traversal and escape refusal |
| `TestDispatchTool` (10) | read / write / edit / glob / grep |
| `TestRepairLlmFilePath` (4) | neighbouring cases of the patched function |
| `test_secret_redaction.py` (2) | **a different file** |

**The patch fixed its target test.** Under `-k <test>` it reported `fix OK`, so
an automated fix would have been presented as verified while disabling twelve
path-security checks. And two of the casualties live in another file, so
scoping the check to the test's own file would not have caught it either.

Interestingly the same model, same run, produced a second patch for the same
test that *did* restore the separators (`s_stripped.replace('/', '\\')`). The
mistake is not systematic — which is exactly why the loop cannot rely on the
model being careful.

### Measured: how often a "fixed" patch was really a regression

Four live runs after the check was widened, counting patches whose target test
passed against patches that also broke something else:

| run | target fixed | regressions |
|---|---|---|
| 1 | 1 | 1 |
| 2 | 2 | 2 |
| 3 | 1 | 1 |
| 4 | 1 | 1 |
| **total** | **5** | **5** |

Every patch that repaired its target broke something else. Under the old
`-k <test>` check all five would have been reported `fix OK`, which means the
1/3 and 2/3 scores recorded before the widening were very likely all false
positives — the drop to 0/3 is the measurement getting honest, not the system
getting worse.

Read this as a property of *this corpus*, not a general rate: the failures all
sit in `repair_llm_file_path`, Windows path tests running on Linux, and the
model "fixes" them by normalising separators, which mechanically breaks the
neighbouring cases of the same function. Another codebase would give another
ratio. What generalises is only that the narrow check could not see any of it.

### The criterion is failure sets, not the exit code

The suite legitimately contains other red tests, so a non-zero exit proves
nothing. Instead:

    before   = failures the shards already observed
    after    = failures once the patch is applied
    verified = target absent from `after`, and (after - before) empty

A pre-existing failure is not a regression. A new one is, and it is named in
the report and in a `fix_regression` event.

### Files nobody ran are not judged

A shard that was skipped (`shard_empty`) or died (exit 126/127/4) leaves no
baseline for its files, so a pre-existing failure there would look like damage.
`covered` tracks the files a shard actually executed with usable pytest output;
anything outside it is reported as `fix_unjudged` rather than blamed on the
patch. Missing information must not become a verdict.

### The baseline must be complete

`before` is only as good as the shard runs that produced it. Once slot-fill
stopped being starved by reasoning (2026-10-01), Nemotron put `-x` on every
shard — the prompt itself listed it as allowed. Each shard stopped at its first
failure: the run saw 2 failures where the suite has 5, and the whole-suite
re-run during verification then reported the 3 hidden ones as damage done by
the patch (`test_connect_mcp_forwards_org_id_env`, already failing before any
patch, was listed under `broke`). Options that change *what runs* — `-x`,
`--maxfail`, `-k`, `-m`, `--deselect`, `--ignore`, `--lf`, `--co`, and `--pdb`,
which would park the sandbox on a prompt — are now refused (`slotfill_narrowed`)
and the shard keeps the template command. Only options after the `pytest` word
count: the `-m` of `python -m pytest` is Python's, not pytest's marker filter.

### An empty sandbox is not a pass

With no stdout, "the target test is not in the failure list" is vacuous. That
is the shape of the `git: not found` bug, where a sandbox that ran nothing
looked exactly like a clean run. Rejected as
`sandbox produced no output - nothing ran`.

## The sandbox is bare

`python:3.12-slim` has no pytest, no dependencies, no git, no patch, and none
of our code. Probed, not assumed: only `diff` is present. So the fix sandbox
gets the same treatment as a shard — the payload, the requirements, PYTHONPATH
— and applies patches with `patch-ng`, which pip can install.

## Model output is repaired before use, not trusted

Each of these silently lost a correct patch in a live run:

| shape | handling |
|---|---|
| bare `@@` header | given counts; `_relocate_hunks` finds the real position |
| invented hunk counts (`@@ -35,7` above 4 lines) | recomputed from the body |
| no trailing newline | added (`patch stream is incomplete!`) |
| `diff --git` envelope | dropped — patch-ng strips `a/` itself, so a fixed `--strip 1` removed one component too many |
| whole block indented | dedented, preserving the ` `/`-`/`+` column |
| file header without `--- `/`+++ ` (`a/x.py` then `b/x.py`, or both on one line) | prefixes restored, only when a hunk follows — with reasoning off, 6/6 live diffs had this shape |
| context that exists nowhere in the file | refused before a node is provisioned |

## The same lesson applies to every model reply

`nemotron_plan_fallback` (reached only with `NGE_PLAN_FALLBACK=nemotron`) had
none of this: it called `json.loads` on the whole reply. Measured against five
realistic answers, four were silently dropped — a ```json fence, an unlabelled
fence, prose around the array, and an empty reply. `llm_text.json_array()`
handles them the way `unified_diff` handles diffs. Tool names outside the fixed
vocabulary are dropped too: the executor only knows those eight, so an invented
name would fail downstream instead of here.

## Why a patch was not produced

Three causes that used to share one name:

| event | `why` | retried? |
|---|---|---|
| `patch_empty` | model returned nothing | yes — 4 attempts, 2s linear backoff |
| `patch_unparsed` | hunks with no file header | no |
| `patch_unparsed` | no diff in the reply | no |
| `patch_truncated` | finish_reason=length · *reasoning used the whole budget* when nothing reached `content` | no — a cut reply is cut again |

Only an empty answer is flakiness worth another call: measured, the same prompt
returned nothing four times in one run and answered twice a few minutes later,
while a 5541-char and a 1500-char version of it both succeeded — so it is the
service, not the request. A refusal is a considered reply; asking again buys
the same answer.

**Why four.** `bench/retry_distribution.py` repeats one real call up to six
times and records which attempt finally answers. Over 20 trials:

| attempt | answered | cumulative |
|---|---|---|
| 1 | 14 | 70% |
| 2 | 5 | 95% |
| 3 | 0 | 95% |
| 4 | 1 | 100% |
| 5–6 | 0 | 100% |

Three attempts reach 19/20, four reach 20/20, and nothing was ever recovered at
five or six — so a fifth buys nothing. The extra call only happens when three
have already failed, which was 1 trial in 20.

Two caveats. n=20, so a single success at rank 4 is thin evidence. And the
service was in a good phase (70% first try) while an earlier run had 16 empty
replies out of 26 — this measures a good window, not a bad one. Re-run the
bench rather than trusting the table if the retry behaviour matters to you.

## Reasoning eats the token ceiling

Nemotron 3 Super reasons before it answers, the reasoning comes back outside
`content` (the vendored normaliser drops it), and **it counts against
`max_tokens`**. The 2026-09-13 live report said "Super truncated (2048 tokens,
0-char reply)" on every patch; that was not a long diff, it was 2048 tokens of
reasoning and no diff at all. Slot-fill at 256 was the same: 256/256 reasoning,
an empty reply, every call — logged as `slotfill_empty`, so the taxonomy filed a
budget problem as an argument problem.

The switch is `chat_template_kwargs: {"enable_thinking": false}` (a system
`/no_think` is ignored). Super, Nano and Ultra all accept it. It is set per call
class — `NGE_THINKING_SHORT` (slot-fill, mission, plan fallback) and
`NGE_THINKING_PATCH`, `on` / `off` / `model` — and `reasoning_tokens` is now in
the usage ledger and on the `*_truncated` events.

**Measured** with `bench/thinking_ab.py` (CSVs, every run's event log and the
verified patch in [`packages/engine/evidence/`](../packages/engine/evidence/README.md)):
real Token Factory sandboxes, the real
suite (5 real failures per run), simulated fleet, heuristic plan so autofix
opens; arms interleaved run by run, 3 runs each.

Short replies (slot-fill), all runs of both series:

| reasoning | usable slot-fills |
|---|---|
| on (model default) | **0/6** — 256/256 tokens of reasoning, empty reply |
| off | **12/12** |

Patches (second series, after the two fixes below):

| reasoning · ceiling | diffs produced | cut | invented context | verified | output tokens | $ est. |
|---|---|---|---|---|---|---|
| on · 2048 (before) | 0/9 | 9 | — | 0 | 18 945 | 0.024 |
| off · 2048 | 9/9 | 0 | **4** | 0 | 2 912 | 0.010 |
| on · 8192 | 7/9 | 2 | 0 | **1** | 61 845 | 0.063 |

Defaults chosen from this: **short replies without reasoning, patches with
reasoning and an 8192 ceiling** (`THINKING_DEFAULTS`, `PATCH_MAX_TOKENS` in
`nge/backends/nebius.py`). Without reasoning, 4 of 9 diffs cited code that is
not in the file and were refused before a sandbox was spent; with it, none did,
and the one verified fix of the whole bench came from that arm — it made
`repair_llm_file_path` split Windows paths with `ntpath` on Linux too, target
fixed, zero regressions on the whole suite. `NGE_THINKING_PATCH=off` stays the
cheap option: every reply parsed, about a sixth of the cost (a twentieth of
the output tokens), two to three times faster per run.

Measuring this surfaced two bugs that starved slot-fill had been hiding:

- **`-x` on every shard** — see *The baseline must be complete* above. In the
  first series, two 8k-arm patches fixed their target and "broke" exactly two
  tests each — both of them failures `-x` had hidden. With a complete baseline
  they would have been verified; `-x` got two good patches rejected. One
  short_off patch "broke" 32 tests: 2 hidden by `-x`, 30 real damage, rightly
  rejected.
- **Diff headers without `--- `/`+++ `** — every reasoning-off diff came back as
  `a/x.py` / `b/x.py`. Restored now (table above); before that the off arm read
  0/6 parsed, after it 9/9.

Caveats, so the table is not over-read:

- n = 3 runs per arm. 1 verified against 0 is one patch, not a rate.
- The five live failures are tests written for Windows (backslash paths in
  `test_nodus_tools.py`, an environment-dependent pair in
  `test_nodus_grafana.py`); all five pass on Windows. "Verified" therefore
  cannot discriminate between arms on this failure set — what the bench does
  measure is whether a usable, honest diff comes back, and at what cost.
- The verified patch strips a leading `_` from *any* basename. The suite stays
  green, but that is broader than the test asked for.

## What this does not do

- The verified suite is `packages/nodus`. A patch touching `packages/engine`
  is not checked by it.
- The success rate varies run to run (0/3 through 2/3), so a single run
  measures nothing. But not all of that spread was noise: the scores recorded
  *before* verification was widened counted patches that broke other tests, and
  every one of the five measured since turned out to be a regression. Treat any
  figure from before that change as an upper bound, not a result.
- Hunks with no file header are not recovered. Guessing the target file would
  apply the diff to the wrong one. (A header that is present but lost its
  `--- `/`+++ ` prefixes is a different case, and is restored.)
- The reasoning defaults were measured on one failure set (Windows-only tests,
  see above). Re-run `bench/thinking_ab.py` on a different target before
  treating them as settled.
