# Judge dry-run — filmable (~90 s)

Source of truth for the **Coding & Agentic Engineering** pitch.
Last rehearsal: **2026-10-03** — A2 replayed end to end; see *Rehearsal notes* below.

## Which demo when

| Mode | Command | What judges *see* | Cost |
|------|---------|-------------------|------|
| **A2 — recommended film** | `--mock --watch --heuristic-plan` | Keyword plan + `edit_file` → migrate → **auto-fixed 2/3** | €0 |
| **A — 324M honesty** | `--mock --watch` | Plan 324M → migrate → often **autofix OFF** | €0 |
| **B — live honesty** | `--live --shards 1` | Contree `cpu-fallback`, heal **gated**, Super usage | cents |

**Pitch rule:** Prefer **A2** if you only have one film — it matches the
« patch and verify » claim. Mention that with the 324M alone (mode A) the plan
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
| `plan gate … autofix ON` | 4 Gate |
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
| Real GPU at all? | « Yes, once: the engine created a Nebius L40S VM, read nvidia-smi — 27 °C, datacenter class — and deleted it in 192 s. The heal loop on real load is next, not done. » |
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
- [ ] Archi if asked: TF for exec; Compute for real `nvidia-smi` (one probe done, heal loop not)

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
