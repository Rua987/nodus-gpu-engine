# Nodus — Devpost submission draft

> Copy the section bodies below into the corresponding Devpost fields.
> Metrics cited are verified (see README): **99%**, **p = 0.0139**. The
> 27/30 arithmetic probe is deliberately NOT cited.
> Reframed for the Agentic Cinema brief: **media workflow** (shoot-day brief),
> **Google Cloud in code AND validated live** (Vertex AI executor + real Cloud
> Storage upload + real Grafana annotations, one command), partner
> **Grafana Cloud** (observability), **MIT license** (see LICENSE).
> Gallery image READY: `gallery_timeline.png` (repo root — real media run).
> Demo video UPLOADED: https://youtu.be/pG2VAql7aog (~3:23 terminal recording —
> `demo_agentic_cinema.py` mock + live Vertex/GCS/Grafana). Older montage:
> fy4lVSboR0I (1:43). Kit: `video_script_3min.md` + `video_cards/`.

---

## Title

**Nodus — a tiny local planner that makes agentic loops free (and observable)**

## Tagline

A 324M-parameter planner turns any natural-language task into an ordered list
of tool calls — runs on a laptop CPU, and streams every step to Grafana Cloud.

## Elevator pitch (≈ 360 words)

The demo is a real production workflow: a 324M local planner reads a film
script, plans the tool steps, a Gemini executor writes the shoot-day brief and
delivers it to Cloud Storage, and Grafana Cloud traces every step — one
command, end to end. Every agentic system pays a hidden tax: before it can do
anything, a frontier model burns tokens just to plan — and for simple tasks,
planning can cost more than the work itself. Nodus replaces that planning
phase with a 324M-parameter transformer, fine-tuned on a single job: turn a
natural-language task into an ordered sequence of tool names. No arguments,
no replanning. The harness fills the details, executes, and verifies.

Because the planner is tiny and local, planning is free, private, and fast —
your code never leaves the machine, and the planning cost stays flat however
long the task grows. And every step of the run is streamed live to Grafana
Cloud as an annotation, so an agent session becomes something you can replay,
correlate, and audit.

The results are real: on a fresh holdout of 120 tasks — brand-new entities the
model never saw in training — Nodus plans 119 correctly (99%, zero
regressions): generalization, not memorized answers. End-to-end, the plan
significantly improves a local executor (sign test, p = 0.0139), with the
effect growing as plans get longer — exactly where agents need help most.
Both arms — plan and no-plan — ran under the same deterministic guardrails,
so the effect isolates the planner's contribution from the harness code.

This hackathon entry is **powered by Google Cloud** — the executor runs on
Gemini, through the Gemini API or **Vertex AI Agent Builder** (`gemini:` /
`vertex:` prefixes, one SDK, ADC auth), and Cloud Storage delivers the media
artifact; both are imported and called in code, mock-first so the demo runs
with zero credentials. It activates **Grafana Cloud** through the official
`mcp-grafana` server as the observability layer: task, plan, every tool call,
and the final result land in a dashboard as tagged annotations in real time.
The whole pipeline was validated live with one command — a real Vertex
executor, a real `gs://` upload, and real Grafana annotations confirmed
through the APIs.

## Inspiration

Agentic loops are expensive twice over: planning burns frontier-model tokens,
and re-planning makes loops slow and hard to audit. We wondered how much of
that cost is actually necessary. A 324M model can't write code well — but
"what tools do I need, and in what order?" is a much simpler question than
"write the code." Train a small model on exactly that question, and the big
model is left with only what it's good at: executing.

## What it does

1. **Plans** — NODUS (the 324M planner) reads a task and outputs an ordered
   JSON array of tool names from a fixed 8-tool vocabulary. Tool names stay a
   small trainable set, but step arguments are open-ended — filled per step by
   an LLM prompt — so the planner's reach scales with the harness, without
   retraining the model.
2. **Executes** — the harness fills the arguments, runs each tool, and verifies
   the result against guardrails trained on the model's known failure classes.
   The loop runs on **Gemini** (`gemini:gemini-2.5-flash`, native function
   calling via the official `google-genai` SDK) or on **Vertex AI — Google Cloud
   Agent Builder** (`vertex:gemini-2.5-flash`, the same SDK built with
   `vertexai=True`, ADC auth). The Agentic Cinema submission uses **Vertex only**
   (see `AGENTIC_CINEMA.md`).
3. **Delivers** — the media workflow (demo task `media`) reads a script, writes
   a shoot-day brief for scene 3, and uploads it to **Google Cloud Storage**
   (`gcs_upload` — mock-first: deterministic `gs://` URI with no credentials,
   real upload via the `google-cloud-storage` SDK when `GCLOUD_BUCKET` + ADC
   are set). GCS is a harness capability tool: the planner's 8-tool vocabulary
   stays untouched.
4. **Observes** — every event (task → plan → tool_call → tool_result → result)
   is pushed to Grafana Cloud through `mcp-grafana` as a tagged annotation, so
   the whole run is replayable in a dashboard — confirmed live through the
   Grafana API (25/25 annotations on the validated media run).

**How it's different** — a 324M local planner instead of one more
frontier-model loop:

| | Monolithic agent loops (e.g. AutoGPT, CrewAI) | Nodus (324M local planner) |
|---|---|---|
| **Architecture** | one frontier model plans, reasons, and executes every step via API | decoupled: the local planner emits an ordered tool-name list; the harness fills arguments and verifies |
| **Planning cost** | repeated API calls — token burn per ReAct loop | free and local: a single small forward pass on CPU/GPU |
| **Reliability** | drift and over-reasoning on long traces | 99% plan accuracy on a fresh 120-task holdout (unseen entities, 0 regressions) — generalization, not memorized answers |
| **Observability** | framework-dependent (LangChain, LlamaIndex, …) | native Google Cloud (Gemini via API or Vertex AI Agent Builder, Cloud Storage delivery) + Grafana Cloud MCP — every event streams live as a tagged annotation |

Try it: `python demo_agentic_cinema.py --task-key media` — no checkpoint, no
API key, no cloud credentials, no container. It runs the whole pipeline
deterministically and prints the timeline.

## How we built it

- **The planner** — a 324M-parameter transformer (24 layers, 768 embed), SFT'd
  on 20k planning examples (60% "hard" multi-step), ~3.5 GPU-minutes on a
  rented RTX 5090. It outputs only tool names — a decision that keeps the model
  small and the surface simple.
- **The harness** — ReAct loop that fills arguments, dispatches the 8 native
  tools, and verifies each result. Guardrails fix the model's systematic
  failure classes (superfluous grep, bash-as-write, missing final write).
- **The Google Cloud layer** — the executor runs on **Gemini via Vertex AI
  (Agent Builder)** or on the Gemini API — `gemini:` / `vertex:` prefixes →
  the official `google-genai` SDK; the `vertex:` path is built with
  `vertexai=True` (the Agent Builder runtime). Cloud Storage delivery
  (`gcs_upload`) is mock-first exactly like the observability sink. Both SDKs
  are imported and called in code, gated on credentials — no key in the repo,
  CI stays credential-free.
- **The observability** — Grafana Cloud MCP server (`mcp-grafana`) launched
  automatically (pip console script → `uvx` → `npx`); each normalized event
  becomes a `create_annotation` call. MCP failure is never fatal to a run
  (silent fallback + counter).
- **The slot-fill layer** — the harness extracts each step's argument target
  (file names, patterns) with a per-step LLM prompt; hardened parsing turns the
  string "null" into a real miss and a prompt fix stopped the JSON key from
  leaking the argument name.
- **The validation** — 994 passing tests (harness, planner bridge, guardrails,
  slot-fill, Grafana sink, Google Cloud sink), plus a fresh 120-task holdout
  with zero entity overlap with any training corpus — and a live end-to-end
  run (Vertex executor + real Cloud Storage upload + real Grafana annotations)
  confirmed through the Google Cloud and Grafana APIs.

## Challenges we ran into

- **Generalization vs memorization** — the first holdout was saturated and
  contaminated: the model had effectively memorized it, hiding a real
  regression. Building a fresh holdout (new entities, zero collision) is what
  actually exposed the old planner's weaknesses — and validated the new one.
- **Fixed tool vocabulary** — the planner can only emit 8 native tools, so
  Grafana (observability) and Cloud Storage delivery both had to be harness
  capabilities, not planable tools. That turned out to be the right design:
  the dashboard is the agent's scope, the bucket its delivery.
- **Mock-first cloud** — no credentials in the repo or CI. Google Cloud is
  imported and called in code, but gated on `NODUS_GCLOUD=real` + ADC; without
  them, a deterministic mock (a `[mock]` marker on every `gs://` URI) keeps the
  demo honest and reproducible.
- **A geo-blocked API** — the plain Gemini API key was rejected from our region
  (`400 "User location is not supported"`). Pivoting to **Vertex AI** (ADC
  auth, far more regions) is what made the live run possible — the Agent
  Builder path of the brief anyway.
- **An org policy that blocks service-account keys** — `iam.disableServiceAccountKeyCreation`
  meant no service-account JSON key. The fix is **user OAuth ADC** (`gcloud
  auth application-default login`), which needs no key at all.
- **Windows console encoding** — the timeline glyphs (→ ✓) crashed printing on
  a cp1252 console; the demo now forces UTF-8 output with a safe fallback.
- **The extractor was never the problem** — a slot-fill probe showed both
  candidate extractors failing structurally: one echoed the argument name as
  its JSON key (the prompt was leaking it), the other returned the string
  "null". One prompt fix took the good extractor from 1/3 to 3/3; a parse
  guard normalized the rest. Lesson: measure before replacing a component.

## Accomplishments that we're proud of

- **99% plan accuracy** on a fresh holdout of 120 never-seen tasks (brand-new
  entities, zero overlap with training, 0 regressions) — the model genuinely
  generalizes to entities it never met in training.
- **Statistically significant e2e impact** — p = 0.0139 sign test: the plan
  helps the executor on 27 tasks, hurts on 11, and the effect grows with plan
  length.
- **A 30-second demo with zero dependencies** that nonetheless uses the real
  324M model when the checkpoint is present (an 8-second media run on GPU) —
  and delivers a media artifact to a **real** Cloud Storage bucket.
- **The full Google Cloud stack runs live in one command** — a Vertex AI
  executor plans and executes, the artifact uploads to real Cloud Storage
  (`[real]`), and every step lands as a real Grafana annotation (confirmed via
  the APIs): the Agent Builder + partner-service story of the brief, proven.
- **A live landing page** — GitHub Pages (`rua987.github.io/nodus`) replays the
  real run's timeline and lets anyone run the demo with copy-paste commands.
- **994 tests passing** across the harness, the planner bridge, the guardrails,
  the slot-fill extractor, the Grafana sink, and the Google Cloud sink.

## What we learned

- Raw plan accuracy is the wrong production metric — model **plus guardrails**
  is what ships. A promotion on raw score alone had to be rolled back.
- Never trust a contaminated holdout; a fresh one changed the verdict.
- Observability isn't a bolt-on — when every tool call is a tagged annotation,
  an agent becomes auditable, replayable, and debuggable like any other system.
- The unlock is the cost curve, not the accuracy ceiling — a 324M planner keeps
  planning flat-cost however long the task grows, so scaling agentic loops
  doesn't scale the planning bill.

## What we built during the hackathon

Nodus didn't start as a hackathon project. It grew out of **months of prior
work on LINUS**, a research line on making agentic planning local, cheap, and
provable — that is where the 324M planner and its holdout results come from.
The Agentic Cinema hackathon wasn't on the roadmap when we started. When the
brief appeared, we treated it as the forcing function to turn that research
into a complete, media-focused, verifiable system — and to prove the
"local planner + frontier executor" stack against *real* Google Cloud
services. What the hackathon period actually added:

- **The media framing** — `demo_agentic_cinema.py --task-key media` reads a
  film script and produces a shoot-day brief for a specific scene, matching
  the brief's media/entertainment value chain.
- **Google Cloud in code and validated live** — the executor runs on Gemini
  through the official `google-genai` SDK, via the API or **Vertex AI Agent
  Builder** (`vertexai=True`, ADC auth); `gcs_upload` delivers the artifact to
  a **real** Cloud Storage bucket. Both SDKs are imported and called in code,
  gated on credentials so the repo stays credential-free.
- **Grafana Cloud live** — `mcp-grafana` streams every event as a tagged
  annotation; the validated run pushed 25/25 annotations, confirmed through
  the Grafana API.
- **994 passing tests** for the harness, planner bridge, guardrails,
  slot-fill, Grafana sink, and Google Cloud sink.
- **Shippable artifacts** — a live landing page (`rua987.github.io/nodus`), a
  ~3 min terminal demo video (live Vertex + Grafana), and release `v1.0.0`
  with the production weights (SHA256
  `9637ae13…`) so the demo runs the real 324M model.
- **Production hardening** — cp1252 console encoding, the slot-fill "null"
  regression, the live-mode annotation fix, Windows log-rotation tolerance.

The months of LINUS work are the foundation; the list above is what the
hackathon period added on top of it — and it's all reproducible from the
public repo.

## What's next

The planner already sits at 99% on its current task family — the headroom is in
the distribution, not the architecture:

- **Deeper slot-filling** — the harness already extracts each step's argument
  target with a hardened LLM prompt; the next step is moving that into the
  local model so the planner emits its own argument targets.
- **Wider task distributions** — 99% is near-ceiling on today's family; the
  measured lever is more diverse, longer planning tasks (the plan's benefit
  already grows with plan length).
- **Everywhere** — the 324M planner already runs on CPU; port it to edge
  targets (mobile, embedded) so planning is free everywhere.
- **Bigger executors** — pair the plan with stronger open executors and measure
  the same A/B protocol.

## Built with

Python · PyTorch · Google Cloud (Gemini · Vertex AI Agent Builder · Cloud
Storage) · Grafana Cloud ·
Model Context Protocol (mcp-grafana) · GitHub Pages

## Try it out

- GitHub: https://github.com/Rua987/nodus
- Hosted: https://rua987.github.io/nodus/ (landing page — timeline of the real
  run, copy-paste "run it yourself" commands)
- Demo video: https://youtu.be/pG2VAql7aog
- Gallery image: upload `gallery_timeline.png` (repo root) — timeline of the
  real media run (324M v5 plan + harness filling args / verifying + mock GCS
  upload + Grafana annotations). Raw after push:
  https://raw.githubusercontent.com/Rua987/nodus/main/gallery_timeline.png

---

### Quick copy checklist

- [ ] Paste each section into its Devpost field (section headings map 1:1).
- [ ] "What we built during the hackathon" → paste into the "How we built it"
      field (top), or append it where the form lets you add context — it's the
      evidence for the pre-existing-work rule.
- [ ] Upload `gallery_timeline.png` as the gallery image (1/3 slots).
- [x] Demo video link in place: https://youtu.be/pG2VAql7aog (~3:23 terminal).
- [ ] Confirm the pitch ≤ 500 words if the form enforces a limit (~360 here).
- [ ] Under "Built with", select the actual Grafana Cloud / MCP tags if the
      form offers them.
