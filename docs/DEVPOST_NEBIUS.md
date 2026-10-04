# Devpost — Nodus-GPU Engine (Nebius × NVIDIA)

> Copy-paste ready for the **Coding & Agentic Engineering** submission.  
> English = judges. Honesty first: mock shows the full loop; live proves Nebius.  
> Written **2026-09-12** from measured runs, not from the wish list; reviewed end to end
> **2026-10-03** (reasoning lever, bugbench, Compute probe, recaptured film); Compute Phase 3
> hybrid run added **2026-10-04**, then read end to end again the same day.

Do **not** paste `AUTORESEARCH_VISION.md` / SkillSpector / a migration under real GPU pressure (never happened) as if shipped.

---

## Fields (short)

**Project name**  
Nodus-GPU Engine

**Tagline** (≤ 1 line)  
Not a chatbot: a control loop that plans, shards tests, migrates off a hot node, and keeps only green patches.

**Track**  
Coding & Agentic Engineering

**Built with**  
Nebius Token Factory · NVIDIA Nemotron 3 (Ultra / Super / Nano) · Token Factory Sandboxes (Contree) · Nebius AI Cloud Compute (L40S GPU VMs: probe + hybrid heal run) · local Nodus 324M planner · Python

---

## Elevator (paste at top of “Inspiration” or video voiceover)

A code-completion wrapper suggests a fix.  
**Nodus-GPU Engine runs the job:** local plan → sharded pytest on a fleet → migrate off a hot node **after scoring the destination** → patch in a fresh sandbox → re-run the suite → keep only what stays green.

Mock film (`--heuristic-plan`): **2/3 auto-fixed & verified** + GPU migrate `02 → 03`.  
Live (`--live`): real **Nemotron @ Token Factory** + Contree sandboxes. Contree is **CPU today** (`probe_kind=cpu-fallback`); thermal heal is **gated** until real `nvidia-smi` — we refuse fake H100 metrics.  
Real GPU: on two Nebius AI Cloud **L40S** VMs it created itself, the heal loop read real `nvidia-smi`,
migrated nothing by mistake (an idle GPU is not "inefficient") and deleted both VMs. There was no real
pressure, so no real migration — we did not stage one.

---

## How to try it (judges — pass/fail)

```bash
cd packages/engine
pip install -r requirements.txt
python -m pytest -q
python -m nge.demo_nebius --mock --watch --watch-delay 2.0 --heuristic-plan
# ~85 s; then open the printed html: path
```

Live (needs a Token Factory key and project — `NEBIUS_API_KEY`, `NEBIUS_PROJECT_ID`, or the files
`packages/engine/.nebius_api_key` / `.nebius_project_id`; the extra packages are what CI's
live job installs):

```bash
pip install -r requirements.txt -r ../nodus/requirements-ci.txt contree-sdk
python -m nge.demo_nebius --live --shards 1
```

Oral script: `packages/engine/docs/JUDGE_DRY_RUN.md`  
Mock film (2/3 + migrate): `packages/engine/evidence/report_20261003T233405Z.html`  
Live Nebius proof (Contree + Super 0/3): `packages/engine/evidence/report_20260913T053458Z_honest.html` (a re-render of that run — provenance in `packages/engine/evidence/README.md`)  
Live after the reasoning fix (real sandboxes, simulated fleet): `packages/engine/evidence/report_20261002T055558Z.html`  
Real GPUs (Compute fleet of 2 × L40S + Token Factory sandboxes): `packages/engine/evidence/report_20261004T031503Z_rerender.html`
— the same run re-rendered so the heal decision shows in the story (provenance in the evidence README); it lists
one failure that does not exist, `test_connect_mc`; why is under Challenges

---

## The four scores (write these into the long description)

### 1. Technological Implementation — Token Factory + NVIDIA

We use **Nebius Token Factory** as the OpenAI-compatible endpoint and **NVIDIA Nemotron 3** as the working models — not a generic cloud LLM with a Nebius sticker.

- **Super** `nvidia/nemotron-3-super-120b-a12b` — slot-fill / triage (billed on live).  
- **Nano** `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` — healthcheck role.  
- **Ultra** `nvidia/Nemotron-3-Ultra-550b-a55b` — plan role (often **route-only** when the local 324M plans).  
- **Sandboxes:** Contree SDK — spawn, upload, exec, jail on every shell command.  
- **Usage ledger:** calls + tokens per model; Nano/Ultra 404/5xx → **one hop to Super**, never silent Super→Nano.  
- **IDs are case-sensitive** (verified against `GET /v1/models`).
- **Reasoning per call class:** Nemotron 3 reasons inside `max_tokens`; short replies run with
  `enable_thinking: false`, patches keep it — chosen from measurements, not taste (Challenges).
- **Nebius AI Cloud Compute:** the Python SDK reads every region the account has (platforms,
  presets, subnets, CUDA images) without creating anything, then one probe creates an **L40S**
  VM, reads `nvidia-smi` over SSH (27 °C, 67.8 W, classified `datacenter`) and deletes it —
  192 s, `packages/engine/evidence/compute_probe_20261003T231022Z.json`. Then a hybrid run: two L40S
  VMs as the fleet, shards in Token Factory sandboxes, real telemetry in every heal decision, both
  VMs deleted — `packages/engine/evidence/report_20261004T031503Z.md`.

Token Factory Contree nodes are **not** physical H100s. Live probes report `cpu-fallback`. That is a product fact, not a bug.

### 2. Design

**Design here = the jury understands in 5 seconds.** Not a second product (no Streamlit). The **HTML control room** (`out/report_*.html`) is the screenshot: dark, node cards (temp/util), story timeline, patches kept.

The stack is layered on purpose:

| Layer | Job |
|-------|-----|
| Local 324M / heuristic | Ordered **tool names** only |
| Router | Ultra / Super / Nano = **roles**, not a magic picker |
| Orchestrator | Shards, pressure, placement, autofix gate |
| Jail | Vet LLM shell before exec |
| Report | HTML: KPIs, diffs, **why / cause / urgency** |

Autofix is **plan-gated**: no `edit_file` / `write_file` → triage only.  
Before migrate: **placement** scores temp / free mem / util — refuse fire→fire, then re-run the shard (we do not claim live sandbox teleport).

### 3. Potential Impact

Teams already run agent fleets that burn GPU time and ship untested diffs.  
This engine is the **ops + verify** layer: isolate work, watch nodes, move a shard off a hot box, and refuse patches that break the rest of the suite.

Same keep/discard discipline could later optimize training metrics — **not in this submission**.

### 4. Quality of the Idea

The idea is not “call Nemotron.”  
It is **one closed loop** on a real repo: plan → test → heal → patch → prove.  
A 2/3 score is a feature: one failure had **no patch** — we record the symptom instead of inventing a green 3/3.

That matches the organizers’ bar: *plans, writes, tests, and iterates with minimal human input* — not a completion wrapper.

---

## “Inspiration” (paste block)

Hackathon agents usually stop at a suggested diff. Production engineering does not: you shard work, you lose a hot node, you must not apply a fix that breaks twenty other tests.

We built the missing loop on **Nebius Token Factory + NVIDIA Nemotron**, with a small local planner so the cloud models are used where they earn their tokens.

---

## “How we built it” (paste block)

- Vendored Nodus runtime (unmodified) + engine package `nge`.  
- Reversible `nebius:` chat backend: `max_tokens`, usage (incl. `reasoning_tokens`), reasoning on/off per call class, `ModelUnavailableError`.  
- Fleet: `mock` (synthetic H100 telemetry for the film) · `nebius` (Contree) · `compute`: Nebius AI Cloud GPU VMs the engine creates, reads over SSH (`nvidia-smi`) and deletes — a one-VM probe, then a hybrid heal run on 2 × L40S. Labelled VMs, a self-power-off in cloud-init, and a refusal to start while one is left over.  
- Mock autofix uses canned patches so the verify loop is deterministic for judges; live slot-fill/triage hits Super.

---

## “Challenges” (paste block — turn risks into design)

- **324M plans are small.** Wrong tool list gates autofix off. We surface `plan(nodus-324m)` vs `plan(heuristic)` and refuse silent edits.  
- **Contree ≠ GPU device.** Efficiency=0 on CPU used to trigger phantom migrations. Heal now requires real GPU metrics.  
- **A real GPU can lie the same way.** An idle L40S reads 0 % utilisation, so efficiency 0: on real metrics the heal would have migrated shards off healthy GPUs. Caught before any VM was created; low efficiency now counts only when the job declares GPU work. The live run then skipped it twice, correctly (`gpu_efficiency_skipped`).  
- **Patches that fix one test and break others.** Keep only suite-green diffs.  
- **Flaky / truncated model replies.** Caps, `patch_truncated`, bounded retries — not an infinite Super bill.
- **The model spent its budget thinking.** Live patches came back empty at 2048 tokens: Nemotron 3 reasons inside the same `max_tokens`, and 99% of output was reasoning. We measured reasoning on/off per call class on real sandboxes (`bench/thinking_ab.py`): short replies went from 0/6 to 12/12 usable with reasoning off; patches keep reasoning with an 8192 ceiling. On six seeded, OS-independent bugs re-checked against held-out cases the model never saw (`bench/bugbench`), every patch the loop verified was a real fix and none broke a test: 16/18 with reasoning on or off, 12/16 with the old setting. Measuring it also exposed the model adding `-x` to shard commands (hid failures, got good patches rejected) and copying the prompt's `--tb=` placeholder (a shard that ran nothing) — both now refused.
- **A sandbox that cuts its output.** The real-GPU run listed a failing test that does not exist, `test_connect_mc`. ContreeSDK cuts stdout at 64 KiB; that shard printed about 65.6 KB, so its last `FAILED` line was cut mid-name and the real test never reached the parser. Replayed at both limits (`bench/output_cut_replay.py`), then fixed: a larger limit, the SDK's `truncated` flag read, the fragment dropped and reported, and no patch is ever called verified on cut output.

---

## “What’s next” (honest, short)

Done since the first draft: the engine's own probe created a Nebius AI Cloud **L40S** VM, read `nvidia-smi` (27 °C, 67.8 W, classified `datacenter`) and deleted it — 192 s end to end, evidence in `packages/engine/evidence/compute_probe_20261003T231022Z.json`. Its first live run failed (a Windows CRLF bug, and a VM that outlived a killed process); both causes are fixed and documented.
Then the heal loop ran on real GPUs: two L40S VMs, real `nvidia-smi` in each heal decision, nothing migrated by mistake,
both VMs deleted (`packages/engine/evidence/report_20261004T031503Z.md`). Building it caught a flaw first: an idle GPU
reads efficiency 0, which would have migrated shards off healthy nodes — fixed before any VM was created.

Next: a migration under real GPU pressure needs GPU work on the node (the shards run on CPU sandboxes today), and
per-SKU thresholds (they are H100-tuned; an L40S tops out near 350 W). Not claimed as done.

---

## Devpost page order (paste)

1. **Title + tagline** (above).  
2. **Problem** — GPU jobs die on throttle; suggested diffs land untested.  
3. **One command** (real CLI, not `nge run`):

```bash
python -m nge.demo_nebius --mock --watch --watch-delay 2.0 --heuristic-plan
```

4. **Screenshot** — HTML control room (fleet cards + Story + patches).  
5. **Four criteria** — the sections above.  
6. **Limits** — mock = synthetic H100 for the film; live = Token Factory + Nemotron; Contree = CPU, heal gated;
   the heal loop has run once on real GPUs (2 × L40S, real telemetry, nothing migrated by mistake); no migration
   under real pressure — there was none.

Do **not** invent “GPU $ saved”. We did not invoice that.

## Video / screenshot checklist

1. Terminal: `--mock --watch --watch-delay 2.0 --heuristic-plan` (~85 s) — plan, bars, migrate, `2/3`.  
2. Browser: **control room** HTML (cards + Story + diffs).  
3. Optional 10 s: `--live` usage line + `heal gated` / `cpu-fallback`.  
3b. Optional 10 s: the Compute probe report — `probe_kind=nvidia-smi`, `NVIDIA L40S`, `deleted: true` — or the
    hybrid report `report_20261004T031503Z_rerender.html`: two `cg-l40s-a` cards at 25 °C, 0 migrations, and in
    the story « efficiency not counted … an idle GPU reads 0, that is not pressure ».  
4. Do **not** lead with taxonomy benches or AutoResearch.

---

## Do not write on Devpost

- “We heal real H100s in production today.”  
- “The engine heals real GPUs.” (the heal loop read real L40S telemetry once, with no pressure; it has never
  migrated off a real GPU)  
- “Ultra is billed on every `--live` plan.” (often 324M).  
- “3/3 always verified.”  
- DeepSeek / Ollama as the submission path (`NGE_TRACK=nebius` blocks them).
