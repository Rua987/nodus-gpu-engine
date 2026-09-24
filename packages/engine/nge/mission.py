"""Turn an engineer's natural-language mission into a run scenario.

The engineer expresses the *what*:

    nge run --mission "Run my pytest suite in ./tests/unit across 3 H100s
                       and self-heal if a node throttles"

and this maps it to the *how* (the scenario dict the orchestrator consumes):
shard count, GPU type, target path, artifacts, self-heal intent. Deterministic
and testable; ``--live`` can later route the mission through Nemotron Ultra for
richer extraction, but the structured fields below cover the common shapes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

_GPU_RE = re.compile(r"\b(H100|A100|L40S|H200|GB200)s?\b", re.I)
_COUNT_RE = re.compile(
    r"(\d+)\s*(?:x\s*)?(?:H100|A100|L40S|H200|GB200|gpus?|nodes?|workers?|"
    r"instances?|shards?|replicas?)\b", re.I)
_ACROSS_RE = re.compile(r"\bacross\s+(\d+)\b", re.I)
_PATH_RE = re.compile(r"(?:\bin\s+|\bat\s+|\bfrom\s+|`)(\.?/?[\w./-]+/[\w./*-]+)")
_ARTIFACT_RE = re.compile(r"\b([\w./-]+\.(?:xml|md|json|txt|html|log))\b", re.I)

_SELF_HEAL = ("self-heal", "self heal", "auto-repair", "auto repair", "auto-migrate",
              "migrate", "throttl", "reallocat", "move them", "s'auto", "auto-migre")
_NO_HEAL = ("no self-heal", "no self heal", "don't migrate", "do not migrate",
            "no migration", "disable self-heal", "without migration",
            "stay on the same node", "ne pas migrer", "sans migration")
_NO_FIX = ("no fix", "don't fix", "do not fix", "skip fix", "report only",
           "just report", "no patch", "ne corrige pas", "sans correctif")


@dataclass
class Mission:
    task: str
    shards: int = 3
    gpu_type: str = "H100"
    target: str = "packages/nodus/tests"
    collect: List[str] = field(default_factory=list)
    self_heal: bool = True
    auto_fix: bool = True
    derived: List[str] = field(default_factory=list)

    def scenario(self) -> dict:
        """The dict NgeOrchestrator.run() consumes. Every parsed field is
        carried through - an intent that does not reach the orchestrator is an
        intent the engineer expressed for nothing."""
        return {"name": "mission", "task": self.task, "shards": self.shards,
                "gpu_type": self.gpu_type, "target": self.target,
                "collect": self.collect, "self_heal": self.self_heal,
                "auto_fix": self.auto_fix}


def parse_mission(text: str) -> Mission:
    t = (text or "").strip()
    if not t:
        raise ValueError("empty mission")
    low = t.lower()
    m = Mission(task=t)
    why: List[str] = []

    gm = _GPU_RE.search(t)
    if gm:
        m.gpu_type = gm.group(1).upper()
        why.append(f"gpu={m.gpu_type} (named)")

    cm = _COUNT_RE.search(t) or _ACROSS_RE.search(t)
    if cm:
        n = int(cm.group(1))
        if 1 <= n <= 64:
            m.shards = n
            why.append(f"{n} shards (from {cm.group(0).strip()!r})")

    pm = _PATH_RE.search(t)
    if pm:
        m.target = pm.group(1).strip("`")
        why.append(f"target={m.target}")

    arts = _ARTIFACT_RE.findall(t)
    if arts:
        m.collect = sorted(set(arts))
        why.append(f"collect={m.collect}")

    # negation wins: "migrate" appears inside "do not migrate"
    if any(k in low for k in _NO_HEAL):
        m.self_heal = False
        why.append("self-heal=off (explicit)")
    elif any(k in low for k in _SELF_HEAL):
        m.self_heal = True
        why.append("self-heal=on (explicit)")
    if any(k in low for k in _NO_FIX):
        m.auto_fix = False
        why.append("auto-fix=off (report-only)")

    m.derived = why or ["defaults (nothing structured extracted)"]
    return m


# -- LLM-backed extraction ---------------------------------------------------
#
# The regex parser above enumerates formulations, so it only understands the
# shapes someone thought to list. Measured against 19 unseen engineer phrasings
# it got 4 right. Natural language extraction is what the model routed on
# `plan` is for; the regex stays as the deterministic fallback (CI, --mock,
# offline, or whenever the model returns something that fails validation).

_GPU_TYPES = ("H100", "A100", "L40S", "H200", "GB200")
_MAX_SHARDS = 64
# a target path / artifact name that is safe to interpolate into a shell
# command. The model is untrusted input, exactly like sandbox stdout.
_SAFE_PATH = re.compile(r"^[\w./*-]{1,200}$")

_EXTRACT_PROMPT = """Extract the run parameters from this engineer's request.

Request: {text}

Reply with ONLY a JSON object, no prose. Fields (omit any that the request
does not specify - do not guess):
  "shards":    integer 1-64, how many parallel workers/nodes/GPUs
  "gpu_type":  one of {gpus}
  "target":    the path to test, as written
  "collect":   array of artifact filenames to retrieve
  "self_heal": false ONLY if they ask NOT to migrate/reallocate on pressure
  "auto_fix":  false ONLY if they ask NOT to patch/fix (report-only)

Numbers may be spelled out ("eight" -> 8). Omit a field rather than guessing."""


def _valid_shards(v):
    if isinstance(v, bool) or not isinstance(v, int):
        return None
    return v if 1 <= v <= _MAX_SHARDS else None


def _valid_gpu(v):
    if not isinstance(v, str):
        return None
    up = v.strip().upper()
    return up if up in _GPU_TYPES else None


def _valid_path(v):
    if not isinstance(v, str):
        return None
    # Check the raw string for substitution *before* stripping quotes -
    # stripping first would turn `id` into the perfectly innocent-looking id.
    if any(c in v for c in "`$"):
        return None
    s = v.strip().strip("'\"")
    return s if s and _SAFE_PATH.match(s) else None


def _valid_collect(v):
    if not isinstance(v, list):
        return None
    out = [p for p in (_valid_path(x) for x in v) if p]
    return sorted(set(out)) or None


def _valid_bool(v):
    return v if isinstance(v, bool) else None


# field -> (validator, human name for the audit trail)
_VALIDATORS = {
    "shards": _valid_shards,
    "gpu_type": _valid_gpu,
    "target": _valid_path,
    "collect": _valid_collect,
    "self_heal": _valid_bool,
    "auto_fix": _valid_bool,
}


def parse_mission_llm(text: str, chat_fn, model: str) -> Mission:
    """Parse a mission with the model, falling back field by field.

    Starts from the regex result, then overlays every model-proposed field
    that passes validation. A field the model gets wrong (bad type, out of
    range, shell metacharacter in a path) is dropped and the regex value
    stands - so this can only do better than ``parse_mission`` alone, never
    worse. A model that errors or returns junk degrades to pure regex.
    """
    base = parse_mission(text)
    if chat_fn is None:
        return base

    prompt = _EXTRACT_PROMPT.format(text=text.strip(),
                                    gpus=", ".join(_GPU_TYPES))
    try:
        from nge.backends.nebius import SLOT_MAX_TOKENS
        try:
            msg = chat_fn([{"role": "user", "content": prompt}], model, None,
                          max_tokens=SLOT_MAX_TOKENS)
        except TypeError:
            msg = chat_fn([{"role": "user", "content": prompt}], model, None)
    except Exception as exc:
        base.derived.append(f"llm extraction failed ({type(exc).__name__}), regex only")
        return base

    from nge import llm_text
    obj = llm_text.json_object(msg)
    if not obj:
        base.derived.append("llm returned no JSON, regex only")
        return base

    applied, rejected = [], []
    for field_name, validate in _VALIDATORS.items():
        if field_name not in obj:
            continue
        ok = validate(obj[field_name])
        if ok is None:
            rejected.append(f"{field_name}={obj[field_name]!r}")
            continue
        if getattr(base, field_name) != ok:
            setattr(base, field_name, ok)
            applied.append(f"{field_name}={ok!r}")

    if applied:
        base.derived.append("llm: " + ", ".join(applied))
    if rejected:
        base.derived.append("llm rejected (kept regex): " + ", ".join(rejected))
    return base
