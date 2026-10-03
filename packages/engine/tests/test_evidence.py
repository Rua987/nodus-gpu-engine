"""The runs the docs cite exist in git, and still say what the docs say.

Until 2026-10-01 every cited report lived in gitignored ``out/``: the Devpost
text and the judge script pointed at files no clone had.
"""
import csv
import json
import re
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parents[1]
REPO = ENGINE.parents[1]
EVIDENCE = ENGINE / "evidence"
DOCS = [REPO / "README.md", *sorted((REPO / "docs").glob("*.md")),
        *sorted((ENGINE / "docs").glob("*.md")), ENGINE / "README.md"]

_STAMP = re.compile(r"\b(?:report_)?(20\d{6}T\d{6}Z)(_honest)?")
_SHORT_STAMP = re.compile(r"(?<![\w/])(\d{6}Z)(?:_honest)?\b")
_CSV = re.compile(r"\b((?:taxonomy|thinking_ab)_[\w]+\.csv)")


def _events(stem):
    t = (EVIDENCE / f"{stem}.md").read_text(encoding="utf-8")
    return json.loads(t[t.index("```json") + 7:t.rindex("```")])


def _kinds(events, kind):
    return [e for e in events if e.get("kind") == kind]


def test_every_cited_report_is_versioned():
    cited, missing = set(), []
    for doc in DOCS:
        text = doc.read_text(encoding="utf-8")
        for stamp, honest in _STAMP.findall(text):
            cited.add(f"report_{stamp}{honest}")
    assert cited, "the docs cite runs; the pattern found none"
    for stem in sorted(cited):
        if stem.endswith("_honest"):
            if not (EVIDENCE / f"{stem}.html").is_file():
                missing.append(f"{stem}.html")
            continue
        for ext in (".md", ".html"):
            if not (EVIDENCE / f"{stem}{ext}").is_file():
                missing.append(stem + ext)
    assert not missing, f"cited in docs, absent from evidence/: {missing}"


def test_short_timestamps_in_docs_resolve_to_one_report():
    """The backlog and the judge script cite runs as `041721Z`."""
    have = {p.stem.split("T")[-1].replace("_honest", "") for p in EVIDENCE.glob("report_*")}
    for doc in DOCS:
        for short in _SHORT_STAMP.findall(doc.read_text(encoding="utf-8")):
            assert short in have, f"{doc.name} cites {short}, no such report in evidence/"


def test_every_cited_dated_csv_is_versioned():
    """Undated names are output paths in command examples; dated ones are evidence."""
    for doc in DOCS:
        for name in _CSV.findall(doc.read_text(encoding="utf-8")):
            if re.search(r"_20\d{6}", name):
                assert (EVIDENCE / name).is_file(), f"{doc.name}: {name}"


@pytest.mark.parametrize("name", ["thinking_ab_20261001.csv", "thinking_ab_20261001_r2.csv",
                                  "thinking_ab_bugbench_20261001.csv"])
def test_bench_rows_point_at_kept_run_logs(name):
    rows = list(csv.DictReader((EVIDENCE / name).open(encoding="utf-8")))
    assert rows
    for r in rows:
        assert not Path(r["out"]).is_absolute() and ":" not in r["out"]
        assert (EVIDENCE / r["out"]).is_file(), f"no event log for {r['out']}"


def test_evidence_paths_stay_short():
    """Windows refuses to check out a path over 260 characters; a first layout
    reached 132 inside the repo and broke a clone made into a deep folder."""
    longest = max(len(str(p.relative_to(REPO)).replace("\\", "/"))
                  for p in EVIDENCE.rglob("*") if p.is_file())
    assert longest <= 70, longest


def test_no_local_paths_or_secrets_in_evidence():
    secret = re.compile(r"sk-[A-Za-z0-9]{12}|[Bb]earer [A-Za-z0-9]{12}|"
                        r"glsa_[A-Za-z0-9]{12}")
    # patches quote repo code, whose docstrings carry example Windows paths;
    # only what the engine itself wrote (reports, CSVs) must not leak one
    local = re.compile(r"[A-Za-z]:\\\\?Users|/home/\w|/Users/\w")
    hits = []
    for p in EVIDENCE.rglob("*"):
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if secret.search(text) or (p.suffix != ".patch" and local.search(text)):
            hits.append(p.relative_to(EVIDENCE))
    assert not hits, hits


# -- the judge-facing claims, checked against the run-time event log ----------

def test_a2_film_is_two_of_three_with_a_migration():
    ev = _events("report_20260913T041721Z")
    assert _kinds(ev, "plan")[0]["source"] == "heuristic"
    assert [(e["from"], e["to"]) for e in _kinds(ev, "gpu_remediation")] == \
        [("nb-h100-02", "nb-h100-03")]
    assert len(_kinds(ev, "fix_verified")) == 2
    assert _kinds(ev, "triage")[0]["unique_failures"] == 3


def test_live_honest_is_cpu_fallback_and_three_cut_patches():
    ev = _events("report_20260913T053458Z")
    assert _kinds(ev, "run_start")[0]["sandbox_mode"] == "token_factory"
    probes = {(e.get("telemetry") or {}).get("probe_kind") for e in _kinds(ev, "gpu_status")}
    assert "cpu-fallback" in probes
    cut = _kinds(ev, "patch_truncated")
    assert len(cut) == 3 and all(e["reply_chars"] == 0 and e["max_tokens"] == 2048
                                 for e in cut)
    assert not _kinds(ev, "fix_verified") and not _kinds(ev, "gpu_remediation")
    # the re-render must keep saying what the log says
    honest = (EVIDENCE / "report_20260913T053458Z_honest.html").read_text(encoding="utf-8")
    assert "cpu-fallback" in honest and "0-char reply" in honest


def test_live_after_reasoning_fix_produces_and_rejects_honestly():
    ev = _events("report_20261002T055558Z")
    rs = _kinds(ev, "run_start")[0]
    assert (rs["fleet_mode"], rs["sandbox_mode"]) == ("mock", "token_factory")
    assert _kinds(ev, "triage")[0]["unique_failures"] == 5
    assert sum(1 for e in _kinds(ev, "fix_attempt") if e["has_patch"]) == 3
    assert not _kinds(ev, "patch_truncated")
    assert len(_kinds(ev, "fix_rejected")) == 3 and not _kinds(ev, "fix_verified")


def test_the_one_verified_bench_patch_is_kept():
    p = EVIDENCE / "ab" / "verified_fix_ntpath.patch"
    assert "ntpath" in p.read_text(encoding="utf-8")
    ev = _events("ab/r2_short_off_patch_8k_2")
    v = _kinds(ev, "fix_verified")
    assert len(v) == 1 and v[0]["test"].endswith("test_drive_underscore_prefix")
    assert v[0]["regressions"] == 0


def test_bugbench_series_every_verified_fix_is_real():
    """The claim in docs/FIX_LOOP.md: on seeded bugs, every patch the loop
    verified also passed the held-out cases, and none broke anything."""
    rows = list(csv.DictReader((EVIDENCE / "thinking_ab_bugbench_20261001.csv")
                               .open(encoding="utf-8")))
    assert len(rows) == 12
    for r in rows:
        assert r["target"] == "bugbench" and r["sandbox"] == "token_factory"
        assert r["holdout_ok"] == r["verified"], r["out"]
        assert r["regression"] == "0", r["out"]
    by = {}
    for r in rows:
        by.setdefault(r["arm"], 0)
        by[r["arm"]] += int(r["verified"])
    assert by == {"baseline": 12, "short_off": 15, "short_off_patch_off": 16,
                  "short_off_patch_8k": 16}


def test_compute_probe_read_a_real_gpu_and_deleted_its_vm():
    """docs/COMPUTE_GPU.md, Phase 2: the engine's own probe - not a manual ssh -
    brought back nvidia-smi from a Nebius Compute VM and deleted it."""
    import json
    d = json.loads((EVIDENCE / "compute_probe_20261003T231022Z.json").read_text(encoding="utf-8"))
    m = d["metrics"]
    assert d["ok"] is True and d["deleted"] is True and d["error"] is None
    assert m["probe_kind"] == "nvidia-smi" and m["gpu_name"] == "NVIDIA L40S"
    assert m["gpu_class"] == "datacenter"
    assert [e["kind"] for e in d["events"]][-1] == "deleted"
    assert d["target"]["platform"] == "gpu-l40s-a" and d["target"]["region"] == "eu-north1"
    text = json.dumps(d)
    for account_id in ("project-e", "vpcsubnet-e", "computeinstance-e"):
        assert account_id not in text
