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
| context that exists nowhere in the file | refused before a node is provisioned |

## Why a patch was not produced

Three causes that used to share one name:

| event | `why` | retried? |
|---|---|---|
| `patch_empty` | model returned nothing | yes — 3 attempts, 2s backoff |
| `patch_unparsed` | hunks with no file header | no |
| `patch_unparsed` | no diff in the reply | no |

Only an empty answer is flakiness worth another call: measured, the same prompt
returned nothing four times in one run and answered twice a few minutes later,
while a 5541-char and a 1500-char version of it both succeeded — so it is the
service, not the request. A refusal is a considered reply; asking again buys
the same answer.

## What this does not do

- The verified suite is `packages/nodus`. A patch touching `packages/engine`
  is not checked by it.
- The success rate is noisy: consecutive live runs have scored 0/3 through 2/3.
  A single run measures nothing; only the mechanisms are stable.
- Hunks with no file header are not recovered. Guessing the target file would
  apply the diff to the wrong one.
