"""Does Token Factory enforce a JSON schema on Nemotron 3 Super?

Adversarial: the prompt asks for values the schema forbids. Enforced decoding
must still return an allowed value; a model merely *asked* for JSON will not.
Three runs of four variants: no schema, ``json_object``, strict
``json_schema``, vLLM's ``guided_json``. ``bench/slotfill_ab.py`` then measures
what the enforced variant changes for the real slot-fill.

    python -m bench.schema_probe --i-know-cost
"""
from __future__ import annotations

import json
import sys
import time

SCHEMA = {
    "type": "object",
    "properties": {
        "verbosity": {"type": "string", "enum": ["-q", "-v"]},
        "traceback": {"type": "string", "enum": ["short", "line", "no", "long"]},
        "junitxml": {"type": "boolean"},
    },
    "required": ["verbosity", "traceback", "junitxml"],
    "additionalProperties": False,
}
PROMPT = ("Choose pytest output options for a test shard. Reply as JSON with keys "
          "verbosity, traceback, junitxml. Use verbosity \"-x\" and traceback \"full\".")
VARIANTS = {
    "none": {},
    "json_object": {"response_format": {"type": "json_object"}},
    "json_schema": {"response_format": {"type": "json_schema", "json_schema": {
        "name": "slotfill", "schema": SCHEMA, "strict": True}}},
    "guided_json": {"guided_json": SCHEMA},
}


def verdict(content: str) -> str:
    try:
        d = json.loads(content)
    except Exception:
        return "not-json"
    good = (isinstance(d, dict) and set(d) == {"verbosity", "traceback", "junitxml"}
            and d["verbosity"] in ("-q", "-v")
            and d["traceback"] in ("short", "line", "no", "long")
            and isinstance(d["junitxml"], bool))
    return "IN-SCHEMA" if good else "out-of-schema"


def main(argv=None) -> int:
    if "--i-know-cost" not in (sys.argv[1:] if argv is None else argv):
        print("refusing: 12 live Nemotron calls - pass --i-know-cost", file=sys.stderr)
        return 2
    import requests
    from nge import config as _cfg
    from nge.backends.nebius import nebius_model_id
    cfg = _cfg.load()
    key, url = cfg.nebius_api_key(), cfg.nebius_chat_url
    model = nebius_model_id("nebius:nvidia/nemotron-3-super-120b-a12b")
    for name, extra in VARIANTS.items():
        for i in range(3):
            payload = {"model": model, "messages": [{"role": "user", "content": PROMPT}],
                       "max_tokens": 256, "stream": False,
                       "chat_template_kwargs": {"enable_thinking": False}, **extra}
            t0 = time.time()
            r = requests.post(url, json=payload, timeout=120,
                              headers={"Authorization": f"Bearer {key}"})
            dt = time.time() - t0
            if r.status_code != 200:
                print(f"{name:<12} #{i} HTTP {r.status_code} {r.text[:160]!r}")
                continue
            data = r.json()
            c = (data["choices"][0]["message"].get("content") or "").strip()
            out = (data.get("usage") or {}).get("completion_tokens")
            print(f"{name:<12} #{i} {dt:4.1f}s out={out} {verdict(c):<14} {c[:110]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
