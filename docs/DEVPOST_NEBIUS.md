# Devpost — Nodus-GPU Engine (Nebius × NVIDIA)

> Copy-paste ready for the **Coding & Agentic Engineering** submission.  
> English = judges. Honesty first: mock shows the full loop; live proves Nebius.  
> Written **2026-09-12** from measured runs, not from the wish list; reviewed end to end
> **2026-10-03** (reasoning lever, bugbench, Compute probe, recaptured film); Compute Phase 3
> hybrid run added **2026-10-04**, then read end to end again the same day.

Do **not** paste `AUTORESEARCH_VISION.md` / SkillSpector / a spontaneous overheating migration (never happened — the real
migration was under a load we induced and declared) as if shipped.

---

## Official requirements — checked against the rules (2026-10-04)

Source: `nebiusglobalaihackathon.devpost.com/rules`. **Deadline: 2026-10-30, 10:00 AM PDT**
(17:00 UTC) — not the 31st, which earlier notes said.

| requirement (rules) | status |
|---|---|
| Runs on Token Factory or AI Cloud, uses an NVIDIA open model | yes — Nemotron 3 on Token Factory, sandboxes, and AI Cloud GPU VMs |
| Track chosen | Coding and Agentic Engineering — « agents that write, run, and test code in Token Factory » |
| Text description of features and functionality | the *About the project* blocks below |
| Demo video **under 3 minutes**, **public on YouTube** | **to do** — film ~85 s + optional shots (checklist below) |
| Code repo **public**, open-source licence file | MIT `LICENSE` present; repo **private today — must be made public** (history scanned 2026-10-04: no key, no account id, no ip) |
| README with setup instructions | `README.md` (*Quick start*, no credentials) |
| Free testing access for judges | the mock demo needs no key and no network (*Testing instructions*) |
| Highlight Nemotron, Token Factory, other Nebius tools | *Technological Implementation* below |
| Feedback on Token Factory, AI Cloud, NVIDIA | *Feedback* block below |
| English | all paste blocks are English |
| New, or significantly updated after 2026-08-26 | every commit is from 2026-09-01 on |

## Form map — which block goes in which field

| Devpost field | paste |
|---|---|
| Project name | `Nodus-GPU Engine` |
| Elevator pitch | the tagline (≤ 200 chars) |
| About the project | in order: *Inspiration*, *What it does*, *How we built it*, *Challenges*, *Accomplishments*, *What we learned*, *What's next* |
| Built with | `python` `nvidia-nemotron` `nebius-token-factory` `nebius-ai-cloud` `contree-sandboxes` `pytorch` `mcp` |
| Try it out | https://github.com/Rua987/nodus-gpu-engine |
| Video demo link | the public YouTube URL |
| Track | Coding and Agentic Engineering |
| Testing instructions | *Testing instructions* block |
| How you used Nemotron / Token Factory / Nebius | *Technological Implementation* section |
| Feedback | *Feedback* block |

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

Live film (`--live`, six seeded bugs): **real Nemotron patches — 5/6 verified in fresh Token Factory sandboxes, and
all 5 also pass hidden cases the model never saw** (three runs: 15/18 verified, 15/15 hold).  
Mock film (`--heuristic-plan`): the heal — GPU migrate `02 → 03` on simulated H100s — with canned patches, 2/3.  
Live (`--live`): real **Nemotron @ Token Factory** + Contree sandboxes. Contree is **CPU today** (`probe_kind=cpu-fallback`); thermal heal is **gated** until real `nvidia-smi` — we refuse fake H100 metrics.  
Real GPU: on Nebius AI Cloud **L40S** VMs it creates and deletes itself, the heal loop reads real `nvidia-smi`.
Idle GPUs: nothing migrated by mistake. A GPU held by another process — a load we **induced and declared** — :
the loop named the process, moved the shard to a fresh VM, and the same work went from **26.8 s to 20.3 s**.

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
Live film (real patches + hidden checks): `packages/engine/evidence/report_20261004T222707Z.html` and its
`.holdout.json`; run it with
`python -m nge.demo_nebius --live --watch --heuristic-plan --scenario scenarios/bugbench_live.json` (~2 min, about one cent)  
Mock film (2/3 + migrate): `packages/engine/evidence/report_20261003T233405Z.html`  
Live Nebius proof (Contree + Super 0/3): `packages/engine/evidence/report_20260913T053458Z_honest.html` (a re-render of that run — provenance in `packages/engine/evidence/README.md`)  
Live after the reasoning fix (real sandboxes, simulated fleet): `packages/engine/evidence/report_20261002T055558Z.html`  
Real migration (3 × L40S, declared induced load, timed): `packages/engine/evidence/report_20261005T001234Z_rerender.html`
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
  VMs deleted — `packages/engine/evidence/report_20261004T031503Z.md`. Then shards whose tests run CUDA
  on the VMs (a checked matmul built with the image's `nvcc`), a GPU burn started on one node and declared
  as induced: the loop read the busy GPU and the process on it, opened a third VM, migrated, and timed the
  same shard 26.8 s → 20.3 s — `packages/engine/evidence/report_20261005T001234Z_rerender.html`.

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

## “What it does” (paste block)

Give it a task and a repo. It plans which tools it needs (a 324M model running locally, or a keyword
plan), shards the test suite across a GPU fleet, watches each node's telemetry, and moves a shard off
a node that runs hot — after scoring where it can go. Failing tests go to Nemotron, which proposes a
patch; the patch is applied in a fresh Token Factory sandbox and the **whole** suite is re-run. A patch
is kept only if its test passes and nothing else broke. Everything ends in one HTML control room: fleet
cards, a short story of the run, the patches kept and why the others were not.

It also says what it did not do: a CPU sandbox reports `cpu-fallback` instead of a fake 0 °C, a cut
model reply is labelled cut, and a sandbox that cut its output never yields a "verified" fix.

## “How we built it” (paste block)

- Vendored Nodus runtime (unmodified) + engine package `nge`.  
- Reversible `nebius:` chat backend: `max_tokens`, usage (incl. `reasoning_tokens`), reasoning on/off per call class, `ModelUnavailableError`.  
- Fleet: `mock` (synthetic H100 telemetry for the film) · `nebius` (Contree) · `compute`: Nebius AI Cloud GPU VMs the engine creates, reads over SSH (`nvidia-smi`) and deletes — a one-VM probe, then a hybrid heal run on 2 × L40S. Labelled VMs, a self-power-off in cloud-init, and a refusal to start while one is left over.  
- Mock autofix uses canned patches so the verify loop is deterministic for judges; live slot-fill/triage hits Super.

---

## “Challenges” (paste block — turn risks into design)

- **324M plans are small.** Wrong tool list gates autofix off. We surface `plan(nodus-324m)` vs `plan(heuristic)` and refuse silent edits.  
- **Contree ≠ GPU device.** Efficiency=0 on CPU used to trigger phantom migrations. Heal now requires real GPU metrics.  
- **The first real migration re-ran nothing.** On a fresh VM the re-run had no files — pytest exit 4 — because the heal had never re-shipped them: the simulated sandbox needs none, so nobody saw it. The same run listed no GPU process because the telemetry probe exits once it has read the GPU. Both fixed, the second with a test that runs the script in a real shell; the next run migrated, re-ran and timed it.
- **A real GPU can lie the same way.** An idle L40S reads 0 % utilisation, so efficiency 0: on real metrics the heal would have migrated shards off healthy GPUs. Caught before any VM was created; low efficiency now counts only when the job declares GPU work. The live run then skipped it twice, correctly (`gpu_efficiency_skipped`).  
- **Patches that fix one test and break others.** Keep only suite-green diffs.  
- **Flaky / truncated model replies.** Caps, `patch_truncated`, bounded retries — not an infinite Super bill.
- **The model spent its budget thinking.** Live patches came back empty at 2048 tokens: Nemotron 3 reasons inside the same `max_tokens`, and 99% of output was reasoning. We measured reasoning on/off per call class on real sandboxes (`bench/thinking_ab.py`): short replies went from 0/6 to 12/12 usable with reasoning off; patches keep reasoning with an 8192 ceiling. On six seeded, OS-independent bugs re-checked against held-out cases the model never saw (`bench/bugbench`), every patch the loop verified was a real fix and none broke a test: 16/18 with reasoning on or off, 12/16 with the old setting. Measuring it also exposed the model adding `-x` to shard commands (hid failures, got good patches rejected) and copying the prompt's `--tb=` placeholder (a shard that ran nothing) — both now refused.
- **A sandbox that cuts its output.** The real-GPU run listed a failing test that does not exist, `test_connect_mc`. ContreeSDK cuts stdout at 64 KiB; that shard printed about 65.6 KB, so its last `FAILED` line was cut mid-name and the real test never reached the parser. Replayed at both limits (`bench/output_cut_replay.py`), then fixed: a larger limit, the SDK's `truncated` flag read, the fragment dropped and reported, and no patch is ever called verified on cut output.

---

## “Accomplishments that we're proud of” (paste block)

- One closed loop on a real repo — plan, test, heal, patch, prove — with every judge-facing claim
  checked by a test against the run's own event log (`packages/engine/tests/test_evidence.py`).
- On six seeded bugs re-checked against held-out cases the model never saw, every patch the loop called
  verified was a real fix, and none broke another test — in the benchmark, and again in the live film
  (15/15 across three runs).
- The heal loop ran on real Nebius L40S GPUs it created and deleted itself: it migrated nothing by mistake
  on idle ones, and moved a GPU job off one that another process held (a load we induced and declared) —
  26.8 s there, 20.3 s on the fresh VM.
- Bugs found by measuring, not guessing: reasoning eating the token budget, `-x` hiding failures, a
  prompt placeholder copied into a command, and a 64 KiB output cut that invented a test.

## “What we learned” (paste block)

- Measure the lever before pulling it. Turning Nemotron's reasoning off fixed short replies outright; for
  patches it was a tie, and we wrote that down instead of claiming a win.
- A green exit code is not a verdict. A sandbox that ran nothing, a shard told to stop at the first
  failure, an output cut at 64 KiB — each looked like success until the failure sets were compared.
- Real metrics can lie like fake ones. An idle GPU reads efficiency 0; the fix for CPU sandboxes had to
  be generalised before the first real VM.

## “What’s next” (honest, short)

Done since the first draft: the engine's own probe created a Nebius AI Cloud **L40S** VM, read `nvidia-smi` (27 °C, 67.8 W, classified `datacenter`) and deleted it — 192 s end to end, evidence in `packages/engine/evidence/compute_probe_20261003T231022Z.json`. Its first live run failed (a Windows CRLF bug, and a VM that outlived a killed process); both causes are fixed and documented.
Then the heal loop ran on real GPUs: two L40S VMs, real `nvidia-smi` in each heal decision, nothing migrated by mistake,
both VMs deleted (`packages/engine/evidence/report_20261004T031503Z.md`). Building it caught a flaw first: an idle GPU
reads efficiency 0, which would have migrated shards off healthy nodes — fixed before any VM was created.

Then a real migration: CUDA shards on the VMs, a GPU load induced and declared on one node, the shard moved and
timed, 26.8 s → 20.3 s (`packages/engine/evidence/report_20261005T001234Z_rerender.html`).

Next: the heal is reactive — it re-runs a shard after reading the node, which only pays on long jobs; checking a
node before placing work there, live migration with state, and per-SKU thresholds (H100-tuned today; an L40S
tops out near 350 W). Not claimed as done.

---

## Testing instructions (paste block)

No key, no network, about 2 minutes:

```bash
git clone https://github.com/Rua987/nodus-gpu-engine
cd nodus-gpu-engine/packages/engine
pip install -r requirements.txt
python -m pytest -q
python -m nge.demo_nebius --mock --watch --watch-delay 2.0 --heuristic-plan
```

On a clean install the tests report about 490 passed and 26 skipped: the skipped ones need the optional
cloud SDKs (`nebius`, `cryptography`, `patch-ng`), which the mock path does not. The last command plays
the full loop on a simulated fleet (~85 s) and prints the path of an HTML report;
open it in a browser. Expected: a migration `nb-h100-02 → nb-h100-03` and 2 of 3 failures fixed and
verified. Recorded runs, including the live Nebius ones, are in `packages/engine/evidence/` with their
provenance in its `README.md`. The live path needs a Token Factory key (`--live`, see the README).

## Feedback — Token Factory, AI Cloud, NVIDIA (paste block)

From building this, in the order we hit things:

- **Token Factory — OpenAI-compatible was the right call.** Our backend is a thin, reversible patch over
  an OpenAI-style client; `usage` reports `reasoning_tokens`, which is how we found the next problem.
- **Nemotron 3 reasons inside `max_tokens`.** Our first live patches came back empty at 2048 tokens: 99 %
  of the output was reasoning and `content` was empty, with `finish_reason=length` as the only sign.
  `chat_template_kwargs: {"enable_thinking": false}` solved it for short replies. A per-request reasoning
  budget, or a clearer note in the model card, would save others that day.
- **Model ids are case-sensitive and not uniform** (`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, but
  `nvidia/nemotron-3-super-120b-a12b`); `GET /v1/models` was the source of truth.
- **Sandboxes (ContreeSDK):** stdout is cut at 64 KiB by default. The `truncated` flag exists but is easy to
  miss; our first real-GPU run counted a test that does not exist because of it. A warning, or a larger
  default, would help. Also: a `files` value of type `str` is read as a *local path* and only `bytes` as
  content — we shipped a file named after a whole diff before noticing. Occasional timeouts on file
  upload/download were absorbed by retries.
- **The default `python:3.12-slim` image** has no git and no `patch`; fine once known (we use `patch-ng`).
- **AI Cloud:** the Python SDK made a read-only inventory of every region easy, and an L40S VM was created in
  49 s. Friction was in the console: Token Factory ids (`aiproject-…`) and AI Cloud ids (`project-…`) look
  alike but are different worlds; the service-account page accepts an uploaded public key but offers no
  downloadable credentials file (the *Access keys* tab gives S3 keys, which Compute does not use), so we
  generate the key pair and assemble the SDK file ourselves; and the AI Cloud balance is separate from the
  Token Factory one. A per-instance time-to-live in the API would let us drop our own safety nets
  (labels, a cloud-init power-off, a refuse-if-leftovers check).
- **Nemotron itself:** Super was a solid triage and patch model once the token budget was right; on our
  seeded bugs every patch the loop verified was a real fix.

## Devpost page order (paste)

1. **Title + tagline** (above).  
2. **Problem** — GPU jobs die on throttle; suggested diffs land untested.  
3. **One command** (real CLI, not `nge run`):

```bash
python -m nge.demo_nebius --mock --watch --watch-delay 2.0 --heuristic-plan
```

4. **Screenshot** — HTML control room (fleet cards + Story + patches).  
5. **Four criteria** — the sections above.  
6. **Limits** — the heal is shown on simulated H100s; the patches are shown live (Token Factory + Nemotron, seeded
   bugs we wrote); Contree = CPU, heal gated;
   on real GPUs (L40S) the heal migrated once, under a load we induced and declared; no spontaneous overheating
   has been seen.

Do **not** invent “GPU $ saved”. We did not invoice that.

## Video / screenshot checklist

1. Terminal: the live film (A3) — real patches, `held-out: 5/5`; then the mock film for the migrate moment.
   Shot list and narration: `packages/engine/docs/JUDGE_DRY_RUN.md`, *YouTube video*.  
2. Browser: **control room** HTML (cards + Story + diffs).  
3. Optional 10 s: `--live` usage line + `heal gated` / `cpu-fallback`.  
3b. Optional 10 s: the Compute probe report — `probe_kind=nvidia-smi`, `NVIDIA L40S`, `deleted: true` — or the
    contention report `report_20261005T001234Z_rerender.html`: « induced load (declared) », « busy … on the GPU:
    ./nge_burn », « migrate … 26.8 s there, 20.3 s here ».  
4. Do **not** lead with taxonomy benches or AutoResearch.

---

## Do not write on Devpost

- “We heal real H100s in production today.”  
- “The engine heals real GPUs in production.” (one real migration, off an L40S held by a load we induced)
- “Migrating saved time.” (the same shard ran faster elsewhere; with the re-run and the VM boot, the run as a
  whole took longer)  
- “Ultra is billed on every `--live` plan.” (often 324M).  
- “3/3 always verified.”  
- DeepSeek / Ollama as the submission path (`NGE_TRACK=nebius` blocks them).
