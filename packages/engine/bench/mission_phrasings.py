# -*- coding: utf-8 -*-
"""Measure mission parsing against phrasings it was never written for.

The regex parser in nge/mission.py enumerates formulations, so its unit tests
inevitably use the phrasings whoever wrote the regexes had in mind. That makes
a green suite say almost nothing about a sentence a real engineer types. This
corpus exists to break that loop: every case here was written *against* the
parser, not with it.

Measured 2026-09-03:  regex 5/19  |  regex + nemotron-3-super-120b  18/19

    python -m bench.mission_phrasings              # regex only, no network
    python -m bench.mission_phrasings --llm --i-know-cost

Adding a case is the point. Do NOT tune the regexes until a case passes -
that is the overfitting this file is here to detect. Either the model handles
it, or it is genuinely ambiguous and belongs in the KNOWN_AMBIGUOUS list.
"""
from __future__ import annotations

import sys

from nge.mission import parse_mission, parse_mission_llm

# (phrasing, expected subset of fields)
CASES = [
    # telegraphic / ticket-speak
    ("smoke tests, 8 gpus, ramasse le junit",           dict(shards=8)),
    ("deploy nightly regression suite on eight H100",   dict(shards=8, gpu="H100")),
    ("besoin de 6 noeuds pour le batch de ce soir",     dict(shards=6)),
    # count after the GPU, or behind a noun
    ("H100 x 5 pour la suite d'integration",            dict(shards=5, gpu="H100")),
    ("provision A100s, quantity 4",                     dict(shards=4, gpu="A100")),
    # spelled-out numbers
    ("run across three nodes",                          dict(shards=3)),
    ("lance sur quatre GPU",                            dict(shards=4)),
    # paths without a leading preposition the regex knows, or without a slash
    ("run the tests under src/api",                     dict(target="src/api")),
    ("execute Tests/Integration on 2 nodes",            dict(shards=2, target="Tests/Integration")),
    # negation phrased as intent rather than as "no X"
    ("keep everything on its original node",            dict(heal=False)),
    ("pas de reallocation svp",                         dict(heal=False)),
    ("disable migrations",                              dict(heal=False)),
    ("surtout ne patche rien",                          dict(fix=False)),
    ("read-only run, no modifications",                 dict(fix=False)),
    # self-heal phrased as a consequence, never naming the feature
    ("if a card overheats, move the work elsewhere",    dict(heal=True)),
    ("bascule sur un autre noeud si ca chauffe",        dict(heal=True)),
    # artifacts
    ("save the coverage.xml and the junit.xml",         dict(collect=["coverage.xml", "junit.xml"])),
    ("recupere bench_results.csv",                      dict(collect=["bench_results.csv"])),
]

# Cases where the sentence itself is genuinely ambiguous. Kept in CASES so the
# score stays honest, listed here so a reader knows the ceiling is not 100%.
KNOWN_AMBIGUOUS = {
    "pytest tests_e2e folder": "no preposition and no slash - 'tests_e2e' "
                               "could be a marker, a module or a directory",
}
CASES.append(("pytest tests_e2e folder", dict(target="tests_e2e")))


def _fields(m):
    return dict(shards=m.shards, gpu=m.gpu_type, target=m.target,
                heal=m.self_heal, fix=m.auto_fix, collect=m.collect)


def run(parser, label: str) -> int:
    hits = 0
    for text, expect in CASES:
        got = _fields(parser(text))
        miss = {k: (v, got[k]) for k, v in expect.items() if got[k] != v}
        hits += not miss
        mark = "ok  " if not miss else "FAIL"
        note = "" if not miss else " | " + ", ".join(
            f"{k}: want {v[0]!r}, got {v[1]!r}" for k, v in miss.items())
        if miss and text in KNOWN_AMBIGUOUS:
            note += f"  [known ambiguous: {KNOWN_AMBIGUOUS[text]}]"
        print(f"{mark} {text[:46]:<48}{note}")
    print(f"\n{label}: {hits}/{len(CASES)}")
    return hits


def main(argv) -> int:
    if "--llm" in argv:
        if "--i-know-cost" not in argv:
            print("refusing: --llm calls Nemotron. Re-run with --i-know-cost.",
                  file=sys.stderr)
            return 2
        from nge import config as _cfg
        from nge.backends import usage as _usage
        from nge.backends.nebius import SLOT_MAX_TOKENS, chat_nebius, resolve_max_tokens
        cfg = _cfg.load()
        model = cfg.nemotron_model
        _usage.reset_usage()
        _usage.set_jsonl_path(cfg.out_dir / "nemotron_usage.jsonl")
        print(f"# regex + {model}  max_tokens={resolve_max_tokens(SLOT_MAX_TOKENS)}\n")

        def _chat(messages, mdl, tools=None, max_tokens=None):
            return chat_nebius(messages, mdl, tools,
                               max_tokens=max_tokens or SLOT_MAX_TOKENS)

        hits = run(lambda t: parse_mission_llm(t, _chat, model), "regex + llm")
        print()
        print(_usage.format_summary())
        return 0 if hits else 1
    else:
        print("# regex only (no network)\n")
        run(parse_mission, "regex")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
