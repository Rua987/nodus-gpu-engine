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
| `swebench_step2_20261019.csv`, `swebench_validation_20261019.jsonl` | `NGE_THINKING_PATCH=off python -m bench.swebench_runner --i-know-cost --repos psf/requests,pallets/flask` and `--repos pytest-dev/pytest`; validation: `python -m bench.swebench_probe --i-know-cost --instance <id>` for each of the 28 | Token Factory sandboxes on the tasks' SWE-bench images; Nemotron Super, reasoning off | Real bugs, step 2: **3 of 21 validated tasks resolved** (flask-5014, pytest-6202, pytest-8399). 7 of 28 do not validate here (bug not reproduced, tests not run, ids not found). The CSV joins each task's outcome, the archive's failure category and its validation | REAL_BUGS |
| `swebench_smoke_20261018.csv`, `swebench_attempts_20261018.jsonl` | `python -m bench.swebench_runner --i-know-cost --instances pallets__flask-5014,psf__requests-5414`, seven passes varying `NGE_PATCH_MAX_TOKENS`, `NGE_THINKING_PATCH` and the adapter's alignment (as it was built) | Token Factory sandboxes on the tasks' SWE-bench images, Nemotron Super | Real bugs, step 1: `flask-5014` resolved twice with reasoning off and context alignment, never otherwise; `requests-5414` never (wrong cause). The `.jsonl` is the adapter's attempt index | REAL_BUGS |
| `swebench_probe_20261018.txt` | `python -m bench.swebench_probe --i-know-cost --instance <id>`, for `pallets__flask-5014` and `psf__requests-5414` | Token Factory sandbox on the task's SWE-bench image, no model call | Real bugs, step 0: the official image runs in a Token Factory sandbox (ready in 0.4 s); with the task's tests `FAIL_TO_PASS` fails, with the historical fix it passes and every `PASS_TO_PASS` stays green (59/59, 130/130) | REAL_BUGS |
| `report_20261019T054453Z` (+ `.holdout.json`), `attempts_20261019.jsonl` | `python -m nge.demo_nebius --live --watch --heuristic-plan --scenario scenarios/bugbench_live.json`, filmed | Nebius / Token Factory | **Live film (A3)**, eighth run, the last before the verification fix: 4/6 « verified » - the patch applied; its sandbox re-run ran no test (FIX_LOOP, *The re-run must have run the tests*) - 4/4 hold the hidden cases, and 4/4 pass the whole suite re-checked after the fact. Rejected: invented context; a right fix patch-ng refused for a loop body typed 4 spaces short (exit 255, no output). Series: 8 runs, 41/48 kept, 41/41 hold, 41/41 break nothing | FIX_LOOP, JUDGE_DRY_RUN, Devpost |
| `suite_recheck_20261019.csv` | `python -m bench.suite_recheck evidence/report_<8 live films>.html --csv …` | local, real pytest, no model | Every patch the eight live films called verified, applied to a copy of bugbench and run against the whole visible suite: **41/41 fix their test and break nothing**. The half of « verified » the sandbox re-run never checked until 2026-10-19 | FIX_LOOP, Devpost |
| `verify_cmd_probe_20261019.txt` | the fix-verification command, old and new, with an archived diff (scratch script; the commands are in the file) | 2 Token Factory sandboxes, no model | Old: exit 2, 3 collection errors, no test ran. New: exit 1, `5 failed, 11 passed` (the 5 other bugs) | FIX_LOOP |
| `report_20261018T211503Z` (+ `.holdout.json`), `attempts_20261018.jsonl` | same command, without `--watch` | Nebius / Token Factory | **Live film (A3)**, seventh run, the first with the attempt archive: 4/6 verified, 4/4 hold. The `.jsonl` is that run's `attempts/index.jsonl` (the per-attempt directories are too deep a path for `evidence/`; the diffs are in the HTML). One rejection is a right fix patch-ng refused for mis-indented context (`category: no_output`, exit 127) - see FIX_LOOP *Every attempt is archived*. Series: 7 runs, 37/42, 37/37 | FIX_LOOP, JUDGE_DRY_RUN, Devpost |
| `report_20261017T064106Z`, `report_20261018T003231Z` (+ `.holdout.json`) | same command, `--watch`, filmed for the video | Nebius / Token Factory | **Live film (A3)**, fifth and sixth runs: 6/6 verified, 6/6 hold, both. The fifth was filmed from a conda Python without patch-ng, so the film printed « held-out: not checked »; its `.holdout.json` was made after the run by `python -m bench.holdout_from_html evidence/report_20261017T064106Z.html` from the diffs in its HTML (that read-back is byte-identical to the patch files on the sixth run, and gives the film's own verdicts there) and says so in a `checked` field. Series: 6 runs, 33/36, 33/33 | JUDGE_DRY_RUN, Devpost |
| `report_20261005T004845Z` (+ `.holdout.json`) | same command, `--watch` | Nebius / Token Factory | **Live film (A3)**, fourth run — the video rehearsal: **6/6** verified, 6/6 hold the held-out cases. Kept with the other three so the series is every run, not the best ones: 21/24, 21/21 | JUDGE_DRY_RUN, Devpost |
| `report_20261004T221630Z`, `…222054Z`, `…222707Z` (+ `.holdout.json`) | `python -m nge.demo_nebius --live --watch --heuristic-plan --scenario scenarios/bugbench_live.json` (the first without `--watch`) | Nebius / Token Factory | **Live film (A3)**, three runs: 6 seeded bugs, real Nemotron patches, 5/6 verified each time, and every verified patch also passes the held-out cases (`.holdout.json`, written by the demo). Rejected: a diff citing code that does not exist (×2), a patch cut at 8192 tokens (×1). The first two ran before the console fix: their nodes are labelled `nb-h100-*` though they are CPU sandboxes, and their terminal showed a spurious token warning; the loop is the same | JUDGE_DRY_RUN, Devpost |
| `report_20261004T234436Z` | `NGE_COMPUTE_SPAWN=1 python -m nge.fleet.compute contention --i-know-cost --max-minutes 20` | Compute (3 × L40S) / compute (shards on the VMs) | **Phase 4, run 1**: declared induced load on node 0 (100 %, 324 W) → `busy` → placement refuses every node → a 3rd VM → migration. The re-run there had no files (pytest exit 4) and the GPU process listing was empty — both fixed after; shard 1 on an idle node passed (CUDA built and checked). No instance id, ip or project id in the report. Code `32ec244` | COMPUTE_GPU, backlog |
| `report_20261019T052247Z` | `NGE_COMPUTE_SPAWN=1 python -m nge.fleet.compute contention --i-know-cost --max-minutes 20` | Compute (3 × L40S) / compute | **Phase 4, run 3**, filmed for the video: the same chain as run 2 - declared induced load (100 %, 324.8 W, `./nge_burn` listed on the GPU) → `busy` → a 3rd VM → migration; the same shard took 25.4 s on the loaded node and 20.5 s on the fresh one, the control shard 21.4 s. Its own HTML is right (written by the fixed renderer): show it as is. Code `c0f9dcf` | COMPUTE_GPU, Devpost, JUDGE_DRY_RUN, backlog |
| `report_20261005T001234Z` (+ `_rerender.html`) | `NGE_COMPUTE_SPAWN=1 python -m nge.fleet.compute contention --i-know-cost --max-minutes 20`; the re-render: `python -m nge.report_rerender evidence/report_20261005T001234Z.md evidence/report_20261005T001234Z_rerender.html` | Compute (3 × L40S) / compute | **Phase 4, run 2**: declared induced load (100 %, 324 W, `./nge_burn` listed on the GPU) → `busy` → a 3rd VM → migration; the same shard took 26.8 s on the loaded node and 20.3 s on the fresh one, the control shard 20.3 s. The run-time HTML labels the busy node « THROTTLED » and says the shards ran in Token Factory sandboxes — both wrong, both fixed in the renderer; the `_rerender.html` is what to show. Code `184effd` | COMPUTE_GPU, Devpost, JUDGE_DRY_RUN, backlog |
| `schema_probe_20261008.txt` | `python -m bench.schema_probe --i-know-cost` | Token Factory (Nemotron 3 Super) | Asked for values a schema forbids: a strict `json_schema` keeps 3/3 replies inside it; no schema, `json_object` and vLLM `guided_json` (accepted, ignored) 0/3 | FIX_LOOP, Devpost |
| `slotfill_ab_20261008.csv` | `python -m bench.slotfill_ab --i-know-cost --calls 10 --csv out/slotfill_ab_20261008.csv` | Token Factory, no sandbox | Free-text vs typed slot-fill on the real call: 40/40 usable each; 0.87 s vs 0.78 s, 55.9 vs 22.0 output tokens | FIX_LOOP |
| `verify_predictor_20261009.txt` / `.csv` | `python -m bench.verify_predictor --csv evidence/verify_predictor_20261009.csv` (needs the local `out/thinking_ab`, which is not versioned; the CSV is the reproducible artefact) | offline, no network | Can a small model predict « this patch will verify » from its features? 83 real-model patches, leave-one-bug-out: inside each suite the model is inside the shuffled-label noise; pooled AUC 0.77 is the suite id (alone: 0.83) | FIX_LOOP |
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
