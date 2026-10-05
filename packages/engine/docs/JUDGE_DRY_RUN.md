# Judge dry-run — filmable (~90 s)

Source of truth for the **Coding & Agentic Engineering** pitch.
Last rehearsal: **2026-10-04** — A2 replayed end to end; see *Rehearsal notes* below.

## Which demo when

| Mode | Command | What judges *see* | Cost |
|------|---------|-------------------|------|
| **A2 — recommended film** | `--mock --watch --heuristic-plan` | Keyword plan + `edit_file` → migrate → **auto-fixed 2/3** | €0 |
| **A — 324M honesty** | `--mock --watch` | Plan 324M → migrate → often **autofix OFF** | €0 |
| **A3 — live film (real patches)** | `--live --watch --heuristic-plan --scenario scenarios/bugbench_live.json` | Real Nemotron patches on 6 seeded bugs, verified in fresh Token Factory sandboxes, then re-checked on **hidden cases**: 5/6 verified, 5/5 hold (3 runs: 15/18, 15/15). Nodes marked `cpu sandbox`, heal gated | ~1 ¢ |
| **B — live honesty** | `--live --shards 1` | Contree `cpu-fallback`, heal **gated**, Super usage | cents |

**Pitch rule:** **A3** is the proof of « patch and verify » — real model, real sandboxes, hidden
checks. **A2** is the only place the heal is visible (it needs GPU metrics). The video uses both,
A3 first. If only one: A3. (Before 2026-10-04 the rule was A2: the patches were canned.) Mention that with the 324M alone (mode A) the plan
may omit `edit_file` and we triage only — same engine, different outcome.

---

## Capture (before the room)

```bash
cd packages/engine
python -m nge.demo_nebius --mock --watch --watch-delay 2.0 --heuristic-plan
```

Expect: `plan [heuristic]: ['bash', 'edit_file', 'write_file']` → `autofix ON` →
`auto-fixed & verified: 2/3` → open printed `html:`. Measured: **85 s** at
`--watch-delay 2.0` (the pace of the spoken lines); 35 s at `0.8`.

**Two screenshots — do not mix:**

| Proof | File | What it shows |
|-------|------|----------------|
| **A2 film** (loop) | `evidence/report_20261003T233405Z.html` | Mock 2/3 + migrate 02→03 + verify 04/05 (2026-10-03 capture, clean header) |
| A2, earlier | `evidence/report_20260913T041721Z.html` | Same result; its header still says « checkpoint NOT FOUND » (fixed since) — don't show |
| **B Nebius** (live) | `evidence/report_20260913T053458Z_honest.html` (re-render, see `evidence/README.md`) | Contree cpu-fallback, Super **0/3** truncated, Ultra route-only |
| B, after 2026-10-01 | `evidence/report_20261002T055558Z.html` | Reasoning fix, real sandboxes, **simulated fleet** (`NGE_FLEET_MODE=mock`): 5 real failures, 3 diffs produced, 0 cut, 3 honestly rejected |

Alternate (gate OFF):

```bash
python -m nge.demo_nebius --mock --watch --watch-delay 0.8
```

Optional live / tiers (not the main film):

```bash
python -m nge.demo_nebius --live --shards 1
python -m bench.tier_smoke --i-know-cost --live-failover --skip-local-failover
```

---

## Watch cues → beats (A2)

| On screen | Beat |
|-----------|------|
| `plan [heuristic]: [… 'edit_file' …]` | 1 Plan |
| `provision x3` + util/temp bars | 2 Fleet |
| migrate `02 ──▶ 03` | 3 Heal |
| `plan gate OK  autofix on  (edit_file, write_file)` | 4 Gate |
| `fix OK` / `fix? … no patch` (summary: `fix --`) | 4b Verify (2/3 typical) |
| `run complete` + HTML | Close |

---

## Spoken lines (English, short)

**0 — cold open**  
« Agentic engineering loop: local plan, GPU fleet, self-heal a hot node, and —
only if the plan asked to edit — patch and verify. »

**1 — Plan**  
« Keyword plan for this film so `edit_file` is present — that unlocks the code
agent. With the 324M weights alone, the plan may omit edit and we triage only. »

**2 — Fleet**  
« Three simulated H100s. Ultra / Super / Nano are *roles* per decision — not a
magic picker. Jail on. »

**3 — Heal**  
« Shard hits thermal pressure. We re-provision and migrate. Mock has synthetic
GPU metrics so the heal is visible. »

**4 — Gate + fix**  
« Plan asked to edit. Fresh sandbox; keep only patches that stay green. Two
verified, one with no canned patch — honesty, not a greenwashed 3/3. »

**5 — Close**  
Open HTML: KPI `2/3`, migration row, diffs under Auto-fixes.

### If interrupted

| Question | Answer |
|----------|--------|
| Real Nebius? | « Mock for the film. `--live` = Token Factory Contree + Nemotron. Contree is CPU today; heal gated until real GPU metrics. » |
| Real GPU at all? | « Yes, Nebius L40S VMs the engine creates and deletes. Idle, it migrated nothing. Then we started a GPU job on one node — induced, and the report says so — the loop saw the busy GPU and the process on it, moved the shard to a fresh VM: 26.8 s there, 20.3 s on the new one. A spontaneous overheat: never seen. » |
| Why heuristic? | « To open the autofix gate for the film. 324M path is real too — often triage-only on this task. » |
| Why not 3/3? | « One failure has no canned patch — we report it, we don't invent success. » |
| Model down? | « Nano/Ultra 404/5xx → one hop to Super, logged. Never silent Super→Nano. » |
| Why was live 0/3? | « Nemotron reasons inside the same token budget: 99% of output was reasoning, every reply cut. Measured per call class — short replies now run without reasoning, patches keep it with room. » |
| DeepSeek? | « Off the Nebius submission path. » |

---

## Presenter checklist

- [ ] Mode **A2** rehearsed; know 2/3 is expected
- [ ] Font large; browser: mock `233405Z` **or** live honest `053458Z_honest` — never both as one run
- [ ] Do **not** open taxonomy benches as the pitch
- [ ] One honest sentence: Contree ≠ H100
- [ ] Archi if asked: TF for exec; Compute for real `nvidia-smi` (probe; hybrid heal run, nothing migrated by mistake; one real migration under a declared induced load, 26.8 s → 20.3 s)

## YouTube video (rules: under 3 min, public) — shot list

Six clips, recorded separately so a bad take costs one clip; target **2:45**, never 3:00.
The live clip (A3) is the proof — real patches; the mock clip (A2) only shows the heal, which
needs GPU metrics the live sandboxes do not have. Narration in English, over each clip.

| # | time | screen | say |
|---|---|---|---|
| 1 | 0:00–0:12 | GitHub repo page (README top, CI badge) | « This is Nodus-GPU Engine, on Nebius Token Factory and NVIDIA Nemotron. Not a chatbot: a control loop that runs tests, fixes what breaks, and keeps only the fixes it can prove. » |
| 2 | 0:12–1:22 | terminal, **A3 live** (~140 s real; speed the model waits up 2× in the editor and caption « 2× ») | start: « Live: Nemotron Super on Nebius Token Factory, six seeded bugs. Every node is a Token Factory sandbox — CPU, so the screen says heal gated. » · fixes: « Each failure goes to Nemotron, which writes a patch; it is applied in a fresh sandbox and the whole suite re-runs. » · end: « Five of six verified. Then each kept patch is re-checked on hidden cases the model never saw: five of five. The sixth did not make it — we keep only what we can prove. » |
| 3 | 1:22–1:52 | terminal, **A2 mock**, `--mock --watch --watch-delay 0.8 --heuristic-plan` (35 s) | « The heal needs GPU metrics, so here it runs on simulated H100s: node 02 overheats, the engine scores a destination and moves the shard to 03. » |
| 4 | 1:52–2:12 | browser: the HTML the A3 run printed | « Everything lands in one control room: the sandboxes, honestly marked CPU, the story of the run, and the diffs we kept. » |
| 5 | 2:12–2:32 | browser: `evidence/report_20261005T001234Z_rerender.html` | « On real Nebius L40S GPUs we started a load on one node — induced, and the report says so. The loop saw the busy GPU and the process on it, moved the shard to a fresh VM: 26.8 seconds there, 20.3 here. » |
| 6 | 2:32–2:45 | GitHub repo page | « Every claim here is checked by a test against the run's own log. Public, MIT — clone it and run it yourself. » |

Which bug fails in A3 varies by run (three runs: a diff citing code that does not exist, twice;
a patch cut at its token ceiling, once) — keep the line generic, as above.

Before recording: terminal font large (~20 pt), window maximised, notifications off, `cls`,
`cd packages/engine`; run each command once to warm up; open the HTML files in tabs.

## Rehearsal notes — 2026-10-04

Replayed A2 after Compute Phase 3 and the report changes, same capture command:
85 s, exit 0, no warning in the terminal. Cues in order: plan, provision ×3,
migrate `02 ──▶ 03`, plan gate, `fix OK` ×2, `no patch`, run complete, `html:`;
result 2/3, verify on 04 / 05. The HTML's visible text matches the committed
capture `233405Z` except its timestamp, so the capture stands. One cue was
worded from memory: the gate reads `plan gate OK  autofix on`, not
`autofix ON` (that spelling is the post-run summary).

## Rehearsal notes — 2026-10-03

Replayed A2 with the exact capture command. Every cue in *Watch cues* appears,
in order; result 2/3, migrate `nb-h100-02 → nb-h100-03`, verify on 04 / 05.
Fixed on the way:

- The film **opened on a warning**: « 324M planner checkpoint NOT FOUND at
  `__nge_force_heuristic__/missing.pt` » — in the terminal and in the HTML
  report — while the weights are on disk and `--heuristic-plan` simply skips
  them. The planner now says « keyword heuristic requested (--heuristic-plan) »
  and the terminal shows no warning.
- The Auto-fixes table read « … before asserting.. » (double full stop) three
  times.
- The script said ~90 s; `--watch-delay 0.8` gives 35 s. `2.0` gives 85 s.

## French — aide-mémoire

0. Boucle : plan → flotte → heal → patch si le plan demande d'éditer.  
1. Film : `--heuristic-plan` → autofix ON → HTML **2/3**.  
2. Ultra/Super/Nano = rôles.  
3. Mock = heal visible ; live = CPU / heal coupé.  
4. Fermer sur le HTML.
