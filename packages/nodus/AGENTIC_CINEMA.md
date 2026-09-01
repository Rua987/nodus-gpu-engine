# Agentic Cinema — compliant submission path

This document is the **single source of truth for hackathon judges**. The
Agentic Cinema rules allow only:

- **Google Cloud AI** — Gemini, Vertex AI Agent Builder (`google-genai`, ADC)
- **Partner track AI** — Grafana Cloud via `mcp-grafana` (Model Context Protocol)

All generative LLM execution in the judged demo runs on **Vertex AI /
Gemini**. The local 324M component is a **non-generative tool-name planner**
(fixed 8-tool vocabulary); it does not call OpenAI, Anthropic, AWS, Microsoft,
Ollama, OpenRouter, or any other third-party LLM API.

Set `NODUS_HACKATHON=1` to block non–Google Cloud LLM backends at runtime
(`nodus_backends.assert_hackathon_llm_model`).

---

## Judges — run the demo (no credentials)

Mock timeline, zero API keys, CI-friendly:

```bash
git clone https://github.com/Rua987/nodus && cd nodus
pip install -r requirements-ci.txt
python demo_agentic_cinema.py --task-key media
```

Optional: drop `checkpoints/checkpoint_sft_plan_v5.pt` (release v1.0.0) to
use the real 324M planner instead of the deterministic gold plan.

---

## Judges — live run (Vertex + Cloud Storage + Grafana)

Requires Google ADC (`gcloud auth application-default login` or
`GOOGLE_APPLICATION_CREDENTIALS`) and Grafana Cloud service account token.

```bash
pip install -r requirements-ci.txt
# .env.gcloud / .env.grafana or export GRAFANA_URL, GRAFANA_SERVICE_ACCOUNT_TOKEN, GCLOUD_BUCKET

python demo_agentic_cinema.py --live \
  --model vertex:gemini-2.5-flash \
  --task-key media
```

`--live` sets `NODUS_HACKATHON=1` and defaults the executor to
`vertex:gemini-2.5-flash`. Expected: real `gs://… [real]` upload, Grafana
annotations pushed via `mcp-grafana`, exit code 0.

Demo video (terminal recording of this path):
https://youtu.be/pG2VAql7aog

---

## Stack map (submission)

| Layer | Technology | Role |
|-------|------------|------|
| Planner | Local 324M (PyTorch) | Ordered tool **names** only |
| Executor + slot-fill | **Vertex AI / Gemini** (`vertex:gemini-2.5-flash`) | ReAct loop, argument fill |
| Delivery | **Google Cloud Storage** | `gcs_upload` harness tool |
| Observability | **Grafana Cloud MCP** | Tagged annotations per event |

---

## Local development backends (not used in submission)

`nodus_backends.py` still contains Ollama / OpenRouter / Anthropic / DeepSeek
routes for **local research**. They are **disabled** when `NODUS_HACKATHON=1`.
Do not use them for the Agentic Cinema demo or Devpost submission.
