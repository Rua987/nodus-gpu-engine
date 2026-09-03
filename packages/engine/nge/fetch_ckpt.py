"""Fetch the Nodus 324M planner weights from their published release.

The weights are ~988 MB and are not in git. They are also not in Git LFS, on
purpose: GitHub's free LFS tier is 1 GB of storage and 1 GB of bandwidth per
month, so a single clone would exhaust the quota and the next one would fail
with "bandwidth quota exceeded". A release asset has neither limit.

    python -m nge.fetch_ckpt            # download, verify, write .nodus_plan_ckpt
    python -m nge.fetch_ckpt --check    # only report what is configured

Without the weights the planner falls back to a hand-written keyword
heuristic and says so loudly - see nge/planner.py.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Optional

RELEASE_URL = ("https://github.com/Rua987/nodus/releases/download/"
               "v1.0.0/checkpoint_sft_plan_v5.pt")
SHA256 = "9637ae133c9886bb04e18abf65aa00fd46c4da7d74c2311b6841d496f3b71744"
SIZE_MB = 988

_ENGINE_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_DIR = _ENGINE_DIR.parent / "nodus" / "checkpoints"
_POINTER = _ENGINE_DIR / ".nodus_plan_ckpt"


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def verify(path: Path) -> bool:
    """True when ``path`` is the published checkpoint."""
    try:
        return path.is_file() and sha256_of(path) == SHA256
    except OSError:
        return False


def download(dest: Path, url: str = RELEASE_URL) -> Path:
    """Stream the asset to ``dest``, with a progress line."""
    import urllib.request

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"fetching {url}\n  -> {dest}  (~{SIZE_MB} MB)")
    # `\r` redraws in a terminal but concatenates into one enormous line in a
    # log file - a redirected run produced a single 30k-character line. Only
    # animate when stdout is a terminal; otherwise report every 10%.
    live = sys.stdout.isatty()
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = next_mark = 0
        while True:
            block = r.read(1 << 20)
            if not block:
                break
            f.write(block)
            done += len(block)
            if not total:
                continue
            pct = 100 * done / total
            if live:
                print(f"\r  {done / 1e6:6.0f} / {total / 1e6:.0f} MB  {pct:5.1f}%",
                      end="", flush=True)
            elif pct >= next_mark:
                print(f"  {done / 1e6:6.0f} / {total / 1e6:.0f} MB  {pct:5.1f}%",
                      flush=True)
                next_mark += 10
        print()
    tmp.replace(dest)
    return dest


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Fetch the 324M planner weights")
    ap.add_argument("--dest", default=str(_DEFAULT_DIR / "checkpoint_sft_plan_v5.pt"))
    ap.add_argument("--check", action="store_true",
                    help="report the configured checkpoint, download nothing")
    ap.add_argument("--force", action="store_true",
                    help="re-download even if a valid copy is present")
    args = ap.parse_args(argv)

    from nge import config as _cfg, planner
    path, exists, note = planner.ckpt_status(_cfg.load())
    if args.check:
        print(note)
        if exists:
            print("  sha256 matches published asset:", verify(path))
        return 0 if exists else 1

    if exists and verify(path) and not args.force:
        print(f"already present and verified: {path}")
        return 0

    dest = Path(args.dest).expanduser()
    if dest.is_file() and verify(dest) and not args.force:
        print(f"already downloaded: {dest}")
    else:
        try:
            download(dest)
        except Exception as exc:
            print(f"download failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            print(f"fetch it by hand from {RELEASE_URL}", file=sys.stderr)
            return 2
        if not verify(dest):
            print("sha256 mismatch - refusing to point at a corrupt file",
                  file=sys.stderr)
            print(f"  expected {SHA256}", file=sys.stderr)
            return 3
        print("sha256 verified")

    _POINTER.write_text(str(dest), encoding="utf-8")
    print(f"wrote {_POINTER.name} -> {dest}")
    print("the planner will now use the real 324M model")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
