"""Compute Phase 0: the preflight reports what the Nebius SDK will actually
accept, and never touches the Token Factory project id.

No network, no real key: credentials files are generated here with a
throwaway RSA key.
"""
import json
from pathlib import Path

import pytest

from nge import config as _cfg
from nge.fleet import compute


@pytest.fixture
def clean(tmp_path, monkeypatch):
    """No env, no engine-dir files, no CLI profile."""
    for k in ("NEBIUS_IAM_TOKEN", "NEBIUS_SA_CREDENTIALS_FILE",
              "NEBIUS_COMPUTE_PROJECT_ID", "NEBIUS_SUBNET_ID", "NEBIUS_PROJECT_ID"):
        monkeypatch.delenv(k, raising=False)
    eng = tmp_path / "engine"
    eng.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(_cfg, "_ENGINE_DIR", eng)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return eng, home


def _creds_file(path: Path, iss="serviceaccount-e00test", sub=None) -> Path:
    pytest.importorskip("nebius")
    rsa = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.rsa")
    from cryptography.hazmat.primitives import serialization
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    path.write_text(json.dumps({"subject-credentials": {
        "type": "JWT", "alg": "RS256", "private-key": pem,
        "kid": "publickey-e00test", "iss": iss, "sub": sub or iss}}),
        encoding="utf-8")
    return path


def test_nothing_configured_is_not_ready_and_says_what_is_missing(clean):
    r = compute.check_credentials()
    assert r["ready_for_wire"] is False and r["spawn_allowed"] is False
    assert r["auth"] is None and r["project_id"] is False
    text = " ".join(r["missing"])
    assert "credentials file" in text and "NEBIUS_COMPUTE_PROJECT_ID" in text


def test_token_factory_project_id_is_never_used_for_compute(clean, monkeypatch):
    """NEBIUS_PROJECT_ID is the Token Factory id the live path needs; the old
    plan said to put the Compute id there, which would break --live."""
    monkeypatch.setenv("NEBIUS_PROJECT_ID", "project-e00compute")
    monkeypatch.setenv("NEBIUS_IAM_TOKEN", "t")
    r = compute.check_credentials()
    assert r["project_id"] is False


def test_an_aiproject_id_is_refused_with_the_reason(clean, monkeypatch):
    monkeypatch.setenv("NEBIUS_COMPUTE_PROJECT_ID", "aiproject-abc123")
    r = compute.check_credentials()
    assert r["project_id"] is False
    assert "Token Factory" in r["project_id_error"]
    assert any("Token Factory" in m for m in r["missing"])


def test_valid_credentials_file_and_project_make_it_ready(clean):
    eng, _ = clean
    _creds_file(eng / ".nebius_sa_credentials.json")
    (eng / ".nebius_compute_project_id").write_text("project-e00test\n", encoding="utf-8")
    r = compute.check_credentials()
    assert r["auth"] == "credentials_file" and r["credentials_file_ok"] is True
    assert r["ready_for_wire"] is True
    assert r["spawn_allowed"] is False, "Phase 0 never allows a spawn"
    assert r["subnet_id"] is False and any("Phase 2" in m for m in r["missing"])


def test_invalid_credentials_file_is_explained_without_leaking_the_key(clean, monkeypatch):
    eng, _ = clean
    f = _creds_file(eng / "bad.json", iss="serviceaccount-a", sub="serviceaccount-b")
    monkeypatch.setenv("NEBIUS_SA_CREDENTIALS_FILE", str(f))
    monkeypatch.setenv("NEBIUS_COMPUTE_PROJECT_ID", "project-e00test")
    r = compute.check_credentials()
    assert r["credentials_file_ok"] is False and r["ready_for_wire"] is False
    assert "Issuer must be the same as subject" in r["credentials_file_error"]
    blob = json.dumps(r)
    assert "PRIVATE KEY" not in blob and "MII" not in blob


def test_credentials_file_set_but_absent_is_reported(clean, monkeypatch, tmp_path):
    monkeypatch.setenv("NEBIUS_SA_CREDENTIALS_FILE", str(tmp_path / "nope.json"))
    r = compute.check_credentials()
    assert r["credentials_file_error"] == "file not found" and r["auth"] is None


def test_cli_profile_counts_as_auth(clean, monkeypatch):
    _, home = clean
    (home / ".nebius").mkdir()
    (home / ".nebius" / "config.yaml").write_text("default: x\n", encoding="utf-8")
    monkeypatch.setenv("NEBIUS_COMPUTE_PROJECT_ID", "project-e00test")
    r = compute.check_credentials()
    assert r["auth"] == "cli_profile"


def test_iam_token_counts_as_auth(clean, monkeypatch):
    monkeypatch.setenv("NEBIUS_IAM_TOKEN", "short-lived")
    monkeypatch.setenv("NEBIUS_COMPUTE_PROJECT_ID", "project-e00test")
    r = compute.check_credentials()
    if not r["sdk_installed"]:
        pytest.skip("nebius SDK absent: ready_for_wire needs it")
    assert r["auth"] == "iam_token" and r["ready_for_wire"] is True


def test_checklist_prints_every_line(clean):
    text = compute.format_checklist(compute.check_credentials())
    assert "Phase 0" in text and "spawn_allowed=False" in text and "missing:" in text


def test_compute_files_are_gitignored():
    repo = Path(__file__).resolve().parents[3]
    rules = (repo / "packages" / "engine" / ".gitignore").read_text(encoding="utf-8")
    assert ".nebius_*" in rules.splitlines()


def test_every_file_the_docs_say_to_copy_is_in_the_repo():
    """`cp .env.example .env` was in two docs while .env.example matched the
    `.env.*` ignore rule: no clone ever had it."""
    import re
    engine = Path(__file__).resolve().parents[1]
    docs = [engine / "README.md", *(engine / "docs").glob("*.md")]
    for doc in docs:
        for src in re.findall(r"^\s*cp\s+(\S+)\s+\S+", doc.read_text(encoding="utf-8"), re.M):
            assert (engine / src).is_file(), f"{doc.name}: cp {src}"


@pytest.mark.parametrize("wrong,kind", [("tenantuseraccount-e00abc", "tenantuseraccount"),
                                        ("serviceaccount-e00abc", "serviceaccount"),
                                        ("tenant-e00abc", "tenant"),
                                        ("e00abc", "unknown")])
def test_an_id_of_another_resource_type_is_refused(clean, monkeypatch, wrong, kind):
    """The first id offered here was the signed-in user's account id."""
    monkeypatch.setenv("NEBIUS_COMPUTE_PROJECT_ID", wrong)
    r = compute.check_credentials()
    assert r["project_id"] is False
    assert f"a {kind} id, not a project" in r["project_id_error"]


def test_a_project_id_is_accepted(clean, monkeypatch):
    monkeypatch.setenv("NEBIUS_COMPUTE_PROJECT_ID", "project-e00abc")
    r = compute.check_credentials()
    assert r["project_id"] is True and r["project_id_error"] is None
