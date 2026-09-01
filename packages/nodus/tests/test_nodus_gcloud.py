# -*- coding: utf-8 -*-
"""Tests du sink Google Cloud Storage (mock-first) + du backend Gemini.

Le cloud est importé et appelé en code, mais gaté sur les creds : en l'absence
de GCLOUD_BUCKET / GOOGLE_APPLICATION_CREDENTIALS / paquet installé, tout
retombe sur le mode mock déterministe — jamais fatal (pattern Grafana).

Gemini : on teste le format de traduction (messages + tool calls + réponse)
avec un faux paquet google.genai — pas besoin de vraie clé ni réseau.
"""

import json
import os
import sys
import types as _pytypes

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import nodus_backends as nb  # noqa: E402
import nodus_gcloud as ng  # noqa: E402
from nodus_gcloud import GcsClient, gcs_from_env  # noqa: E402
from nodus_tools import dispatch_tool  # noqa: E402


# ── GcsClient : mode mock (déterministe, sans creds) ─────────────────────────

def test_mock_upload_content_deterministic():
    with GcsClient(mode="mock", bucket="nodus-media-demo") as client:
        ok, out = client.upload(destination="production/brief.md", content="hello")
        assert ok
        assert out == "gs://nodus-media-demo/production/brief.md (5 bytes) [mock]"


def test_mock_upload_local_path(tmp_path):
    p = tmp_path / "brief.md"
    p.write_text("# Shoot-day brief\n", encoding="utf-8")
    with GcsClient(mode="mock", bucket="b") as client:
        ok, out = client.upload(local_path=str(p), destination="x/brief.md")
    assert ok and "gs://b/x/brief.md" in out and "[mock]" in out


def test_upload_records_event():
    with GcsClient(mode="mock", bucket="b") as client:
        client.upload(destination="x.md", content="data")
        assert len(client.events) == 1
        evt = client.events[0]
        assert evt["kind"] == "upload"
        assert evt["destination"] == "x.md"
        assert evt["mode"] == "mock"


def test_upload_off_mode_noop():
    with GcsClient(mode="off") as client:
        ok, out = client.upload(destination="x.md", content="data")
        assert ok is False and "off" in out
        assert client.events == []


def test_upload_missing_destination():
    with GcsClient(mode="mock", bucket="b") as client:
        ok, out = client.upload(content="data")
    assert ok is False and "destination" in out


def test_upload_no_bucket():
    with GcsClient(mode="mock") as client:
        ok, out = client.upload(destination="x.md", content="data")
    assert ok is False and "bucket" in out


def test_upload_missing_file(tmp_path):
    with GcsClient(mode="mock", bucket="b") as client:
        ok, out = client.upload(local_path=str(tmp_path / "nope.md"), destination="x.md")
    assert ok is False and "cannot read" in out


def test_mock_jsonl_output(tmp_path):
    path = tmp_path / "uploads.jsonl"
    with GcsClient(mode="mock", bucket="b", jsonl_path=str(path)) as client:
        client.upload(destination="x.md", content="data")
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["destination"] == "x.md"


def test_summary_timeline():
    with GcsClient(mode="mock", bucket="b") as client:
        client.upload(destination="prod/x.md", content="data")
        text = client.summary()
    assert "upload prod/x.md" in text
    assert "gs://b/prod/x.md" in text
    assert "[mock]" in text


def test_summary_empty():
    with GcsClient(mode="mock", bucket="b") as client:
        assert client.summary() == "(no uploads)"


# ── gcs_from_env : pilotage par environnement ────────────────────────────────

def test_from_env_default_mock(monkeypatch):
    monkeypatch.delenv("NODUS_GCLOUD", raising=False)
    with gcs_from_env() as client:
        assert client.mode == "mock"


def test_from_env_jsonl(monkeypatch, tmp_path):
    target = tmp_path / "u.jsonl"
    monkeypatch.setenv("NODUS_GCLOUD", f"jsonl:{target}")
    with gcs_from_env() as client:
        assert client.mode == "mock"
        assert client._jsonl is not None


def test_from_env_off(monkeypatch):
    monkeypatch.setenv("NODUS_GCLOUD", "off")
    with gcs_from_env() as client:
        assert client.mode == "off"


def test_from_env_real_without_creds_falls_back(monkeypatch):
    monkeypatch.setenv("NODUS_GCLOUD", "real")
    monkeypatch.delenv("GCLOUD_BUCKET", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    with gcs_from_env() as client:
        assert client.mode == "mock"
        assert any("GCLOUD_BUCKET" in e for e in client.errors)


# ── Mode real : fallbacks + vrai chemin SDK (patché) ────────────────────────

def test_real_requires_bucket(monkeypatch):
    monkeypatch.delenv("GCLOUD_BUCKET", raising=False)
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "x.json")
    client = GcsClient(mode="real")
    assert client.mode == "mock"
    assert any("GCLOUD_BUCKET" in e for e in client.errors)
    client.close()


def test_real_requires_adc(monkeypatch):
    monkeypatch.setenv("GCLOUD_BUCKET", "b")
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    client = GcsClient(mode="real")
    assert client.mode == "mock"
    assert any("GOOGLE_APPLICATION_CREDENTIALS" in e for e in client.errors)
    client.close()


def test_real_sdk_init_failure_falls_back(monkeypatch):
    monkeypatch.setenv("GCLOUD_BUCKET", "b")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "x.json")

    class _BoomClient:
        def get_bucket(self, name):
            raise RuntimeError("credential scopes mismatch")

    fake_storage = _pytypes.ModuleType("google.cloud.storage")
    fake_storage.Client = lambda: _BoomClient()
    monkeypatch.setitem(sys.modules, "google", _FakeNs(storage=fake_storage))
    monkeypatch.setitem(sys.modules, "google.cloud", _FakeNs(storage=fake_storage))
    monkeypatch.setitem(sys.modules, "google.cloud.storage", fake_storage)

    client = GcsClient(mode="real")
    assert client.mode == "mock"
    assert any("init failed" in e for e in client.errors)
    client.close()


class _FakeNs:
    """Mini namespace pour les modules google.* factices."""

    def __init__(self, **attrs):
        for k, v in attrs.items():
            setattr(self, k, v)


class _FakeBlob:
    def __init__(self, bucket, name):
        self.bucket, self.name = bucket, name
        self.uploads = []

    def upload_from_filename(self, path, timeout=None):
        self.uploads.append((path, timeout))


class _FakeBucket:
    def __init__(self):
        self.blobs = {}

    def blob(self, name):
        self.blobs.setdefault(name, _FakeBlob(self, name))
        return self.blobs[name]


class _FakeStorageClient:
    def __init__(self):
        self.buckets = {}

    def get_bucket(self, name):
        self.buckets.setdefault(name, _FakeBucket())
        return self.buckets[name]

    def bucket(self, name):
        return self.get_bucket(name)


def _install_fake_storage(monkeypatch):
    storage = _pytypes.ModuleType("google.cloud.storage")
    storage.Client = _FakeStorageClient
    monkeypatch.setitem(sys.modules, "google", _FakeNs(cloud=_FakeNs(storage=storage)))
    monkeypatch.setitem(sys.modules, "google.cloud", _FakeNs(storage=storage))
    monkeypatch.setitem(sys.modules, "google.cloud.storage", storage)
    return storage


def test_real_upload_calls_sdk(monkeypatch, tmp_path):
    _install_fake_storage(monkeypatch)
    monkeypatch.setenv("GCLOUD_BUCKET", "b")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "x.json")
    p = tmp_path / "brief.md"
    p.write_text("hello", encoding="utf-8")
    with GcsClient(mode="real") as client:
        assert client.mode == "real"
        ok, out = client.upload(local_path=str(p), destination="x/brief.md")
        blob = client._client.buckets["b"].blob("x/brief.md")
        assert blob.uploads  # upload_from_filename a bien été appelé
    assert ok and "gs://b/x/brief.md" in out and "[real]" in out


# ── dispatch_tool → gcs_upload (chemin outil complet) ───────────────────────

def test_dispatch_gcs_upload_mock_content(tmp_path):
    r = dispatch_tool("gcs_upload", {"destination": "x/b.md", "content": "hi",
                                     "bucket": "b"}, cwd=str(tmp_path))
    assert r.success and "gs://b/x/b.md" in r.output and "[mock]" in r.output


def test_dispatch_gcs_upload_local_path_confined(tmp_path):
    p = tmp_path / "brief.md"
    p.write_text("data", encoding="utf-8")
    r = dispatch_tool("gcs_upload", {"local_path": "brief.md",
                                     "destination": "x/brief.md", "bucket": "b"},
                      cwd=str(tmp_path))
    assert r.success and "gs://b/x/brief.md" in r.output


def test_dispatch_gcs_upload_requires_bucket(tmp_path):
    r = dispatch_tool("gcs_upload", {"destination": "x/b.md", "content": "hi"},
                      cwd=str(tmp_path))
    assert not r.success and "bucket" in r.output


# ── Backend Gemini : détection + id de modèle ────────────────────────────────

def test_detect_backend_gemini_prefix():
    assert nb.detect_backend("gemini:gemini-2.0-flash") == "gemini"
    assert nb.detect_backend("gemini:gemini-2.5-flash") == "gemini"
    # sans préfixe explicite → pas confondu avec un modèle Ollama
    assert nb.detect_backend("gemini-2.0-flash") == "ollama"
    assert nb.detect_backend("qwen3.5:2b") == "ollama"


def test_gemini_model_id_strips_prefix():
    assert nb._gemini_model_id("gemini:gemini-2.0-flash") == "gemini-2.0-flash"
    assert nb._gemini_model_id("plain-model") == "plain-model"


def test_chat_api_routes_gemini(monkeypatch):
    monkeypatch.setattr(nb, "_chat_gemini", lambda m, model, tools: {"role": "assistant",
                                                                     "content": "ok"})
    assert nb.chat_api([], "gemini:gemini-2.0-flash", None)["content"] == "ok"


def test_hackathon_blocks_non_gcp_models(monkeypatch):
    monkeypatch.setenv("NODUS_HACKATHON", "1")
    with pytest.raises(RuntimeError, match="AGENTIC_CINEMA"):
        nb.assert_hackathon_llm_model("qwen3.5:2b")
    with pytest.raises(RuntimeError, match="AGENTIC_CINEMA"):
        nb.chat_api([], "openrouter/x", None)
    nb.assert_hackathon_llm_model("vertex:gemini-2.5-flash")  # no raise


def test_hackathon_allows_gcp_when_disabled(monkeypatch):
    monkeypatch.delenv("NODUS_HACKATHON", raising=False)
    nb.assert_hackathon_llm_model("qwen3.5:2b")  # no raise


# ── Backend Gemini : faux paquet google.genai ───────────────────────────────

class _Fake:
    """Faux objet style proto : kwargs → attributs, optionnels absents → None."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __getattr__(self, name):
        return None


class _FakeModels:
    resp = None
    calls = []

    def generate_content(self, model, contents, config=None):
        _FakeModels.calls.append({"model": model, "contents": contents, "config": config})
        return _FakeModels.resp


class _FakeGenaiClient:
    last = None  # dernière instance créée (capturée pour assertions)

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.models = _FakeModels()
        _FakeGenaiClient.last = self


def _install_fake_genai(monkeypatch):
    fake_types = _pytypes.ModuleType("google.genai.types")
    for cls in ("Part", "Content", "FunctionCall", "FunctionResponse",
                "Tool", "FunctionDeclaration"):
        setattr(fake_types, cls, _Fake)
    genai = _pytypes.ModuleType("google.genai")
    genai.types = fake_types
    genai.Client = _FakeGenaiClient
    monkeypatch.setitem(sys.modules, "google", _FakeNs(genai=genai))
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    # isolation : état de classe partagé remis à zéro à chaque installation
    _FakeGenaiClient.last = None
    _FakeModels.calls = []
    _FakeModels.resp = None


def test_chat_gemini_requires_key(monkeypatch):
    monkeypatch.setattr(nb, "load_api_key", lambda provider: None)
    with pytest.raises(RuntimeError, match="Gemini API key"):
        nb._chat_gemini([{"role": "user", "content": "hi"}], "gemini:gemini-2.0-flash", None)


def test_chat_gemini_normalizes_response(monkeypatch):
    _install_fake_genai(monkeypatch)
    monkeypatch.setattr(nb, "load_api_key", lambda provider: "test-key")
    _FakeModels.calls = []
    _FakeModels.resp = _Fake(candidates=[_Fake(content=_Fake(parts=[
        _Fake(text="I will write it"),
        _Fake(function_call=_Fake(name="write_file", args={"path": "x.txt"})),
    ]))])
    msg = nb._chat_gemini([{"role": "user", "content": "write a file"}],
                          "gemini:gemini-2.0-flash", None)
    assert msg["role"] == "assistant"
    assert msg["content"] == "I will write it"
    assert msg["tool_calls"][0]["function"]["name"] == "write_file"
    assert msg["tool_calls"][0]["function"]["arguments"] == {"path": "x.txt"}
    # préfixe retiré + key passée au client
    call = _FakeModels.calls[-1]
    assert call["model"] == "gemini-2.0-flash"
    assert _FakeGenaiClient.last.kwargs.get("api_key") == "test-key"


def test_chat_gemini_empty_candidates(monkeypatch):
    _install_fake_genai(monkeypatch)
    monkeypatch.setattr(nb, "load_api_key", lambda provider: "test-key")
    _FakeModels.calls = []
    _FakeModels.resp = _Fake(candidates=[])
    msg = nb._chat_gemini([{"role": "user", "content": "hi"}],
                          "gemini:gemini-2.0-flash", None)
    assert msg == {"role": "assistant", "content": ""}


def test_to_gemini_contents_maps_tool_result_name(monkeypatch):
    _install_fake_genai(monkeypatch)
    system, contents = nb._to_gemini_contents([
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "ok",
         "tool_calls": [{"id": "c1", "function": {"name": "read_file",
                                                  "arguments": {"path": "x"}}}]},
        {"role": "tool", "content": "result", "tool_call_id": "c1"},
    ])
    assert system == "SYS"
    assert contents[0].role == "user"
    assert contents[1].role == "model"
    fc = contents[1].parts[1].function_call
    assert fc.name == "read_file"
    # le nom de la fonction est résolu via l'id du tool_call précédent
    assert contents[2].parts[0].function_response.name == "read_file"


def test_to_gemini_tools_conversion(monkeypatch):
    _install_fake_genai(monkeypatch)
    tools = [{"type": "function", "function": {"name": "bash", "description": "run",
                                               "parameters": {"type": "object"}}}]
    converted = nb._to_gemini_tools(tools)
    assert converted is not None
    assert converted[0].function_declarations[0].name == "bash"


def test_to_gemini_tools_none():
    assert nb._to_gemini_tools(None) is None


# ── Backend Vertex AI : détection + appel (google-genai vertexai=True) ───────

def test_detect_backend_vertex_prefix():
    assert nb.detect_backend("vertex:gemini-2.0-flash") == "vertex"
    assert nb.detect_backend("vertex:gemini-2.5-pro") == "vertex"
    # sans deux-points → pas confondu avec un modèle Ollama
    assert nb.detect_backend("vertex-2.0-flash") == "ollama"
    # pas de collision avec le préfixe gemini
    assert nb.detect_backend("gemini:gemini-2.0-flash") == "gemini"


def test_vertex_model_id_strips_prefix():
    assert nb._vertex_model_id("vertex:gemini-2.0-flash") == "gemini-2.0-flash"
    assert nb._vertex_model_id("plain-model") == "plain-model"


def test_chat_api_routes_vertex(monkeypatch):
    monkeypatch.setattr(nb, "_chat_vertex", lambda m, model, tools: {"role": "assistant",
                                                                    "content": "ok"})
    assert nb.chat_api([], "vertex:gemini-2.0-flash", None)["content"] == "ok"


def test_vertex_location_defaults(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_REGION", raising=False)
    assert nb._vertex_location() == "us-central1"
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "europe-west4")
    assert nb._vertex_location() == "europe-west4"
    monkeypatch.delenv("GOOGLE_CLOUD_LOCATION")
    monkeypatch.setenv("GOOGLE_CLOUD_REGION", "asia-northeast1")
    assert nb._vertex_location() == "asia-northeast1"


def test_chat_vertex_requires_project(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "fake.json")
    with pytest.raises(RuntimeError, match="GOOGLE_CLOUD_PROJECT"):
        nb._chat_vertex([{"role": "user", "content": "hi"}],
                        "vertex:gemini-2.0-flash", None)


def test_chat_vertex_requires_creds(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    with pytest.raises(RuntimeError, match="GOOGLE_APPLICATION_CREDENTIALS"):
        nb._chat_vertex([{"role": "user", "content": "hi"}],
                        "vertex:gemini-2.0-flash", None)


def test_chat_vertex_normalizes_response(monkeypatch):
    _install_fake_genai(monkeypatch)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "fake.json")
    _FakeModels.resp = _Fake(candidates=[_Fake(content=_Fake(parts=[
        _Fake(text="I will write it"),
        _Fake(function_call=_Fake(name="write_file", args={"path": "x.txt"})),
    ]))])
    msg = nb._chat_vertex([{"role": "user", "content": "write a file"}],
                          "vertex:gemini-2.0-flash", None)
    assert msg["role"] == "assistant"
    assert msg["content"] == "I will write it"
    assert msg["tool_calls"][0]["function"]["name"] == "write_file"
    assert msg["tool_calls"][0]["function"]["arguments"] == {"path": "x.txt"}
    # préfixe retiré + client construit avec vertexai=True / project / location
    call = _FakeModels.calls[-1]
    assert call["model"] == "gemini-2.0-flash"
    k = _FakeGenaiClient.last.kwargs
    assert k.get("vertexai") is True
    assert k.get("project") == "test-project"
    assert k.get("location") == "us-central1"
    assert k.get("api_key") is None


def test_chat_vertex_empty_candidates(monkeypatch):
    _install_fake_genai(monkeypatch)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "fake.json")
    _FakeModels.resp = _Fake(candidates=[])
    msg = nb._chat_vertex([{"role": "user", "content": "hi"}],
                          "vertex:gemini-2.0-flash", None)
    assert msg == {"role": "assistant", "content": ""}


def test_chat_vertex_passes_system_and_tools(monkeypatch):
    _install_fake_genai(monkeypatch)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "fake.json")
    _FakeModels.resp = _Fake(candidates=[_Fake(content=_Fake(parts=[_Fake(text="ok")]))])
    tools = [{"type": "function", "function": {"name": "bash", "description": "run",
                                               "parameters": {"type": "object"}}}]
    nb._chat_vertex([{"role": "system", "content": "SYS"},
                     {"role": "user", "content": "hi"}],
                    "vertex:gemini-2.0-flash", tools)
    call = _FakeModels.calls[-1]
    assert call["config"]["system_instruction"] == "SYS"
    assert call["config"]["tools"][0].function_declarations[0].name == "bash"
    assert call["contents"][0].role == "user"
