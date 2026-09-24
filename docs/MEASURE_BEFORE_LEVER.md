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
| **0b — execute** | After a plan exists, what do events say? | `python -m bench.failure_taxonomy_0b` | **A** args/slot-fill · **X** parse · **I** infra · **F** flake · **Q** patch failed verify |

0a never sees sandbox/fleet. 0b never decides « add a ninth tool » — that is 0a’s job.

```bash
cd packages/engine
python -m bench.failure_taxonomy                         # heuristic
python -m bench.failure_taxonomy --model --csv out/taxonomy_p0a.csv
python -m bench.failure_taxonomy_0b --csv out/taxonomy_p0b.csv
python -m bench.failure_taxonomy_0b --live --csv out/taxonomy_p0b_live.csv
```

`--live` costs Nemotron calls; fleet/sandbox stay mock unless you change env.
Probes set `RETRY_DELAY_S = 0` so empty-patch retries do not sleep.

## Label definitions

| Code | Means | Typical evidence |
|------|--------|------------------|
| **V** | Useful tool is outside the fixed 8 | Human gold: `gcs_upload`, `gpu_provision`, browser… |
| **P** | The 8 suffice; plan names/order wrong | `plan` / `plan_degraded` vs gold list |
| **A** | Slot-fill / args bad | `slotfill_off_target`, `slotfill_bad_flags`, `slotfill_rejected`, `slotfill_empty` |
| **X** | Reply unusable as structured output | `patch_unparsed` (prose, hunks without `--- a/`) |
| **I** | Fleet / sandbox / env | `gpu_pressure`, `gpu_remediation`, `fix_unjudged`, … |
| **F** | Model flaked (empty / recovered on retry) | `patch_empty`, `patch_retry_succeeded` |
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
| **Q** dominates (live) | Patch quality / verify loop (`docs/FIX_LOOP.md`) | Treat as « need more tools » |

Planted probes (0b scripted `chat_fn`, 0a `vocab_gap` rows) prove the
**classifier** works. They must **not** be read as field frequencies. For
rates, use `--model` / `--live` rows alone, or a human-labelled ticket corpus.

## Snapshot that justified keeping this method (2026-09-04)

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
  **256**; patch default **2048**, override ``NGE_PATCH_MAX_TOKENS`` or
  ``NGE_NEMOTRON_MAX_TOKENS``).
- Per-model usage is logged to ``packages/engine/out/nemotron_usage.jsonl`` and
  printed at the end of ``--live`` / LLM benches.
- LLM benches require ``--i-know-cost``
  (``retry_distribution``, ``mission_phrasings --llm``, ``failure_taxonomy_0b --live``).
- A patch cut by the ceiling emits ``patch_truncated`` (not retried as empty).
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
