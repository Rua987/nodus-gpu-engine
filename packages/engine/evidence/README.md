# Evidence

Every run the docs cite, kept in git. `out/` is gitignored, so before
2026-10-01 a clone had none of these files while the Devpost text and the judge
script pointed at them.

Report names are UTC; the `.md` of each run holds its full event log as written
at run time — when an HTML and the log disagree, the log is the record. Nothing
here contains keys, project ids or local paths (scanned before commit).
`tests/test_evidence.py` fails if a doc cites a file that is not here, or if a
judge-facing claim stops matching its event log.

## Runs

| file | command | fleet / sandbox | shows | cited by |
|---|---|---|---|---|
| `report_20261003T233405Z` | `--mock --watch --watch-delay 2.0 --heuristic-plan` | mock / mock | **A2 judge film, current capture**: same result as below, header no longer claims a missing checkpoint, no double full stops | Devpost, JUDGE_DRY_RUN |
| `report_20260913T041721Z` | `--mock --heuristic-plan` | mock / mock | **A2 judge film** (earlier capture; its header wrongly says « checkpoint NOT FOUND »): autofix ON, migrate `nb-h100-02 → 03`, 2/3 verified on fresh nodes 04 / 05 | Devpost, JUDGE_DRY_RUN, backlog |
| `report_20260913T053458Z` | `--live --shards 1 --heuristic-plan` | Nebius / Token Factory | **Live B**: Contree `cpu-fallback`, heal gated, 5 failures, 3 patches cut at 2048 (0-char), 0/3 | Devpost, JUDGE_DRY_RUN |
| `report_20261002T055558Z` | `NGE_FLEET_MODE=mock --live --shards 2 --heuristic-plan` | mock / Token Factory | Same loop after the reasoning defaults: 5 failures, 3 diffs produced, 0 cut, 3 rejected by verification | JUDGE_DRY_RUN, backlog |
| `report_20260905T232100Z` | `--mock --heuristic-plan` | mock / mock | First 2/3 capture with migrate (M10) | NEBIUS_TRACK, backlog |
| `report_20260905T223331Z` | `--mock` (324M plan) | mock / mock | Plan gate OFF (`bash`, `brave_search`), migrate still happens (M9) | backlog |
| `report_20260905T211401Z` | `--live` (324M plan) | Nebius / Token Factory | `cpu-fallback`, remediations none, autofix gated off (C2, C8) | backlog |
| `compute_probe_20261003T231022Z.json` | `NGE_COMPUTE_SPAWN=1 python -m nge.fleet.compute probe --i-know-cost --max-minutes 15` | Nebius AI Cloud Compute VM | **Real GPU**: L40S in eu-north1, `probe_kind=nvidia-smi`, 27 °C, 67.8 W, `datacenter`; VM deleted at 192 s. Project, subnet, instance ids and the public ip redacted | COMPUTE_GPU, Devpost, JUDGE_DRY_RUN, backlog |
| `report_20261004T031503Z` | `NGE_COMPUTE_SPAWN=1 python -m nge.fleet.compute hybrid --i-know-cost --shards 2 --max-minutes 12` | Compute (2 × L40S) / Token Factory | **Phase 3 hybrid**: real `nvidia-smi` in each heal decision (25 °C, ~36 W, 0 %), `gpu_efficiency_skipped` ×2, no remediation, both VMs deleted. Lists one phantom failure, `test_connect_mc` — a line ContreeSDK cut at 64 KiB (see the replay). As written by the engine: it records no instance id, ip or project id. Its `capabilities` event still carries the old « skeleton » wording, fixed after the run (`dc6458f`) | COMPUTE_GPU, Devpost, JUDGE_DRY_RUN, backlog |
| `report_20261004T031503Z_rerender.html` | `python -m nge.report_rerender evidence/report_20261004T031503Z.md evidence/report_20261004T031503Z_rerender.html` | (re-render, no run) | The hybrid run above, re-rendered from its `.md` after the renderer learned `gpu_efficiency_skipped`, `autofix_skipped` and `shard_output_truncated`. Visible-text diff against the run-time HTML: only the real-GPU banner, those event lines, and the remediation / autofix sentences that now say why. `tests/test_report_rerender.py` checks the file is exactly what the command produces | Devpost |
| `report_20261004T221630Z`, `…222054Z`, `…222707Z` (+ `.holdout.json`) | `python -m nge.demo_nebius --live --watch --heuristic-plan --scenario scenarios/bugbench_live.json` (the first without `--watch`) | Nebius / Token Factory | **Live film (A3)**, three runs: 6 seeded bugs, real Nemotron patches, 5/6 verified each time, and every verified patch also passes the held-out cases (`.holdout.json`, written by the demo). Rejected: a diff citing code that does not exist (×2), a patch cut at 8192 tokens (×1). The first two ran before the console fix: their nodes are labelled `nb-h100-*` though they are CPU sandboxes, and their terminal showed a spurious token warning; the loop is the same | JUDGE_DRY_RUN, Devpost |
| `report_20261004T234436Z` | `NGE_COMPUTE_SPAWN=1 python -m nge.fleet.compute contention --i-know-cost --max-minutes 20` | Compute (3 × L40S) / compute (shards on the VMs) | **Phase 4, run 1**: declared induced load on node 0 (100 %, 324 W) → `busy` → placement refuses every node → a 3rd VM → migration. The re-run there had no files (pytest exit 4) and the GPU process listing was empty — both fixed after; shard 1 on an idle node passed (CUDA built and checked). No instance id, ip or project id in the report. Code `32ec244` | COMPUTE_GPU, backlog |
| `output_cut_replay_20261004.txt` | `python -m bench.output_cut_replay --i-know-cost` | — / Token Factory | Shard 0 of the run above, replayed at the SDK's 65 535-byte default (cut, fragment dropped by the fixed parser) and at 4 MiB (65 637 bytes, both real failures) | COMPUTE_GPU |

**`report_20260913T053458Z_honest.html` is a re-render, not the run-time
HTML.** `report_20260913T053458Z.html` is what the renderer of that day
produced, and it was wrong: "OK · 0 °C" for a CPU sandbox with no GPU probe,
and "no patch proposed" where the model had in fact been cut off. The
`_honest` file was rendered about 1 h 30 later from the same run with the renderer
that labels `cpu-fallback` and `patch_truncated`; no committed command produces
it. Its content matches the run-time event log in the `.md` (three
`patch_truncated` events, `max_tokens: 2048`, `reply_chars: 0`;
`probe_kind: cpu-fallback`). Both HTMLs are kept so the difference is visible.

Code version: the September runs used engine code that was uncommitted at the
time and later landed in `3497190` — the exact state at each run was not
recorded. The 2026-10-02 run used the code of `3e49336`; the 2026-10-03 Compute probe, `f92faf1`; the 2026-10-04 hybrid run, `251b6ad`; the
replay, the code of the commit that adds it (the output-cut fix).

## Benches

| file | what | cited by |
|---|---|---|
| `taxonomy_p0_heuristic.csv`, `taxonomy_p0_model.csv` | 0a plan taxonomy, 24 cases (2026-09-03) — 29/46/25 % and 21/54/25 % | MEASURE_BEFORE_LEVER, snapshot 2026-09-04 |
| `taxonomy_p0b.csv`, `taxonomy_p0b_live.csv` | 0b probes + one live run: A=0 X=0 F=0, Q=1 | same |
| `taxonomy_p0b_live_20261001.csv` | 0b live run that read `slotfill_empty` and « infra » (pre-T bucket) | MEASURE_BEFORE_LEVER, snapshot 2026-10-01 |
| `thinking_ab_20261001.csv` | reasoning A/B, series 1 (before the `-x` guard and header repair), 4 arms × 3 | FIX_LOOP, MEASURE_BEFORE_LEVER |
| `thinking_ab_20261001_r2.csv` | series 2 (after both fixes), 3 arms × 3 | same |
| `thinking_ab_bugbench_20261001.csv` | reasoning A/B on `bench/bugbench` (6 seeded bugs, held-out checks), 4 arms × 3; `holdout_ok` = verified patches that also passed the held-out cases | FIX_LOOP, MEASURE_BEFORE_LEVER |
| `ab/<series>_<arm>_<round>.md` | event log of every bench run, the file each CSV row points at (`out`); series `r1`, `r2` (vendored suite) and `bb` (bugbench); `run_dir` keeps the run's original id | — |
| `ab/verified_fix_ntpath.patch` | the one verified patch (`ntpath` on Linux), from `r2_short_off_patch_8k_2` | FIX_LOOP |

Paths here are kept short on purpose: Windows refuses to check out a path
over 260 characters, and a first layout (`thinking_ab/<run>/fixes/<test>.patch`,
132 characters inside the repo) broke a clone made into a deep directory.

The bench runs used Token Factory sandboxes and a simulated fleet; their
failures are the five Windows-only tests described in
[`../../../docs/FIX_LOOP.md`](../../../docs/FIX_LOOP.md) — read "verified"
there with that caveat.
