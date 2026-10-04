"""Nebius AI Cloud Compute GPU fleet (real VMs with nvidia-smi).

Distinct from :class:`nge.fleet.nebius.NebiusFleet`, which uses Token Factory
**Contree microVMs** (CPU only today). This module targets Compute instances
(``gpu-h100-sxm`` / ``gpu-h200-sxm`` …) via the Nebius Python SDK (``nebius``).

Phase 0 (credentials), Phase 1 (read-only inventory), Phase 2 (one probe) and
the Phase 3 fleet (``compute_fleet.ComputeGpuFleet``) live here and next door.
Every paid action needs an explicit operator **Go** (cost).
See ``docs/ENGINE_BACKLOG.md`` M1/M2 and ``docs/COMPUTE_GPU.md``.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

from nge.fleet import telemetry


from nge.fleet.compute_fleet import ComputeGpuFleet  # noqa: E402,F401  (re-export)


def expected_probe_kind() -> str:
    """Compute VMs with CUDA images should expose nvidia-smi."""
    return telemetry.PROBE_NVIDIA


# Token Factory projects (the id Contree sandboxes and Nemotron use) look like
# ``aiproject-...``; they are not AI Cloud projects and cannot own a VM. Compute
# therefore reads its own project id, never NEBIUS_PROJECT_ID - which the live
# path already uses for Token Factory and must keep.
_TOKEN_FACTORY_PROJECT_PREFIX = "aiproject-"
_CREDENTIALS_DEFAULT = ".nebius_sa_credentials.json"


def _engine_dir() -> Path:
    from nge import config as _cfg
    return _cfg._ENGINE_DIR


def _credentials_file_check(path: Path) -> Optional[str]:
    """Validate a service-account credentials file offline, the way the SDK
    will read it (``subject-credentials``: RS256, iss == sub, a parseable PEM
    key). Returns None when usable, else why not. No network."""
    import json
    try:
        from nebius.base.service_account.credentials_file import (
            ServiceAccountCredentials)
        data = json.loads(path.read_text(encoding="utf-8"))
        creds = ServiceAccountCredentials.from_json(data)
        creds.subject_credentials.parse_private_key()
    except ImportError:
        return "nebius SDK not installed, cannot validate"
    except KeyError as exc:
        return f"missing field {exc} (expected subject-credentials: alg, private-key, kid, iss, sub)"
    except Exception as exc:                     # never echo the key itself
        return f"{type(exc).__name__}: {str(exc)[:160]}"
    return None


def check_credentials() -> dict:
    """Phase 0 preflight: can the Compute SDK authenticate, and against which
    project? Read-only - no API call, no VM, nothing created.

    Auth, in the SDK's own order of preference: a service-account credentials
    file (``NEBIUS_SA_CREDENTIALS_FILE`` or ``packages/engine/.nebius_sa_credentials.json``),
    the ``nebius`` CLI profile (``~/.nebius/config.yaml``), then
    ``NEBIUS_IAM_TOKEN`` - the only environment variable the SDK reads.
    Project: ``NEBIUS_COMPUTE_PROJECT_ID`` or ``.nebius_compute_project_id``.
    Subnet (needed from Phase 2): ``NEBIUS_SUBNET_ID`` or ``.nebius_compute_subnet_id``.
    """
    from nge import config as _cfg

    try:
        import importlib.metadata as _md
        sdk_version = _md.version("nebius")
        import nebius  # noqa: F401
        sdk = True
    except Exception:
        sdk, sdk_version = False, None

    iam = bool(os.environ.get("NEBIUS_IAM_TOKEN", "").strip())
    raw = os.environ.get("NEBIUS_SA_CREDENTIALS_FILE", "").strip()
    cred_path = Path(raw).expanduser() if raw else _engine_dir() / _CREDENTIALS_DEFAULT
    cred_error = None
    if cred_path.is_file():
        cred_error = _credentials_file_check(cred_path)
    elif raw:
        cred_error = "file not found"
    cred_ok = cred_path.is_file() and cred_error is None
    cli_profile = (Path("~/.nebius/config.yaml").expanduser()).is_file()

    project = _cfg.load_value("nebius_compute_project_id", "NEBIUS_COMPUTE_PROJECT_ID")
    project_error = None
    if project.startswith(_TOKEN_FACTORY_PROJECT_PREFIX):
        project_error = ("a Token Factory project id (aiproject-...), not an AI "
                         "Cloud project - Compute VMs need the AI Cloud one")
    elif project and not project.startswith("project-"):
        # Nebius ids name their resource type first. The first id offered for
        # this field was a tenantuseraccount-... (the signed-in user), which
        # the aiproject- check alone would have accepted.
        kind = project.split("-", 1)[0] if "-" in project else "unknown"
        project_error = (f"a {kind} id, not a project - an AI Cloud project id "
                         "starts with project-")
    subnet = _cfg.load_value("nebius_compute_subnet_id", "NEBIUS_SUBNET_ID")

    auth = ("credentials_file" if cred_ok else "cli_profile" if cli_profile
            else "iam_token" if iam else None)
    project_ok = bool(project) and project_error is None

    missing: List[str] = []
    if not sdk:
        missing.append("pip install nebius")
    if auth is None:
        missing.append("auth: a service-account credentials file "
                       f"(packages/engine/{_CREDENTIALS_DEFAULT} or NEBIUS_SA_CREDENTIALS_FILE)"
                       + (f" - current one: {cred_error}" if cred_error else "")
                       + ", or a `nebius` CLI profile, or NEBIUS_IAM_TOKEN")
    if not project_ok:
        missing.append("AI Cloud project id in NEBIUS_COMPUTE_PROJECT_ID or "
                       "packages/engine/.nebius_compute_project_id"
                       + (f" - current one is {project_error}" if project_error else ""))
    if not subnet:
        missing.append("(Phase 2) subnet id in NEBIUS_SUBNET_ID or "
                       "packages/engine/.nebius_compute_subnet_id")

    return {
        "sdk_installed": sdk,
        "sdk_version": sdk_version,
        "auth": auth,
        "iam_token": iam,
        "credentials_file": str(cred_path) if (raw or cred_path.is_file()) else None,
        "credentials_file_ok": cred_ok,
        "credentials_file_error": cred_error,
        "cli_profile": cli_profile,
        "project_id": project_ok,
        "project_id_error": project_error,
        "subnet_id": bool(subnet),
        "ready_for_wire": sdk and auth is not None and project_ok,
        "spawn_allowed": False,  # always False until explicit Go + code path
        "missing": missing,
    }


def format_checklist(report: dict) -> str:
    mark = lambda ok: "OK " if ok else "-- "              # noqa: E731
    lines = [
        "Compute Phase 0 - credentials preflight (no API call, no VM)",
        f"  {mark(report['sdk_installed'])} nebius SDK {report['sdk_version'] or ''}".rstrip(),
        f"  {mark(report['auth'] is not None)} auth: {report['auth'] or 'none'}",
        f"  {mark(report['project_id'])} AI Cloud project id",
        f"  {mark(report['subnet_id'])} subnet id (needed from Phase 2)",
        f"  ready_for_wire={report['ready_for_wire']}  spawn_allowed={report['spawn_allowed']}",
    ]
    if report["missing"]:
        lines.append("missing:")
        lines += [f"  - {m}" for m in report["missing"]]
    return "\n".join(lines)


_PRIVATE_KEY_DEFAULT = ".nebius_sa_private_key.pem"
_PUBLIC_KEY_DEFAULT = ".nebius_sa_public_key.pem"


def key_files(name: str = "") -> Dict[str, str]:
    """File names of one service account's key set. ``name`` separates the
    read-only account (default) from e.g. the Phase 2 one (``phase2``), so
    adding a write-capable account never touches the read-only key."""
    if name and not name.isalnum():
        raise ValueError(f"key set name must be alphanumeric: {name!r}")
    tag = f"_{name}" if name else ""
    return {"private": f".nebius_sa{tag}_private_key.pem",
            "public": f".nebius_sa{tag}_public_key.pem",
            "credentials": f".nebius_sa{tag}_credentials.json"}


def generate_keypair(engine_dir: Optional[Path] = None, name: str = "") -> Path:
    """Create the RSA pair for a service-account *authorized key*.

    The console only takes an uploaded public key. The private key is written
    next to it under ``packages/engine/`` (``.nebius_*`` is gitignored) and is
    never printed. Refuses to overwrite: a second run would silently orphan
    the key already uploaded. Returns the public key path, to upload.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    d = engine_dir or _engine_dir()
    files = key_files(name)
    priv, pub = d / files["private"], d / files["public"]
    if priv.exists():
        raise FileExistsError(f"{priv.name} already exists - delete it first "
                              "if you really mean to replace the key")
    key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    priv.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                       serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    pub.write_bytes(key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo))
    return pub


def write_credentials(service_account_id: str, public_key_id: str,
                      engine_dir: Optional[Path] = None, name: str = "") -> Path:
    """Assemble the credentials file the SDK reads, from the local private key
    and the two ids the console shows. Validated before it is kept."""
    import json

    if not service_account_id.startswith("serviceaccount-"):
        raise ValueError(f"not a service account id: {service_account_id!r}")
    if not public_key_id.startswith("publickey-"):
        raise ValueError(f"not an authorized key id: {public_key_id!r} "
                         "(the console shows publickey-... after the upload)")
    d = engine_dir or _engine_dir()
    files = key_files(name)
    priv = d / files["private"]
    if not priv.is_file():
        raise FileNotFoundError(f"{priv.name} missing - run keygen first")
    out = d / files["credentials"]
    out.write_text(json.dumps({"subject-credentials": {
        "type": "JWT", "alg": "RS256",
        "private-key": priv.read_text(encoding="utf-8"),
        "kid": public_key_id, "iss": service_account_id,
        "sub": service_account_id}}, indent=2), encoding="utf-8")
    why = _credentials_file_check(out)
    if why:
        out.unlink()
        raise ValueError(f"assembled file rejected: {why}")
    return out


def _main(argv: List[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m nge.fleet.compute",
                                 description="Compute Phase 0: no API call, no VM.")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("check", help="credentials checklist (default)")
    kg = sub.add_parser("keygen", help="RSA pair for an authorized key; prints the public key")
    kg.add_argument("--name", default="", help="key set, e.g. phase2 (default: read-only)")
    cr = sub.add_parser("credentials", help="build the SDK credentials file")
    cr.add_argument("--service-account-id", required=True)
    cr.add_argument("--public-key-id", required=True)
    cr.add_argument("--name", default="", help="key set, e.g. phase2 (default: read-only)")
    sub.add_parser("inventory", help="Phase 1: read-only GPU platforms / subnets / "
                                     "CUDA images in every region (nothing created)")
    pr = sub.add_parser("probe", help="Phase 2: ONE paid GPU VM, nvidia-smi over SSH, "
                                      "deleted in a finally")
    pr.add_argument("--i-know-cost", action="store_true")
    pr.add_argument("--max-minutes", type=float, default=30)
    cl = sub.add_parser("cleanup", help="delete every VM this tool labelled")
    cl.add_argument("--project-id", default=None)
    hy = sub.add_parser("hybrid", help="Phase 3: the orchestrator on real GPU VMs "
                                       "(telemetry) + Token Factory sandboxes (shards)")
    hy.add_argument("--i-know-cost", action="store_true")
    hy.add_argument("--shards", type=int, default=2)
    hy.add_argument("--max-minutes", type=float, default=12)
    args = ap.parse_args(argv)

    if args.cmd in ("probe", "cleanup"):
        return _phase2(args)
    if args.cmd == "hybrid":
        return _phase3(args)

    if args.cmd == "inventory":
        r = check_credentials()
        if not r["ready_for_wire"]:
            print(format_checklist(r))
            return 1
        from nge import config as _cfg
        from nge.fleet import compute_inventory as ci
        project = _cfg.load_value("nebius_compute_project_id", "NEBIUS_COMPUTE_PROJECT_ID")
        sdk = ci.build_sdk(_engine_dir())
        try:
            inv = ci.inventory(ci.NebiusReadApi(sdk), project)
        finally:
            try:
                sdk.sync_close()
            except Exception:
                pass
        rec = ci.recommend(inv)
        print(ci.format_inventory(inv, rec))
        print(f"saved: {ci.save(inv, rec, _cfg.load().out_dir)}")
        return 0

    if args.cmd == "keygen":
        pub = generate_keypair(name=args.name)
        print(f"private key kept in packages/engine/{key_files(args.name)['private']} "
              "(gitignored, never printed)")
        print(f"upload this public key (also in packages/engine/{pub.name}):\n")
        print(pub.read_text(encoding="utf-8"))
        return 0
    if args.cmd == "credentials":
        out = write_credentials(args.service_account_id, args.public_key_id,
                                name=args.name)
        print(f"wrote packages/engine/{out.name} - valid for the SDK")
    r = check_credentials()
    print(format_checklist(r))
    return 0 if r["ready_for_wire"] else 1


def _phase2(args) -> int:
    """probe / cleanup: the write-capable ``phase2`` service account, never the
    read-only one, and for probe two explicit opt-ins before anything is paid."""
    from nge import config as _cfg
    from nge.fleet import compute_inventory as ci
    from nge.fleet import compute_probe as cp

    creds = _engine_dir() / key_files("phase2")["credentials"]
    why = _credentials_file_check(creds) if creds.is_file() else "file not found"
    if why:
        print(f"Phase 2 needs the write-capable service account: {creds.name} - {why}.\n"
              "  python -m nge.fleet.compute keygen --name phase2\n"
              "  (upload the public key to that account, then)\n"
              "  python -m nge.fleet.compute credentials --name phase2 "
              "--service-account-id serviceaccount-... --public-key-id publickey-...")
        return 1
    if args.cmd == "probe":
        if not args.i_know_cost or os.environ.get("NGE_COMPUTE_SPAWN") != "1":
            print("refusing: a probe creates a paid GPU VM. Re-run with --i-know-cost "
                  "and NGE_COMPUTE_SPAWN=1.")
            return 2
        if not 0 < args.max_minutes <= cp.MAX_MINUTES:
            print(f"refusing: --max-minutes must be in (0, {cp.MAX_MINUTES}]")
            return 2

    out_dir = _cfg.load().out_dir
    sdk = ci.build_sdk(_engine_dir(), key_files("phase2")["credentials"])
    try:
        project = _cfg.load_value("nebius_compute_project_id", "NEBIUS_COMPUTE_PROJECT_ID")
        inv = ci.inventory(ci.NebiusReadApi(sdk), project)
        target = ci.recommend(inv)
        api = cp.ComputeApi(sdk)
        if args.cmd == "cleanup":
            pid = args.project_id or (target or {}).get("project_id")
            if not pid:
                print("no project to clean: pass --project-id")
                return 1
            cp.cleanup(api, pid)
            return 0
        if not target:
            print("no bootable target in the inventory - nothing created")
            return 1
        cost = cp.estimate_usd(target, args.max_minutes)
        print(f"[probe] target {target['platform']} / {target['preset']} in "
              f"{target['region']}, image {target['image_family']}, "
              f"max {args.max_minutes:g} min, compute "
              + (f"~${cost} before tax (+ disk and public IP)" if cost is not None
                 else "cost unknown (no list price)"))
        key, pub = cp.ensure_ssh_key(_engine_dir())
        report = cp.probe(api, target, key, pub, max_minutes=args.max_minutes)
        print(f"[probe] saved {cp.save(report, out_dir)}")
        if report["instance_id"] and not report["deleted"]:
            print("[probe] WARNING: deletion NOT confirmed - run "
                  "`python -m nge.fleet.compute cleanup` and check the console")
            return 3
        m = report["metrics"] or {}
        print(f"[probe] ok={report['ok']} probe_kind={m.get('probe_kind')} "
              f"gpu={m.get('gpu_name')!r} temp={m.get('temp_c')}C "
              f"power={m.get('power_w')}W wall={report['wall_s']}s")
        return 0 if report["ok"] else 1
    finally:
        try:
            sdk.sync_close()
        except Exception:
            pass


HYBRID_MAX_SHARDS = 3            # each shard is one paid GPU VM


def _phase3(args) -> int:
    """One orchestrator run with fleet_mode=compute (real GPU VMs, telemetry
    only) and sandbox_mode=token_factory (the shards). Autofix is off: every fix
    attempt reserves a fleet node, which here would be one more paid VM for a
    verification that runs in a sandbox anyway. The claim under test is the
    heal loop on real telemetry, not the fixes."""
    from nge import config as _cfg
    from nge.fleet import compute_probe as cp

    creds = _engine_dir() / key_files("phase2")["credentials"]
    why = _credentials_file_check(creds) if creds.is_file() else "file not found"
    if why:
        print(f"Phase 3 needs the write-capable service account: {creds.name} - {why}")
        return 1
    if not args.i_know_cost or os.environ.get("NGE_COMPUTE_SPAWN") != "1":
        print("refusing: a hybrid run creates one paid GPU VM per shard. Re-run with "
              "--i-know-cost and NGE_COMPUTE_SPAWN=1.")
        return 2
    if not 0 < args.max_minutes <= cp.MAX_MINUTES or not 1 <= args.shards <= HYBRID_MAX_SHARDS:
        print(f"refusing: --max-minutes in (0, {cp.MAX_MINUTES}], --shards in "
              f"[1, {HYBRID_MAX_SHARDS}]")
        return 2

    os.environ["NGE_COMPUTE_MAX_MINUTES"] = str(args.max_minutes)
    os.environ.setdefault("NGE_TRACK", "nebius")
    from nge.backends import usage as _usage
    from nge.demo_nebius import _DEFAULT_SCENARIO, _live_chat_fn, _load_scenario
    from nge.orchestrator import NgeOrchestrator
    from nge.tools import handlers

    cfg = _cfg.load(fleet_mode="compute", sandbox_mode="token_factory")
    _usage.reset_usage()
    _usage.set_jsonl_path(cfg.out_dir / "nemotron_usage.jsonl")
    scenario = {**_load_scenario(_DEFAULT_SCENARIO), "shards": args.shards,
                "auto_fix": False, "gpu_workload": False}
    cost = cp.estimate_usd({"platform": "gpu-l40s-a"}, args.max_minutes)
    print(f"[hybrid] {args.shards} GPU VM(s), max {args.max_minutes:g} min each - compute "
          + (f"~${round(cost * args.shards, 2)} before tax (+ disks, public IPs, "
             "Nemotron and sandbox calls)" if cost is not None else "cost unknown"))
    orch = NgeOrchestrator(config=cfg, chat_fn=_live_chat_fn(cfg.nemotron_model))
    report, err = None, None
    try:
        report = orch.run(scenario)
    except BaseException as exc:                # the fleet was released by run()
        err = exc
    fleet = handlers.state().fleet
    undeleted = list(getattr(fleet, "undeleted", []))
    tele = [e["telemetry"] for e in orch.events
            if e["kind"] == "gpu_status" and e.get("telemetry")]
    kinds = [e["kind"] for e in orch.events]
    for t in tele:
        print(f"[hybrid] telemetry {t['id']}: {t['probe_kind']} {t.get('gpu_name')!r} "
              f"{t['temp_c']}C {t['power_w']}W util={t['util_pct']}% health={t['health']} "
              f"efficiency={t['efficiency']}")
    print(f"[hybrid] efficiency skipped={kinds.count('gpu_efficiency_skipped')} "
          f"pressure={kinds.count('gpu_pressure')} remediations={kinds.count('gpu_remediation')}")
    if report is not None:
        print(f"[hybrid] report {report.artifact_path}")
    print(_usage.format_summary())
    if undeleted:
        print(f"[hybrid] WARNING: deletion NOT confirmed for {undeleted} - run "
              "`python -m nge.fleet.compute cleanup` and check the console")
        return 3
    if err is not None:
        print(f"[hybrid] run failed: {type(err).__name__}: {err}")
        if not isinstance(err, Exception):
            raise err
        return 1
    return 0


if __name__ == "__main__":                       # pragma: no cover
    import sys
    raise SystemExit(_main(sys.argv[1:]))
