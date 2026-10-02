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
| `report_20260913T041721Z` | `--mock --heuristic-plan` | mock / mock | **A2 judge film**: autofix ON, migrate `nb-h100-02 → 03`, 2/3 verified on fresh nodes 04 / 05 | Devpost, JUDGE_DRY_RUN, backlog |
| `report_20260913T053458Z` | `--live --shards 1 --heuristic-plan` | Nebius / Token Factory | **Live B**: Contree `cpu-fallback`, heal gated, 5 failures, 3 patches cut at 2048 (0-char), 0/3 | Devpost, JUDGE_DRY_RUN |
| `report_20261002T055558Z` | `NGE_FLEET_MODE=mock --live --shards 2 --heuristic-plan` | mock / Token Factory | Same loop after the reasoning defaults: 5 failures, 3 diffs produced, 0 cut, 3 rejected by verification | JUDGE_DRY_RUN, backlog |
| `report_20260905T232100Z` | `--mock --heuristic-plan` | mock / mock | First 2/3 capture with migrate (M10) | NEBIUS_TRACK, backlog |
| `report_20260905T223331Z` | `--mock` (324M plan) | mock / mock | Plan gate OFF (`bash`, `brave_search`), migrate still happens (M9) | backlog |
| `report_20260905T211401Z` | `--live` (324M plan) | Nebius / Token Factory | `cpu-fallback`, remediations none, autofix gated off (C2, C8) | backlog |

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
recorded. The 2026-10-02 run used the code of `3e49336`.

## Benches

| file | what | cited by |
|---|---|---|
| `taxonomy_p0_heuristic.csv`, `taxonomy_p0_model.csv` | 0a plan taxonomy, 24 cases (2026-09-03) — 29/46/25 % and 21/54/25 % | MEASURE_BEFORE_LEVER, snapshot 2026-09-04 |
| `taxonomy_p0b.csv`, `taxonomy_p0b_live.csv` | 0b probes + one live run: A=0 X=0 F=0, Q=1 | same |
| `taxonomy_p0b_live_20261001.csv` | 0b live run that read `slotfill_empty` and « infra » (pre-T bucket) | MEASURE_BEFORE_LEVER, snapshot 2026-10-01 |
| `thinking_ab_20261001.csv` | reasoning A/B, series 1 (before the `-x` guard and header repair), 4 arms × 3 | FIX_LOOP, MEASURE_BEFORE_LEVER |
| `thinking_ab_20261001_r2.csv` | series 2 (after both fixes), 3 arms × 3 | same |
| `ab/<series>_<arm>_<round>.md` | event log of every bench run, the file each CSV row points at (`out`); `run_dir` keeps the run's original id | — |
| `ab/verified_fix_ntpath.patch` | the one verified patch (`ntpath` on Linux), from `r2_short_off_patch_8k_2` | FIX_LOOP |

Paths here are kept short on purpose: Windows refuses to check out a path
over 260 characters, and a first layout (`thinking_ab/<run>/fixes/<test>.patch`,
132 characters inside the repo) broke a clone made into a deep directory.

The bench runs used Token Factory sandboxes and a simulated fleet; their
failures are the five Windows-only tests described in
[`../../../docs/FIX_LOOP.md`](../../../docs/FIX_LOOP.md) — read "verified"
there with that caveat.
