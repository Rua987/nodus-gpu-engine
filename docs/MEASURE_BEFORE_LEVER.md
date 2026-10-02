# Measure before picking a lever

Every tempting upgrade to the Nodus-GPU Engine (ninth planner tool, more
retries, better slot-fill, Docker for the 324M checkpoint…) looks urgent until
you count **where failures actually come from**. This file is the decision
method. The benches exist so the method can be re-run instead of believed.

Analogues already in-repo: retry count was guessed at 3, then measured at 4
(`bench/retry_distribution.py`); mission regexes looked green until
`bench/mission_phrasings.py` faced unseen phrasings. Same rule here for
*which subsystem to improve*.

## Two layers (do not mix)

| Phase | Question | Instrument | Labels |
|-------|----------|------------|--------|
| **0a — plan** | Wrong *names*, or tool *missing* from the 8? | `python -m bench.failure_taxonomy` | **V** vocab gap · **P** bad plan · **OK** |
| **0b — execute** | After a plan exists, what do events say? | `python -m bench.failure_taxonomy_0b` | **A** args/slot-fill · **X** parse · **I** infra · **F** flake · **T** token budget · **Q** patch failed verify |

0a never sees sandbox/fleet. 0b never decides « add a ninth tool » — that is 0a’s job.

```bash
cd packages/engine
python -m bench.failure_taxonomy                         # heuristic
python -m bench.failure_taxonomy --model --csv out/taxonomy_p0a.csv
python -m bench.failure_taxonomy_0b --csv out/taxonomy_p0b.csv
python -m bench.failure_taxonomy_0b --live --i-know-cost --csv out/taxonomy_p0b_live.csv
python -m bench.thinking_ab --i-know-cost --runs 3 --csv out/thinking_ab.csv
python -m bench.thinking_ab --i-know-cost --runs 3 --target bugbench   # known answers
```

`--live` costs Nemotron calls; fleet/sandbox stay mock unless you change env.
Probes set `RETRY_DELAY_S = 0` so empty-patch retries do not sleep.

## Label definitions

| Code | Means | Typical evidence |
|------|--------|------------------|
| **V** | Useful tool is outside the fixed 8 | Human gold: `gcs_upload`, `gpu_provision`, browser… |
| **P** | The 8 suffice; plan names/order wrong | `plan` / `plan_degraded` vs gold list |
| **A** | Slot-fill / args bad | `slotfill_off_target`, `slotfill_bad_flags`, `slotfill_narrowed`, `slotfill_rejected`, `slotfill_empty` |
| **X** | Reply unusable as structured output | `patch_unparsed` (prose, hunks without `--- a/`) |
| **I** | Fleet / sandbox / env | `gpu_pressure`, `gpu_remediation`, `fix_unjudged`, … |
| **F** | Model flaked (empty / recovered on retry) | `patch_empty`, `patch_retry_succeeded` |
| **T** | Reply cut by `max_tokens` — reasoning included | `slotfill_truncated`, `patch_truncated` (`reasoning_tokens` on the event) |
| **Q** | Diff parsed but verification rejected it | `fix_rejected`, `fix_regression` |

Root-cause only: one label per failure — the one that, fixed, would have been enough.

## Decision table (after a measured distribution)

| If… | Then | Do **not** |
|-----|------|------------|
| **V** &lt; ~10% of plan misses (or V only from planted cases) | Keep the 8-tool vocab | Re-train a 9th tool |
| **P** dominates plan misses | Better corpus / checkpoint on the **same** 8 (upstream `nodus`) | Expand vocabulary first |
| **A** dominates executor events | Harden slot-fill / jail / command templates | Touch the 324M planner |
| **X** dominates | Parse / prompt format | Add retries blindly |
| **I** dominates | Engine fleet/sandbox path | Blame the planner |
| **F** dominates | Revisit retry / backoff (already measured → **4**) | Jump to 5 without a new distribution |
| **T** dominates | Token budget: reasoning on/off per call class, `max_tokens` (`bench/thinking_ab.py`) | Add retries — a cut reply is cut again |
| **Q** dominates (live) | Patch quality / verify loop (`docs/FIX_LOOP.md`) | Treat as « need more tools » |

Planted probes (0b scripted `chat_fn`, 0a `vocab_gap` rows) prove the
**classifier** works. They must **not** be read as field frequencies —
and since 2026-10-01 the 0b bench only draws its « Décision » from the
`--live` run (before, it summed probes + mock baseline and always said « I »). For
rates, use `--model` / `--live` rows alone, or a human-labelled ticket corpus.

## Snapshot that justified keeping this method (2026-09-04)

Data: `packages/engine/evidence/taxonomy_p0_*.csv`, `taxonomy_p0b*.csv`.

**0a** — 24 cases, exact match to gold plans:

| Source | OK | P | V | Among non-OK |
|--------|----|----|---|--------------|
| Heuristic | 29% | 46% | 25% | P 65% |
| 324M (`--model`) | 21% | 54% | 25% | P 68% |

V rows were deliberately planted (GCS, GPU, browser…). Exact match is harsh
(near-misses count as P). Decision under those caveats: **do not widen the 8;
if anything, improve planning on the 8.**

**0b** — 9/9 deterministic probes emitted the expected bucket (instrument OK).
One `--live` Nemotron run (2 shards, fleet+sandbox mock): **A=0 X=0 F=0**,
**Q=1** (`fix_rejected`), **I** only `sandbox_env`. Live signal that day:
patch verification quality, not slot-fill flake. **n=1** — re-run before
treating Q as a stable majority.

Related measured lever (not taxonomy, same rule):
`bench/retry_distribution.py` → four attempts, not five
(`nge/orchestrator.py` patch loop).

## Snapshot 2026-10-01 — the live signal was T, and the instrument could not see it

Hypothesis: « live slot-fill and patch failures are a token-budget problem —
Nemotron 3 Super's reasoning spends `max_tokens` before the answer starts ».

What the 0b bench said first (`--live`, 2 shards): `slotfill_empty` ×1, and
« Décision : Go engine infra ». Both wrong. The empty slot-fill was 256/256
reasoning tokens — a budget cut, filed under **A**. `patch_truncated` had no
bucket at all, so a run where every patch was cut read « X=0 F=0 ». And the
« infra » decision came from summing planted probes with the mock baseline.
Fixed: bucket **T**, `slotfill_truncated`, and the decision now uses the live
run only.

Then the matching bench, `bench/thinking_ab.py` (real sandboxes, real suite,
3 interleaved runs per arm): with the pre-change settings, **99%** of output
tokens were reasoning (19 384 / 19 595), and 14 of the 15 model calls were cut
by the ceiling — 0/6 slot-fills usable, 1/9 patches produced. **T**, not A. The table's lever for T is the token
budget, not retries: reasoning off for short replies, on with an 8192 ceiling
for patches. Numbers and caveats: `docs/FIX_LOOP.md`, *Reasoning eats the
token ceiling*. CSVs and every run's event log: `packages/engine/evidence/thinking_ab_20261001*.csv`,
`packages/engine/evidence/ab/`; the 0b live run:
`packages/engine/evidence/taxonomy_p0b_live_20261001.csv`.

Same rule as the retry count, twice over. The obvious fix (« turn reasoning
off ») was right for slot-fill and *undecided* for patches — and the first
patch result (off: 4/9 invented context) looked decisive until a second
failure set with known answers (`--target bugbench`, held-out checks) showed a
tie, 16/18 either way, with « invented context » now pointing the other way.
One bench on the wrong failure set would have shipped a conclusion the next
one reverses. Bugbench CSV: `packages/engine/evidence/thinking_ab_bugbench_20261001.csv`.

## How the engine should use this

Before opening a PR that changes planner vocab, retry depth, slot-fill
prompts, or jail policy:

1. State the hypothesis (« failures are mostly A »).
2. Re-run the matching phase (0a and/or 0b; `--live` if the claim is about Nemotron).
3. Paste the distribution + CSV path in the PR (or in this file under a new dated snapshot).
4. Only then implement the lever the table names.

If the distribution is flat or dominated by planted rows, **stop** — enlarge
the corpus or take another live sample; do not ship the upgrade.

### Nemotron cost guardrails

- Every `nebius:` call sets ``max_tokens`` (default **2048**; slot-fill/mission
  **256**; patch default **8192** since 2026-10-01 — patches reason first —,
  override ``NGE_PATCH_MAX_TOKENS`` or ``NGE_NEMOTRON_MAX_TOKENS``).
- Per-model usage is logged to ``packages/engine/out/nemotron_usage.jsonl`` and
  printed at the end of ``--live`` / LLM benches.
- LLM benches require ``--i-know-cost``
  (``retry_distribution``, ``mission_phrasings --llm``, ``failure_taxonomy_0b --live``).
- A patch cut by the ceiling emits ``patch_truncated`` (not retried as empty);
  a slot-fill cut by it emits ``slotfill_truncated``. Both carry
  ``reasoning_tokens``: Nemotron 3 reasons before answering, and those tokens
  count against the same ceiling.
- Reasoning per call class: ``NGE_THINKING_SHORT`` (slot-fill, mission, plan
  fallback) and ``NGE_THINKING_PATCH`` = ``on`` / ``off``; unset = the defaults
  in ``nge/backends/nebius.py`` (``THINKING_DEFAULTS``). Sent as
  ``chat_template_kwargs.enable_thinking``; a system ``/no_think`` is ignored.
- HTTP 429/5xx → ``model_unavailable``; **no** auto-failover Super→Nano.
- Router **tier** (ultra/super/nano) = role of the step; ledger **model** = id billed.
  DeepSeek is blocked under ``NGE_TRACK=nebius`` (hackathon path).

### PR checklist (internal — not a judge slide)

Paste into the PR body when the change touches the agent loop:

```
Hypothesis: …
Candidate label: V | P | A | X | I | F | Q
Evidence: event kinds / CSV path / bench command + date
Lever this PR changes: … (one area)
Explicitly NOT changing: …
```

Skip this checklist for typos, pure unit-test fixes, packaging, and docs that
do not alter runtime behaviour.

## Out of scope (on purpose)

- Docker / `fetch_ckpt` on Linux — environment coverage (`docs/ENVIRONMENTS.md`), not taxonomy.
- Editing vendored `packages/nodus/` — improve upstream, then re-vendor (`docs/VENDORING.md`).
- Replacing human gold in 0a with an LLM judge — would circularly trust the system under test.
- Judge-facing demo script — see `packages/engine/docs/JUDGE_DRY_RUN.md` (separate from this method).
