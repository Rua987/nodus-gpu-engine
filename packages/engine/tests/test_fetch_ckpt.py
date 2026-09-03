"""Fetching the planner weights from their release asset.

Not in Git LFS on purpose: the free tier is 1 GB of storage and 1 GB of
bandwidth per month, and the file is 988 MB - one clone would exhaust it and
the next would fail with "bandwidth quota exceeded". A release asset has
neither limit.

No test downloads anything.
"""
import hashlib

import pytest

from nge import fetch_ckpt as fc


def test_the_published_identity_is_pinned():
    assert fc.SHA256 == ("9637ae133c9886bb04e18abf65aa00fd46c4da7d74"
                         "c2311b6841d496f3b71744")
    assert fc.RELEASE_URL.startswith("https://github.com/Rua987/nodus/releases/")
    assert fc.RELEASE_URL.endswith(".pt")


def test_sha256_of_a_real_file(tmp_path):
    p = tmp_path / "w.pt"
    p.write_bytes(b"nodus")
    assert fc.sha256_of(p) == hashlib.sha256(b"nodus").hexdigest()


def test_verify_rejects_the_wrong_bytes(tmp_path):
    p = tmp_path / "w.pt"
    p.write_bytes(b"not the checkpoint")
    assert fc.verify(p) is False


def test_verify_is_false_for_a_missing_file(tmp_path):
    assert fc.verify(tmp_path / "absent.pt") is False


def test_verify_accepts_a_file_whose_digest_matches(tmp_path, monkeypatch):
    p = tmp_path / "w.pt"
    p.write_bytes(b"pretend weights")
    monkeypatch.setattr(fc, "SHA256", hashlib.sha256(b"pretend weights").hexdigest())
    assert fc.verify(p) is True


def test_check_reports_without_downloading(monkeypatch, capsys):
    called = []
    monkeypatch.setattr(fc, "download", lambda *a, **k: called.append(1))
    fc.main(["--check"])
    assert called == [], "--check must never fetch"
    assert "planner" in capsys.readouterr().out.lower()


def test_a_corrupt_download_is_refused(tmp_path, monkeypatch, capsys):
    """A truncated or wrong file must not become the configured checkpoint."""
    dest = tmp_path / "w.pt"

    def fake_download(d, url=None):
        d.parent.mkdir(parents=True, exist_ok=True)
        d.write_bytes(b"truncated")
        return d
    monkeypatch.setattr(fc, "download", fake_download)
    monkeypatch.setattr(fc, "_POINTER", tmp_path / ".nodus_plan_ckpt")

    from nge import planner
    monkeypatch.setattr(planner, "ckpt_status",
                        lambda cfg=None: (tmp_path / "none.pt", False, "absent"))

    rc = fc.main(["--dest", str(dest)])
    assert rc == 3
    assert "mismatch" in capsys.readouterr().err
    assert not (tmp_path / ".nodus_plan_ckpt").exists(), \
        "a corrupt file must not be pointed at"


def test_a_network_failure_is_reported_not_raised(tmp_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise OSError("no route to host")
    monkeypatch.setattr(fc, "download", boom)
    monkeypatch.setattr(fc, "_POINTER", tmp_path / ".nodus_plan_ckpt")
    from nge import planner
    monkeypatch.setattr(planner, "ckpt_status",
                        lambda cfg=None: (tmp_path / "none.pt", False, "absent"))

    assert fc.main(["--dest", str(tmp_path / "w.pt")]) == 2
    err = capsys.readouterr().err
    assert "download failed" in err and fc.RELEASE_URL in err


def test_progress_does_not_smear_into_one_line_when_redirected(tmp_path,
                                                               monkeypatch, capsys):
    """A redirected run produced a single 30k-character line: `\r` redraws in
    a terminal but concatenates in a file."""
    import io as _io
    import urllib.request

    payload = b"x" * (3 << 20)

    class _Resp(_io.BytesIO):
        headers = {"Content-Length": str(len(payload))}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda u: _Resp(payload))
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)

    dest = tmp_path / "w.pt"
    fc.download(dest, url="http://example.invalid/w.pt")
    assert dest.read_bytes() == payload

    out = capsys.readouterr().out
    assert "\r" not in out, "no carriage returns when stdout is not a terminal"
    assert max(len(l) for l in out.splitlines() or [""]) < 200


def test_the_partial_file_is_not_left_behind(tmp_path, monkeypatch):
    """Download to .part and rename, so an interrupted run cannot leave a
    truncated file that looks like the checkpoint."""
    import io as _io
    import urllib.request

    class _Resp(_io.BytesIO):
        headers = {"Content-Length": "5"}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda u: _Resp(b"nodus"))
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    dest = tmp_path / "w.pt"
    fc.download(dest, url="http://example.invalid/w.pt")
    assert dest.is_file()
    assert not dest.with_suffix(".pt.part").exists()
