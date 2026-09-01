# Nodus

**A tiny local planner that turns a natural-language task into an ordered
sequence of tool calls — with media & entertainment workflows, Google Cloud
delivery, and an observability layer that streams every step into Grafana
Cloud.**

> Nodus is a research planner developed for a 324M-parameter model (trained
> locally, runs on CPU or a single GPU). The planner outputs **only tool names**
> — no arguments, no replanning. The harness fills the arguments, verifies each
> step, executes, and **delivers** the final artifact (Google Cloud Storage).

**Agentic Cinema judges:** see **[AGENTIC_CINEMA.md](AGENTIC_CINEMA.md)** for the
compliant demo path (Vertex AI / Gemini + Grafana Cloud MCP only).

---

## Why Nodus?

Agentic loops are expensive: a big frontier model plans each task token-by-token,
then an executor re-derives the same steps. Nodus replaces the planning phase
with a **fixed, tiny, local model** that was fine-tuned on one single task:

> NL task → ordered JSON array of tool names (`["glob", "read_file", "edit_file"]`)

Because the planner is small and local, planning is **free, private, and fast**
— no API call, no prompt re-sent, no data leaving the machine. The executor
keeps the last word (it fills real arguments and verifies), so Nodus is a
*suggestion engine*, not a replacement for the loop.

**Measured on unseen tasks** (120-task fresh holdout, entities never seen in
training):

| Planner | Plan accuracy (raw) | + guardrails |
|---|---|---|
| previous (v2b) | 79% | 91% |
| **Nodus (v5)** | **99%** | **99%** |

- 0 guardrail regressions across all replays.
- **End-to-end significance** (statistical, p = 0.0139, sign test over 200
  runs): Nodus planning *significantly improves* a local executor on multi-step
  tasks — 27 tasks better, 11 worse, effect growing with plan length.

---

## The demo: watch Nodus think, in Grafana

Nodus integrates **Grafana Cloud MCP** (`mcp-grafana`) as its observability
layer. Every run streams structured events — task, plan, each tool call, each
result — into a Grafana dashboard as live annotations:

```
▶ task: deploy the app then verify health
  ∘ plan [nodus]: ['bash', 'bash']
    ↳ tool bash {"command": "echo step1"}   ✓ ok
    ↳ tool bash {"command": "echo step2"}   ✓ ok
● result: Done.
```

- **mock mode** (default, zero setup, no token): events collected in memory +
  JSONL — perfect for the video / CI.
- **live mode**: `NODUS_GRAFANA=mcp` + `GRAFANA_URL` + `GRAFANA_SERVICE_ACCOUNT_TOKEN`
  (Grafana Cloud free tier, service account `glsa_…`). Each event becomes a
  `mcp-grafana.create_annotation` call through the official `mcp-grafana` server
  (tools are namespaced by the server's self-reported name, not the config key).

---

## Quick start

```bash
# 1. Install Python deps (torch optional — planner runs on CPU)
pip install -r requirements-ci.txt

# 2. Optional: drop the planner checkpoint into checkpoints/ to use the
#    real 324M planner (~940 MB — see "Checkpoints" below)

# 3. Plan a task (mock telemetry, no Grafana account needed)
python nodus_plan_local.py --plan-once
#   echo "read src/main.py, then search for request_id, then edit it" | \
#     python nodus_plan_local.py --plan-once
#   → {"ok": true, "names": ["read_file", "grep", "edit_file"]}

# 4. Agentic Cinema judges — live run (Vertex + Grafana; see AGENTIC_CINEMA.md)
python demo_agentic_cinema.py --live --model vertex:gemini-2.5-flash --task-key media

# 4b. Or stream a custom task via nodus_agent (Vertex executor required)
NODUS_HACKATHON=1 NODUS_GRAFANA=mcp python nodus_agent.py "..." \
  --plan --plan-source nodus --model vertex:gemini-2.5-flash
```

## Run the demo (30 seconds, zero dependencies)

`demo_agentic_cinema.py` replays the full pipeline end to end — task → plan →
tools → delivery → Grafana — deterministically, with **no checkpoint, no cloud
credentials, no LLM API** required for the mock path. Add
`checkpoints/checkpoint_sft_plan_v5.pt` (or set `NODUS_PLAN_CKPT`) and the same
command uses the **real 324M planner** instead of the gold plan:

```bash
python demo_agentic_cinema.py                 # plan → tools → timeline (mock)
python demo_agentic_cinema.py --list-tasks    # show the curated demo tasks
python demo_agentic_cinema.py --task-key media # media workflow (shoot-day brief)
python demo_agentic_cinema.py --contrast      # plan vs no-plan side by side
python demo_agentic_cinema.py --live --model vertex:gemini-2.5-flash --task-key media
# live: Vertex AI executor + real GCS + Grafana (ADC + Grafana token — see AGENTIC_CINEMA.md)
```

The **media** task is the Agentic Cinema use case: read the script, save the
shoot-day brief (the script is scene 3) as a new file, **upload it to Google
Cloud Storage** (`gcs_upload`, mock-first — deterministic `gs://` URI without
credentials), and verify. The planner keeps its fixed 8-tool vocabulary; GCS
delivery is a *harness capability* (like the Grafana observability layer).

It streams every step through the same `GrafanaSink` — mock mode prints the
timeline, `NODUS_GRAFANA=mcp` pushes live annotations to Grafana Cloud:

```
▶ task: Read script.txt, then save a new file shoot_day_brief.md with the shoot-day brief, then upload it to Google Cloud Storage, then verify.
  ∘ plan [nodus]: ['read_file', 'write_file', 'bash', 'gcs_upload']
    ↳ tool read_file {"path": "script.txt"}
      ✓ SCENE 3  INT. EDIT BAY — DAY  The editor pulls up the dailies…
    ↳ tool write_file {"path": "shoot_day_brief.md", "content": "# Shoot-day brief — Scene 3…"}
      ✓ wrote 244 bytes -> shoot_day_brief.md
    ↳ tool bash {"command": "ls"}
      ✓ script.txt  shoot_day_brief.md
    ↳ tool gcs_upload {"local_path": "shoot_day_brief.md", "destination": "production/shoot_day_brief.md", "bucket": "nodus-media-demo"}
      ✓ gs://nodus-media-demo/production/shoot_day_brief.md (253 bytes) [mock]
● result: Done: wrote shoot_day_brief.md; uploaded production/shoot_day_brief.md.
```

With `NODUS_GCLOUD=real` + ADC credentials, the same `gcs_upload` step performs
a real upload — the URI marker switches from `[mock]` to `[real]`. The full
stack (Vertex AI executor → real upload → live Grafana annotations) was
validated end to end; the `[real]` upload and the annotation count are
confirmed through the Google Cloud and Grafana APIs.

### Grafana Cloud live setup (one time)

1. Create a free account at [grafana.com](https://grafana.com/cloud/).
2. **Administration → Service accounts** → add a token (`glsa_…`) with
   `dashboards:write` (annotations).
3. Run with the env vars above; the harness starts `mcp-grafana` automatically —
   the console script from `pip install mcp-grafana` (logs to stderr = clean
   stdio transport), else `uvx mcp-grafana`, else `npx -y @leval/mcp-grafana`
   (npm, logs to stdout — last resort). Override the launcher with
   `NODUS_GRAFANA_SERVER="mcp-grafana"` (or any command string).
   Each event calls `create_annotation`.

---

## Google Cloud: Gemini executor + Cloud Storage delivery

Nodus is powered by Google Cloud in two places — both imported and called in
**code** at runtime, both mock-first:

1. **Gemini as an executor** — any model id prefixed with `gemini:` routes the
   ReAct loop through the official `google-genai` SDK with native function
   calling (the same normalized message format every other backend speaks):

   ```bash
   export GEMINI_API_KEY=...
   python nodus_agent.py "Read script.txt, then write the shoot-day brief, then upload it" \
     --plan --plan-source nodus --model gemini:gemini-2.5-flash
   ```

   *Optional: `pip install google-genai`. Without the package, the run fails
   loudly only if you actually request a `gemini:` model.*

   **Vertex AI — Google Cloud Agent Builder** — the same executor can run on
   **Vertex AI** (Google Cloud's Agent Builder / Gemini Enterprise platform)
   using Application Default Credentials instead of an API key. Any model id
   prefixed with `vertex:` routes the loop through the same `google-genai`
   SDK built with `vertexai=True`:

   ```bash
   export GOOGLE_CLOUD_PROJECT=<your-gcp-project-id>
   # user OAuth ADC (recommended — works even where service-account key
   # creation is disabled by org policy):
   #   gcloud auth application-default login
   # or point GOOGLE_APPLICATION_CREDENTIALS at a service-account JSON key:
   #   export GOOGLE_APPLICATION_CREDENTIALS=service-account.json
   python nodus_agent.py "Read script.txt, then write the shoot-day brief, then upload it" \
     --plan --plan-source nodus --model vertex:gemini-2.5-flash
   ```

   *Region: `GOOGLE_CLOUD_LOCATION` (default `us-central1`); the Vertex AI API
   must be enabled in the project. Same `pip install google-genai` requirement —
   the run fails loudly only if you actually request a `vertex:` model.*

2. **`gcs_upload` — deliver the produced asset to Cloud Storage** — the final
   step of the media workflow. Deterministic mock by default (no credentials,
   no network); real upload via the official `google-cloud-storage` SDK when
   credentials are present:

   ```bash
   # mock (default): deterministic gs:// URI, no credentials
   NODUS_GCLOUD=mock python demo_agentic_cinema.py --task-key media

   # real: Google Cloud Storage upload via ADC
   $env:GCLOUD_BUCKET = "nodus-media-demo"
   $env:GOOGLE_APPLICATION_CREDENTIALS = "service-account.json"
   $env:NODUS_GCLOUD = "real"
   python demo_agentic_cinema.py --task-key media
   ```

   *Optional: `pip install google-cloud-storage`. `gcs_upload` is a **harness
   capability tool** — the 324M planner keeps its fixed 8-tool vocabulary; the
   harness delivers the final artifact (exactly like the Grafana observability
   layer). A failed upload is never fatal to a run (silent fallback + counter).*

**Why mock-first?** The whole demo runs with zero credentials — deterministic
and CI-friendly — while the *real* SDK code path is exercised the moment
`NODUS_GCLOUD=real` and ADC credentials exist. No fake data: a `[mock]` marker
on every `gs://` URI makes the mode explicit.

---

## Repository layout

```
bridge/            plan bridge: prompt, parser, tool schemas, versions
nodus_plan_local.py  local inference (plan NL → tool names)
nodus_auto_model.py  model architecture (324M)
nodus_gpt.py         transformer core (RoPE, RMSNorm)
nodus_agent.py       ReAct executor loop (fills args, verifies, executes)
nodus_verify.py      guardrails: normalize + 7 predicates + transformations
nodus_grafana.py     Grafana Cloud telemetry sink (mock / mcp / off)
nodus_gcloud.py      Google Cloud Storage delivery (mock / real / off)
nodus_mcp_client.py  multi-server MCP registry (namespacing, pinning)
nodus_backends.py    Google Cloud executors (Gemini · Vertex AI via google-genai);
                     local-dev backends gated when NODUS_HACKATHON=1 (see AGENTIC_CINEMA.md)
demo_agentic_cinema.py  self-contained demo: task → plan → tools → GCS → Grafana
AGENTIC_CINEMA.md       hackathon judges: compliant commands + stack map
video_script_3min.md    3-minute narration script for the hackathon video
devpost_draft.md        Devpost submission draft (copy-paste ready)
tests/             994 passing tests (pytest)
```

### Guardrails (why 99% is real)

`nodus_verify.py` normalizes the raw plan: it fixes the systematic failure
classes the model was trained against (superfluous `grep` before `read`,
`bash`-as-write, missing final `write`) and validates the result. The guardrail
never *replaces* the executor — it makes the suggestion robust.

---

## Checkpoints

The model weights are **not** committed to git (too large) — and you don't
need them to run the demo: `python demo_agentic_cinema.py --task-key media`
replays the pipeline deterministically with **no checkpoint, no credentials**
(see "Run the demo" above). Adding the weights switches the same command to
the **real 324M planner** (an ~8-second media run on GPU):

```bash
export NODUS_PLAN_CKPT=checkpoints/checkpoint_sft_plan_v5.pt
# or: $env:NODUS_PLAN_CKPT = "checkpoints\checkpoint_sft_plan_v5.pt"
```

Where the weights come from:

- **Download the v5 production weights** — the ones behind the 99% holdout and
  p = 0.0139 numbers cited above: release **v1.0.0**,
  [`checkpoint_sft_plan_v5.pt`](https://github.com/Rua987/nodus/releases/tag/v1.0.0)
  (~1 GB, SHA256 `9637ae13…`). Drop it into `checkpoints/` and the demo uses
  the real 324M planner.
- **Your own SFT** — the training recipe is summarized under "Training &
  method" below (20k planning examples, ~3.5 GPU-minutes).

---

## Training & method (summary)

Nodus v5 was fine-tuned from v2b on 20k planning examples (60% "hard" steps),
scheduled on a rented RTX 5090 for ~3.5 GPU-minutes. It was promoted to
production after a **fresh 120-task holdout** (no entity overlap with any
training or validation corpus) showed 99% plan accuracy with zero guardrail
regressions — a decisive improvement over the previous planner (91%).

---

## Tests

```bash
python -m pytest tests/        # 994 passed
```

---

## License

Released under the **MIT License** — see [LICENSE](LICENSE). The AI-generated
assets in the repo (video script, Devpost draft, gallery image) are included
under the same license.

---

*Prepared for the Agentic Cinema hackathon (Google Cloud + partners).
Google Cloud: Gemini + Vertex AI executor (`google-genai`, `vertexai=True` for
the Agent Builder runtime) + Cloud Storage delivery (`gcs_upload`).
Partner service: Grafana Cloud MCP (`mcp-grafana`).*
