# Nodus — 3-minute video narration script

**Format** : screen recording + voice-over. ~460 spoken words ≈ 3 min at
140 wpm. Timeline is a target; each segment is independent so you can trim
any segment without breaking the others.

**How to record the demo cleanly** :
```bash
# UTF-8 terminal so the timeline glyphs (→ ✓ ∘ ↳ ●) render correctly
# (Git Bash / Windows Terminal / VS Code all work; cmd.exe: chcp 65001)
python demo_agentic_cinema.py --task-key media   # the media demo timeline
python demo_agentic_cinema.py --contrast         # plan vs no-plan side by side
python demo_agentic_cinema.py --list-tasks       # for the intro card
# optional clip — real Vertex AI executor (needs GOOGLE_CLOUD_PROJECT + ADC)
python demo_agentic_cinema.py --live --model vertex:gemini-2.5-flash --task-key media
```
If `checkpoints/checkpoint_sft_plan_v5.pt` is present the demo uses the
**real 324M planner** (plan source: `[nodus]`); otherwise the gold plan
(`[demo-gold]`) — visually identical, deterministic, safe for recording.

---

## Segment 1 — 0:00 → 0:25 · "The expensive habit"

**Visual** : a terminal scrolls random tool calls while a "$ COST" meter climbs;
the screen glitches and cuts to the title card **NODUS — a tiny local planner**.

**Narration** (≈ 70 words):
> Every agentic system pays the same hidden tax: before it can do anything, a
> frontier model burns tokens just to plan. On simple tasks, planning can cost
> more than the work itself — and every step leaves your code in someone
> else's cloud. What if planning were free? What if a model small enough to
> run on a laptop CPU could do it, instantly and privately?

---

## Segment 2 — 0:25 → 0:55 · "The idea"

**Visual** : split screen. Left — the task
`Read src/utils.py, then save a config stub, then verify.` Right — a model card
(324M params · 24 layers · 768 embed · vocab 100k) resolving to the plan
`["read_file", "write_file", "bash"]`.

**Narration** (≈ 72 words):
> This is Nodus — a 324-million-parameter transformer, trained on one single
> job: turn a natural-language task into an ordered list of tool names. No
> arguments. No replanning. The harness fills the details, executes, and
> verifies. Because the planner is small and local, planning costs nothing and
> runs on CPU — your plan stays private. Execution is where you choose: a local
> model, or Gemini on Google Cloud's Vertex AI. The big model's only job is
> what it's actually good at: executing.

---

## Segment 3 — 0:55 → 1:45 · "The demo — a media workflow"

**Visual** : live record `python demo_agentic_cinema.py --task-key media`.
Pause ~1s per line as the timeline appears; hover the cursor over the plan
line, the gs:// upload URI, then the ✓ results.

**Narration** (≈ 108 words):
> Here's the whole pipeline, end to end — on a real media workflow. A task
> arrives: read the script, write the shoot-day brief for scene three, and
> deliver it to Google Cloud Storage. The executor can run on Gemini through
> Vertex AI — Google's Agent Builder platform. The planner answers in tool
> names: read, write, upload. The harness takes over — fills the arguments,
> runs each step,
> verifies the result. Read the script. Write the brief. Upload it — here's the
> gs:// URI, delivered. Every one of these events streams to Grafana Cloud as a
> live annotation, so the dashboard becomes the agent's scope. With a plan, the
> whole media task completes in four steps. That is the product.

---

## Segment 4 — 1:45 → 2:20 · "The evidence"

**Visual** : metric cards. "119 / 120 = 99% · 0 regressions · 120 unseen tasks"
then the sign-test table — plan better 27 · plan worse 11 · p = 0.0139.

**Narration** (≈ 78 words):
> Is this real? On a fresh holdout of one hundred and twenty tasks — brand-new
> entities the model never saw in training — Nodus plans one hundred and
> nineteen correctly: ninety-nine percent, zero regressions. Generalization,
> not memorized answers. Across two hundred runs the plan measurably helps the
> executor — better on twenty-seven tasks, worse on only eleven — a sign test
> at p equals zero point zero one three nine, statistically significant. And
> the effect grows with plan length — exactly where agents need help most.

---

## Segment 5 — 2:20 → 2:45 · "Google Cloud delivery + Grafana Cloud"

**Visual** : split screen. Left: the `gcs_upload` line from segment 3, zoomed —
`gcs_upload` → `gs://nodus-media-demo/production/shoot_day_brief.md [mock]`,
plus the wiring `NODUS_GCLOUD=real` → `google-cloud-storage` SDK →
`GCLOUD_BUCKET` + ADC. Small overlay card: "mock-first: no credentials needed —
the real SDK path activates with `NODUS_GCLOUD=real`". Right: the event stream
`task → plan → tool_call → tool_result → result` carrying `kind` tags
(`nodus:task`, `nodus:plan`, …) → `mcp-grafana` server → `create_annotation`.

**Narration** (≈ 72 words):
> Execution is powered by Gemini on Vertex AI — Google Cloud's Agent Builder
> runtime — through the official SDK. Delivery is powered by Google Cloud too:
> the upload tool calls the official Cloud Storage SDK when credentials are
> present, and prints an honest, deterministic mock URI when they're not — so
> the demo runs with zero setup. In parallel,
> every event — task, plan, every tool call and result — is tagged and streamed
> to Grafana Cloud through the official MCP server. Point it at your Grafana,
> and the whole run lands live in your dashboard.

---

## Segment 6 — 2:45 → 3:00 · "Close"

**Visual** : repo card `github.com/Rua987/nodus`, the README headline
("119/120 · 99%"), a test run ending `900+ passed`, the MIT LICENSE badge.

**Narration** (≈ 66 words):
> Nodus is open source — MIT licensed. Nine hundred-plus tests passing, and a
> checkpoint you can drop in and run on a laptop CPU. And the planner's cost
> stays flat as tasks grow longer — bigger loops scale the work, not the
> planning bill. If you want your agent to plan for free, deliver to the cloud,
> and watch every step — clone the repo, and let it think. Thank you.

---

## Shot list (quick reference)

| Time | Shot | Audio |
|---|---|---|
| 0:00 | agent flails + cost meter → title card | Segment 1 |
| 0:25 | split screen: task → model card → plan | Segment 2 |
| 0:55 | live `--task-key media` timeline (read → write → gs:// upload → verify) | Segment 3 |
| 1:45 | metric cards: 99% then p=0.0139 table | Segment 4 |
| 2:20 | Vertex AI executor + GCS delivery + event stream → Grafana MCP mapping (split screen) | Segment 5 |
| 2:45 | repo card + `900+ passed` + MIT badge | Segment 6 |

**Production notes**
- Record at 1080p, 30 fps; keep a 1–2 s hold on every visual before narration
  starts so cuts don't feel rushed.
- The demo glyphs need a UTF-8-capable terminal; if they ever render as `?`
  on your setup, the output is still fully readable — don't re-record for that.
- Optional cut: if the segment 3 contrast clip makes the video run long, drop
  the "no plan" part and keep only the with-plan timeline.
- Optional clip: the live Vertex AI executor (`--live --model
  vertex:gemini-2.5-flash`) is a strong 10 s shot if the real run is clean —
  it shows Gemini on Google Cloud's Agent Builder platform functioning as
  built (per the brief). Requires `GOOGLE_CLOUD_PROJECT` + ADC.
