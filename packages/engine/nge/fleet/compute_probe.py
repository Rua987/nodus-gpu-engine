"""Compute Phase 2: one GPU VM, ``nvidia-smi`` read over SSH, then deleted.

The VM is paid by the minute, so the shape of this module is about getting it
deleted, not about creating it:

- the instance id is known as soon as the create *request* returns, before the
  operation finishes - a create that times out still leaves an id to delete;
- deletion runs in a ``finally`` (error, timeout, Ctrl+C), with retries, and
  the report says whether it was confirmed;
- every wait is bounded by one wall-clock deadline (``MAX_MINUTES`` at most);
- every VM carries the label ``nge-phase2=probe``, so ``cleanup`` can find and
  delete anything a crashed run left behind.

The probe itself is the same shell snippet the Contree fleet already runs
(``nge.fleet.nebius._PROBE``) and the same parser, so a real GPU reading lands
as ``probe_kind=nvidia-smi`` exactly where the engine expects it.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

LABEL_KEY, LABEL_VALUE = "nge-phase2", "probe"
NAME_PREFIX = "nge-probe-"
MAX_MINUTES = 30
SSH_USER = "nge"                 # Nebius reserves root and admin for itself
BOOT_DISK_GIB = 50               # the CUDA images do not fit the 10 GiB examples
SSH_KEY = ".nebius_vm_ssh_key"   # .nebius_* is gitignored


# -- SSH key for the VM ------------------------------------------------------

def ensure_ssh_key(engine_dir: Path) -> Tuple[Path, str]:
    """An ed25519 key for this probe, created once and kept local. OpenSSH
    refuses a private key others can read, so access is narrowed to the user.
    Returns (private key path, public key line)."""
    priv, pub = engine_dir / SSH_KEY, engine_dir / f"{SSH_KEY}.pub"
    if not priv.exists():
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519
        key = ed25519.Ed25519PrivateKey.generate()
        priv.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                           serialization.PrivateFormat.OpenSSH,
                                           serialization.NoEncryption()))
        pub.write_bytes(key.public_key().public_bytes(serialization.Encoding.OpenSSH,
                                                      serialization.PublicFormat.OpenSSH)
                        + b" nge-probe\n")
        _restrict(priv)
    return priv, pub.read_text(encoding="utf-8").strip()


def _restrict(path: Path) -> None:
    if os.name == "nt":
        user = os.environ.get("USERNAME", "")
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
                       capture_output=True, check=False)
    else:
        os.chmod(path, 0o600)


def cloud_init(public_key: str, user: str = SSH_USER) -> str:
    return ("#cloud-config\n"
            "users:\n"
            f"  - name: {user}\n"
            "    shell: /bin/bash\n"
            "    ssh_authorized_keys:\n"
            f"      - {public_key}\n")


def run_ssh(ip: str, key: Path, script: str, timeout: float,
            user: str = SSH_USER) -> Tuple[int, str, str]:
    """Run ``script`` on the VM. Host key: accepted on first use and kept in a
    throwaway known_hosts - a fresh VM has no key we could have pinned, and
    only nvidia-smi output comes back."""
    with tempfile.TemporaryDirectory(prefix="nge_ssh_") as td:
        cmd = ["ssh", "-i", str(key), "-o", "BatchMode=yes",
               "-o", "StrictHostKeyChecking=accept-new",
               "-o", f"UserKnownHostsFile={Path(td) / 'known_hosts'}",
               "-o", "ConnectTimeout=10", f"{user}@{ip}", "sh -s"]
        try:
            r = subprocess.run(cmd, input=script, capture_output=True, text=True,
                               timeout=timeout)
            return r.returncode, r.stdout, r.stderr
        except subprocess.TimeoutExpired:
            return 124, "", "ssh timed out"


# -- the four calls Phase 2 makes -------------------------------------------

class ComputeApi:
    def __init__(self, sdk) -> None:
        import nebius.api.nebius.common.v1 as common
        import nebius.api.nebius.compute.v1 as compute
        self._c, self._common = compute, common
        self._instances = compute.InstanceServiceClient(sdk)

    def create(self, target: Dict[str, str], name: str, user_data: str,
               timeout: float) -> Tuple[str, Any]:
        """Send the create; return (instance id, operation) at once - the id
        must be known before anything can fail while waiting."""
        c = self._c
        req = c.CreateInstanceRequest(
            metadata=self._common.ResourceMetadata(
                parent_id=target["project_id"], name=name,
                labels={LABEL_KEY: LABEL_VALUE}),
            spec=c.InstanceSpec(
                resources=c.ResourcesSpec(platform=target["platform"],
                                          preset=target["preset"]),
                boot_disk=c.AttachedDiskSpec(
                    attach_mode=c.AttachedDiskSpec.AttachMode.READ_WRITE,
                    managed_disk=c.ManagedDisk(
                        name=f"{name}-boot", labels={LABEL_KEY: LABEL_VALUE},
                        spec=c.DiskSpec(
                            size_gibibytes=BOOT_DISK_GIB,
                            type=c.DiskSpec.DiskType.NETWORK_SSD,
                            source_image_family=c.SourceImageFamily(
                                image_family=target["image_family"])))),
                network_interfaces=[c.NetworkInterfaceSpec(
                    name="eth0", subnet_id=target["subnet_id"],
                    ip_address=c.IPAddress(),
                    public_ip_address=c.PublicIPAddress())],
                cloud_init_user_data=user_data))
        op = self._instances.create(req, timeout=min(timeout, 120)).wait()
        return op.resource_id, op

    @staticmethod
    def wait_op(op, timeout: float) -> None:
        op.sync_wait(timeout=max(1.0, timeout))
        if not op.successful():
            raise RuntimeError(f"operation failed: {op.status}")

    def get(self, instance_id: str, timeout: float = 30) -> Dict[str, Optional[str]]:
        i = self._instances.get(self._c.GetInstanceRequest(id=instance_id),
                                timeout=timeout).wait()
        ip = None
        for nic in i.status.network_interfaces or []:
            addr = getattr(getattr(nic, "public_ip_address", None), "address", "") or ""
            if addr:
                ip = addr.split("/")[0]
                break
        return {"state": getattr(i.status.state, "name", str(i.status.state)), "public_ip": ip}

    def delete(self, instance_id: str, timeout: float) -> None:
        op = self._instances.delete(self._c.DeleteInstanceRequest(id=instance_id),
                                    timeout=min(timeout, 120)).wait()
        self.wait_op(op, timeout)

    def list_labeled(self, project_id: str) -> List[Dict[str, str]]:
        r = self._instances.list(self._c.ListInstancesRequest(parent_id=project_id),
                                 timeout=60).wait()
        return [{"id": i.metadata.id, "name": i.metadata.name,
                 "state": getattr(i.status.state, "name", str(i.status.state))}
                for i in r.items
                if dict(i.metadata.labels or {}).get(LABEL_KEY) == LABEL_VALUE]


# -- the run ------------------------------------------------------------------

def probe(api, target: Dict[str, str], ssh_key: Path, public_key: str,
          max_minutes: float = MAX_MINUTES,
          clock: Callable[[], float] = time.monotonic,
          sleep: Callable[[float], None] = time.sleep,
          ssh: Callable[..., Tuple[int, str, str]] = run_ssh,
          log: Callable[[str], None] = print) -> Dict[str, Any]:
    from nge.fleet.nebius import _PROBE, _parse_probe

    max_minutes = min(float(max_minutes), MAX_MINUTES)
    t0 = clock()
    deadline = t0 + max_minutes * 60
    left = lambda: deadline - clock()                       # noqa: E731
    report: Dict[str, Any] = {"target": target, "max_minutes": max_minutes,
                              "instance_id": None, "metrics": None, "ok": False,
                              "deleted": None, "error": None, "events": []}

    def ev(kind: str, **kw) -> None:
        e = {"t": round(clock() - t0, 1), "kind": kind, **kw}
        report["events"].append(e)
        log(f"[probe +{e['t']:>6}s] {kind} {kw if kw else ''}".rstrip())

    name = f"{NAME_PREFIX}{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}"
    iid = None
    interrupted = None
    try:
        iid, op = api.create(target, name, cloud_init(public_key), left())
        report["instance_id"] = iid
        ev("create_sent", instance_id=iid, name=name)
        api.wait_op(op, left())
        ev("created")
        ip = None
        while True:
            st = api.get(iid)
            if st["state"] == "ERROR":
                raise RuntimeError("instance entered ERROR state")
            if st["state"] == "RUNNING" and st["public_ip"]:
                ip = st["public_ip"]
                break
            if left() <= 0:
                raise TimeoutError(f"not running before the deadline (state {st['state']})")
            sleep(10)
        ev("running", public_ip=ip)
        while True:
            rc, out, err = ssh(ip, ssh_key, _PROBE, timeout=min(60.0, max(5.0, left())))
            if rc == 0 and out.strip():
                break
            if left() <= 0:
                raise TimeoutError(f"no SSH answer before the deadline: {err.strip()[:200]}")
            sleep(15)
        metrics = _parse_probe(out)
        report["metrics"] = metrics
        report["ok"] = bool(metrics and metrics["probe_kind"] == "nvidia-smi")
        ev("probed", probe_kind=(metrics or {}).get("probe_kind"),
           gpu_name=(metrics or {}).get("gpu_name"))
    except BaseException as exc:                 # incl. KeyboardInterrupt: delete first
        report["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        ev("error", error=report["error"])
        if not isinstance(exc, Exception):
            interrupted = exc
    finally:
        if iid:
            report["deleted"] = False
            for attempt in (1, 2, 3):
                try:
                    # deleting gets its own budget: a run that hit the
                    # deadline must still be able to clean up
                    api.delete(iid, timeout=600)
                    report["deleted"] = True
                    ev("deleted", attempt=attempt)
                    break
                except Exception as exc:
                    ev("delete_failed", attempt=attempt,
                       error=f"{type(exc).__name__}: {str(exc)[:200]}")
                    sleep(10)
    report["wall_s"] = round(clock() - t0, 1)
    if interrupted is not None:
        raise interrupted
    return report


def cleanup(api, project_id: str, log: Callable[[str], None] = print) -> List[str]:
    """Delete every VM labelled by this module in ``project_id``."""
    gone = []
    for inst in api.list_labeled(project_id):
        log(f"[cleanup] deleting {inst['name']} ({inst['id']}, {inst['state']})")
        api.delete(inst["id"], timeout=600)
        gone.append(inst["id"])
    if not gone:
        log("[cleanup] no labelled probe VM found")
    return gone


def estimate_usd(target: Dict[str, str], minutes: float) -> Optional[float]:
    """GPU + vCPU + RAM at the console list prices (eu-north1, before tax,
    read 2026-10-03) for the whole ``minutes``. Boot disk and public IP are
    billed on top and not in this figure. Unknown platform -> None."""
    per_hour = {"gpu-l40s-a": 1.35 + 8 * 0.012 + 32 * 0.0032}
    rate = per_hour.get(target.get("platform", ""))
    return None if rate is None else round(rate * minutes / 60, 2)


def save(report: Dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"compute_probe_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return path
