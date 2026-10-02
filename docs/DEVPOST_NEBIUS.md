# Devpost — Nodus-GPU Engine (Nebius × NVIDIA)

> Copy-paste ready for the **Coding & Agentic Engineering** submission.  
> English = judges. Honesty first: mock shows the full loop; live proves Nebius.  
> Written **2026-09-12** from measured runs, not from the wish list.

Do **not** paste `AUTORESEARCH_VISION.md` / SkillSpector / Compute Phase 2 as if shipped.

---

## Fields (short)

**Project name**  
Nodus-GPU Engine

**Tagline** (≤ 1 line)  
Not a chatbot: a control loop that plans, shards tests, migrates off a hot node, and keeps only green patches.

**Track**  
Coding & Agentic Engineering

**Built with**  
Nebius Token Factory · NVIDIA Nemotron 3 (Ultra / Super / Nano) · Token Factory Sandboxes (Contree) · local Nodus 324M planner · Python

---

## Elevator (paste at top of “Inspiration” or video voiceover)

A code-completion wrapper suggests a fix.  
**Nodus-GPU Engine runs the job:** local plan → sharded pytest on a fleet → migrate off a hot node **after scoring the destination** → patch in a fresh sandbox → re-run the suite → keep only what stays green.

Mock film (`--heuristic-plan`): **2/3 auto-fixed & verified** + GPU migrate `02 → 03`.  
Live (`--live`): real **Nemotron @ Token Factory** + Contree sandboxes. Contree is **CPU today** (`probe_kind=cpu-fallback`); thermal heal is **gated** until real `nvidia-smi` — we refuse fake H100 metrics.

---

## How to try it (judges — pass/fail)

```bash
cd packages/engine
pip install -r requirements.txt
python -m pytest -q
python -m nge.demo_nebius --mock --watch --heuristic-plan
# then open the printed html: path
```

Live (needs Token Factory key):

```bash
python -m nge.demo_nebius --live --shards 1
```

Oral script: `packages/engine/docs/JUDGE_DRY_RUN.md`  
Mock film (2/3 + migrate): `packages/engine/evidence/report_20260913T041721Z.html`  
Live Nebius proof (Contree + Super 0/3): `packages/engine/evidence/report_20260913T053458Z_honest.html` (a re-render of that run — provenance in `packages/engine/evidence/README.md`)  
Live after the reasoning fix (real sandboxes, simulated fleet): `packages/engine/evidence/report_20261002T055558Z.html`

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
- Fleet: `mock` (synthetic H100 telemetry for the film) · `nebius` (Contree) · `compute` (skeleton only — **no VM spawn in this demo**).  
- Mock autofix uses canned patches so the verify loop is deterministic for judges; live slot-fill/triage hits Super.

---

## “Challenges” (paste block — turn risks into design)

- **324M plans are small.** Wrong tool list gates autofix off. We surface `plan(nodus-324m)` vs `plan(heuristic)` and refuse silent edits.  
- **Contree ≠ GPU device.** Efficiency=0 on CPU used to trigger phantom migrations. Heal now requires real GPU metrics.  
- **Patches that fix one test and break others.** Keep only suite-green diffs.  
- **Flaky / truncated model replies.** Caps, `patch_truncated`, bounded retries — not an infinite Super bill.
- **The model spent its budget thinking.** Live patches came back empty at 2048 tokens: Nemotron 3 reasons inside the same `max_tokens`, and 99% of output was reasoning. We measured reasoning on/off per call class on real sandboxes (`bench/thinking_ab.py`): short replies went from 0/6 to 12/12 usable with reasoning off; patches keep reasoning (off, 4/9 diffs cited code that does not exist) with an 8192 ceiling. Measuring it also exposed the model adding `-x` to shard commands, which hid failures and got good patches rejected — now refused.

---

## “What’s next” (honest, short)

Wire Nebius **AI Cloud Compute** for real `nvidia-smi` heal (architecture A: Compute for telemetry, Token Factory for exec). Not claimed as done.

---

## Devpost page order (paste)

1. **Title + tagline** (above).  
2. **Problem** — GPU jobs die on throttle; suggested diffs land untested.  
3. **One command** (real CLI, not `nge run`):

```bash
python -m nge.demo_nebius --mock --watch --heuristic-plan
```

4. **Screenshot** — HTML control room (fleet cards + Story + patches).  
5. **Four criteria** — the sections above.  
6. **Limits** — mock = synthetic H100 for the film; live = Token Factory + Nemotron; Contree = CPU, heal gated.

Do **not** invent “GPU $ saved”. We did not invoice that.

## Video / screenshot checklist

1. Terminal: `--mock --watch --heuristic-plan` — plan, bars, migrate, `2/3`.  
2. Browser: **control room** HTML (cards + Story + diffs).  
3. Optional 10 s: `--live` usage line + `heal gated` / `cpu-fallback`.  
4. Do **not** lead with taxonomy benches or AutoResearch.

---

## Do not write on Devpost

- “We heal real H100s in production today.”  
- “Ultra is billed on every `--live` plan.” (often 324M).  
- “3/3 always verified.”  
- DeepSeek / Ollama as the submission path (`NGE_TRACK=nebius` blocks them).
