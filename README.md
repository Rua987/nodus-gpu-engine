# Nodus-GPU Engine

[![engine-tests](https://github.com/Rua987/nodus-gpu-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/Rua987/nodus-gpu-engine/actions/workflows/ci.yml)
[![python](https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12-blue)](packages/engine/pyproject.toml)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![tests](https://img.shields.io/badge/tests-555%20passing-brightgreen)](packages/engine/tests)

**Agentic engineering platform — Nebius "Coding & Agentic Engineering" track.**

A deterministic local planner decides *what* to do, Nemotron (tier-routed) decides
the *hard parts*, and a fleet of Nebius GPUs + Token Factory sandboxes actually
*runs the work* — isolated, monitored, and re-provisioned by the engine itself
when a node throttles.

```
Nodus 324M planner   ──▶  ordered tool names             [ brain / DSL ]
Nemotron @ Nebius    ──▶  routing: Ultra / Super / Nano  [ inference   ]
GPU fleet (Nebius)   ──▶  provision / monitor / migrate  [ infrastructure ]
Token Factory        ──▶  isolated exec + capability jail [ execution   ]
```

> **The 324M planner needs its weights.** They are ~988 MB and not in git, so
> without them the planner step falls back to a hand-written keyword heuristic
> — a real fallback, but *not* the model. Every run says which one produced the
> plan (`plan(nodus-324m)` vs `plan(heuristic)`, plus a `[planner] WARNING`
> line and a `plan_degraded` event), so this is never silent. To use the model:
>
> ```bash
> python -m nge.fetch_ckpt      # from packages/engine — downloads, verifies, configures
> ```
>
> It pulls the published asset (release `v1.0.0` of `Rua987/nodus`, ~988 MB),
> checks its SHA256 and writes `.nodus_plan_ckpt`. Not in Git LFS on purpose:
> the free tier is 1 GB of storage and 1 GB of bandwidth per month, so one
> clone would exhaust it. `--check` reports what is configured without
> downloading. If you already have the file:
>
> ```bash
> echo /path/to/checkpoint_sft_plan_v5.pt > packages/engine/.nodus_plan_ckpt
> ```
>
> The two disagree — on `"Find the config file and read it"` the model answers
> `['bash']` where the heuristic guesses `['glob', 'read_file']`.

## Layout

| Path | What |
|------|------|
| [`packages/engine/`](packages/engine/) | **The project.** All new code (`nge`): Nebius backend, tier router, GPU fleet + Token Factory sandbox layers, capability jail, orchestrator, demo. |
| [`packages/nodus/`](packages/nodus/) | **Vendored, unmodified** snapshot of <https://github.com/Rua987/nodus> — the Nodus runtime (ReAct executor, `bridge/`, backends, MCP). The `nebius:` backend is added by a reversible monkey-patch, never an edit. See [`docs/VENDORING.md`](docs/VENDORING.md). |


The auto-fix loop's verification rules each come from a live run that broke without them — including a patch that repaired its target test while breaking 28 others, twelve of them path-security checks. The evidence is in [`docs/FIX_LOOP.md`](docs/FIX_LOOP.md), and
[`docs/ENVIRONMENTS.md`](docs/ENVIRONMENTS.md) records where this has actually been run, what each environment caught, and what is still
exercised on only one machine. Before picking the next upgrade lever (more
tools, more retries, slot-fill, infra), re-run the failure taxonomy in
[`docs/MEASURE_BEFORE_LEVER.md`](docs/MEASURE_BEFORE_LEVER.md)
(`bench/failure_taxonomy*.py`).

Every run and bench the docs cite — the judge film, the live reports, the
CSVs — is kept in [`packages/engine/evidence/`](packages/engine/evidence/README.md)
with its provenance; `tests/test_evidence.py` keeps the citations honest.

## Quick start (mock — no credentials, no network)

```bash
cd packages/engine
pip install -r requirements.txt
python -m pytest -q                 # 555 tests; ~26 skip without the optional cloud SDKs
python -m nge.demo_nebius --mock    # -> out/report_<ts>.md  +  .html (self-contained)
```

Judge oral script (`--mock --watch`): [`packages/engine/docs/JUDGE_DRY_RUN.md`](packages/engine/docs/JUDGE_DRY_RUN.md).

The mock run: `plan (→Ultra)` → `gpu_provision(3×H100)` → 3 sandboxes run a
sharded pytest (commands vetted by the jail) → a hot node throttles → the engine
re-provisions and migrates that shard by itself → **the code agent proposes a
patch per failure, applies it in a fresh sandbox and re-runs the whole suite,
keeping only what fixes its target without breaking anything else** → `gpu_release` → consolidated report (triage + `fixes/*.patch`).

```bash
python -m nge.demo_nebius --mock --watch    # live fleet view: util/temp bars, migration, fixes
```

## The differentiators (all real in the mock demo)

1. **Code + Infrastructure in one loop** — `orchestrator._react_to_pressure`:
   GPU telemetry drives compute reallocation while the plan executes.
2. **A code agent, not just a test runner** — `orchestrator._attempt_fixes`:
   propose a patch → apply it with `patch-ng` in a fresh GPU sandbox → re-run
   the **whole suite** and keep only what fixes its target *without breaking
   anything else*. A patch that repairs one test and breaks another is
   rejected and named. Unverifiable failures are flagged for a human.
   See [`docs/FIX_LOOP.md`](docs/FIX_LOOP.md) for the evidence behind each
   rule — including the patch that fixed its target while breaking 28 tests.
3. **Multi-tier Nemotron routing** — `nge/router.py`: Ultra 550b (plan),
   Super 120b (slot-fill / triage / patch), Nano 30b (fast telemetry checks).
4. **Deterministic execution + capability jail** — `nge/policy.py` gates every
   LLM-proposed shell command; the runtime stays strict and reproducible.

Full judge-facing doc: [`packages/engine/docs/NEBIUS_TRACK.md`](packages/engine/docs/NEBIUS_TRACK.md).
Architecture: [`packages/engine/docs/ARCHITECTURE.md`](packages/engine/docs/ARCHITECTURE.md).
Judge dry-run script: [`packages/engine/docs/JUDGE_DRY_RUN.md`](packages/engine/docs/JUDGE_DRY_RUN.md).
The 324M plan gates auto-fix: without `edit_file`/`write_file` in the plan, the
engine triages only (`plan_gated_autofix`).

## Live path

`--live` runs for real: the 324M planner, Nemotron (tier-routed) and Token
Factory sandboxes, all at once. `NebiusFleet` and `TokenFactorySandbox` are
wired and exercised — the CI job `live-smoke` runs the whole pipeline on
Ubuntu against real sandboxes on demand and on a weekday cron.

```bash
cd packages/engine
python -m nge.sandbox.token_factory                    # auth + spawn + exec
NGE_FLEET_MODE=mock python -m nge.demo_nebius --live   # no GPU allocated
```

`NGE_FLEET_MODE=mock` keeps the fleet ledger simulated, so the cost is the
Nemotron calls plus the sandboxes the shards run in. Needs `NEBIUS_API_KEY`
and `NEBIUS_PROJECT_ID` (files under `packages/engine/` or environment).
Every `nebius:` call is capped (`max_tokens`, default 2048; patches 8192) and
usage — reasoning tokens included — is appended to `out/nemotron_usage.jsonl`.
Nemotron 3 reasons inside that same budget, so short replies (slot-fill,
mission) run with reasoning off and patches with it on: measured, not guessed —
see *Reasoning eats the token ceiling* in [`docs/FIX_LOOP.md`](docs/FIX_LOOP.md).
LLM benches require `--i-know-cost`.

## License

MIT — see [`LICENSE`](LICENSE). The vendored `packages/nodus/` subtree is a snapshot of
[Rua987/nodus](https://github.com/Rua987/nodus), also MIT (Copyright (c) 2024 Temple IAM), with its own
[`packages/nodus/LICENSE`](packages/nodus/LICENSE). (That note used to sit at the end of `LICENSE`,
which stopped GitHub from recognising the file as MIT.)
