#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ TEMPLE IAM - NODUS BACKENDS
⚡ Multi-backend : Ollama (local) · DeepSeek · Anthropic (Claude)
🔥 Même boucle ReAct, modèle local OU API capable

Copyright © 2024 Temple IAM - All Rights Reserved

SÉCURITÉ : les clés API ne sont JAMAIS hardcodées ni passées en clair.
    Lecture depuis .{provider}_api_key (fichier) ou variable d'environnement.

Architecture :
    detect_backend(model)   → "ollama" | "deepseek" | "anthropic" (pur)
    chat_api(messages, ...)  → appelle le bon backend, NORMALISE la réponse
                               vers le format Ollama attendu par la boucle :
        {"role":"assistant", "content": str,
         "tool_calls": [{"id":.., "function":{"name":.., "arguments": dict|str}}]}

    Les traductions de format (OpenAI ↔ Anthropic) sont des fonctions pures,
    testées avec HTTP mocké (pas besoin de vraies clés pour les tests).
"""

import json
import os
from pathlib import Path
from typing import List, Optional, Tuple

import requests

# ── Endpoints ─────────────────────────────────────────────────────────────────
DEEPSEEK_URL      = "https://api.deepseek.com/v1/chat/completions"
OPENROUTER_URL    = "https://openrouter.ai/api/v1/chat/completions"
ANTHROPIC_URL     = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
API_TIMEOUT       = 300
ANTHROPIC_MAX_TOKENS = 4096
OPENROUTER_PREFIX = "openrouter/"
GEMINI_PREFIX = "gemini:"
VERTEX_PREFIX = "vertex:"
HACKATHON_DEFAULT_MODEL = "vertex:gemini-2.5-flash"

_HERE = Path(__file__).parent.resolve()


def hackathon_mode() -> bool:
    """True when Agentic Cinema / submission guard is active."""
    return os.environ.get("NODUS_HACKATHON", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def assert_hackathon_llm_model(model: str) -> None:
    """
    Block third-party LLM backends when NODUS_HACKATHON=1.

    Allows only Google Cloud AI (gemini:/vertex: prefixes). See AGENTIC_CINEMA.md.
    """
    if not hackathon_mode():
        return
    backend = detect_backend(model)
    if backend not in ("gemini", "vertex"):
        raise RuntimeError(
            f"NODUS_HACKATHON=1 allows only Google Cloud AI "
            f"(gemini:… or vertex:…). Got {model!r} ({backend}). "
            f"See AGENTIC_CINEMA.md."
        )


# ── Détection du backend ──────────────────────────────────────────────────────

def detect_backend(model: str) -> str:
    """
    Détermine le backend à partir du nom de modèle.

    Règles (fonction pure, sans ambiguïté avec les modèles Ollama) :
        - "openrouter/*"                   → "openrouter" (préfixe explicite)
        - "claude-*"                       → "anthropic"
        - "deepseek-chat" / "deepseek-reasoner" → "deepseek" (noms API exacts)
        - "gemini:*"                       → "gemini" (préfixe explicite)
        - tout le reste (qwen3.5:2b, granite4.1:3b, deepseek-coder:latest, …)
                                           → "ollama"

    Args:
        model: Nom du modèle

    Returns:
        "ollama" | "deepseek" | "anthropic" | "openrouter" | "gemini" | "vertex"

    Example:
        >>> detect_backend("openrouter/anthropic/claude-3.5-sonnet")
        'openrouter'
        >>> detect_backend("claude-sonnet-4-5")
        'anthropic'
        >>> detect_backend("deepseek-chat")
        'deepseek'
        >>> detect_backend("gemini:gemini-2.5-flash")
        'gemini'
        >>> detect_backend("vertex:gemini-2.5-flash")
        'vertex'
        >>> detect_backend("qwen3.5:2b")
        'ollama'
        >>> detect_backend("deepseek-coder:latest")
        'ollama'
    """
    name = (model or "").strip().lower()
    if name.startswith(OPENROUTER_PREFIX):
        return "openrouter"
    if name.startswith("claude-"):
        return "anthropic"
    if name in ("deepseek-chat", "deepseek-reasoner"):
        return "deepseek"
    if name.startswith(GEMINI_PREFIX):
        return "gemini"
    if name.startswith(VERTEX_PREFIX):
        return "vertex"
    return "ollama"


# ── Lecture des clés (jamais hardcodées) ──────────────────────────────────────

def load_api_key(provider: str) -> Optional[str]:
    """
    Lit la clé API d'un provider depuis un fichier ou l'environnement.

    Ordre :
        1. fichier .{provider}_api_key dans le dossier du module
        2. variable d'environnement {PROVIDER}_API_KEY

    Args:
        provider: "deepseek" | "anthropic"

    Returns:
        La clé (strippée) ou None si introuvable.
    """
    key_file = _HERE / f".{provider}_api_key"
    try:
        if key_file.exists():
            content = key_file.read_text(encoding="utf-8").strip()
            if content:
                return content
    except OSError:
        pass
    return os.environ.get(f"{provider.upper()}_API_KEY")


# ── Backend Ollama-style (DeepSeek = OpenAI-compatible) ────────────────────────

def _normalize_openai_message(data: dict) -> dict:
    """
    Normalise une réponse OpenAI-compatible vers le format de la boucle.

    OpenAI renvoie {"choices":[{"message":{content, tool_calls:[{id,
    function:{name, arguments(str JSON)}}]}}]}. La boucle attend un message
    assistant avec le même schéma tool_calls — on extrait juste de l'enveloppe.

    Args:
        data: JSON de réponse OpenAI/DeepSeek

    Returns:
        Message assistant normalisé (Ollama-style).
    """
    choices = data.get("choices") or []
    if not choices:
        return {"role": "assistant", "content": ""}
    msg = choices[0].get("message", {}) or {}
    normalized = {
        "role": "assistant",
        "content": msg.get("content") or "",
    }
    if msg.get("tool_calls"):
        normalized["tool_calls"] = msg["tool_calls"]
    return normalized


def _chat_openai_compatible(
    messages: list,
    model: str,
    tools: Optional[list],
    url: str,
    api_key: str,
    extra_headers: Optional[dict] = None,
) -> dict:
    """
    Appel générique vers une API OpenAI-compatible (DeepSeek, OpenRouter…).

    Args:
        messages:      Historique (format OpenAI/Ollama)
        model:         Identifiant du modèle côté API
        tools:         TOOL_SCHEMAS (format OpenAI)
        url:           Endpoint chat/completions
        api_key:       Clé Bearer
        extra_headers: En-têtes additionnels (ex: OpenRouter referer/title)

    Returns:
        Message assistant normalisé.
    """
    payload: dict = {"model": model, "messages": messages, "stream": False}
    if tools:
        payload["tools"] = tools
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    resp = requests.post(url, json=payload, headers=headers, timeout=API_TIMEOUT)
    resp.raise_for_status()
    return _normalize_openai_message(resp.json())


def _chat_deepseek(messages: list, model: str, tools: Optional[list]) -> dict:
    """
    Appel DeepSeek (API OpenAI-compatible).

    Raises:
        RuntimeError: si la clé API est absente.
    """
    api_key = load_api_key("deepseek")
    if not api_key:
        raise RuntimeError(
            "DeepSeek API key missing — create .deepseek_api_key or set DEEPSEEK_API_KEY"
        )
    return _chat_openai_compatible(messages, model, tools, DEEPSEEK_URL, api_key)


def _openrouter_model_id(model: str) -> str:
    """
    Retire le préfixe 'openrouter/' pour obtenir l'id de modèle réel.

    Fonction pure (préserve la casse de l'id réel).

    Args:
        model: Nom complet (ex: 'openrouter/anthropic/claude-3.5-sonnet')

    Returns:
        Id de modèle OpenRouter (ex: 'anthropic/claude-3.5-sonnet').

    Example:
        >>> _openrouter_model_id("openrouter/openai/gpt-4o")
        'openai/gpt-4o'
        >>> _openrouter_model_id("plain-model")
        'plain-model'
    """
    if model.lower().startswith(OPENROUTER_PREFIX):
        return model[len(OPENROUTER_PREFIX):]
    return model


def _chat_openrouter(messages: list, model: str, tools: Optional[list]) -> dict:
    """
    Appel OpenRouter (API OpenAI-compatible, accès multi-modèles via 1 clé).

    Le nom de modèle est préfixé 'openrouter/' ; on le retire avant l'appel.

    Raises:
        RuntimeError: si la clé API est absente.
    """
    api_key = load_api_key("openrouter")
    if not api_key:
        raise RuntimeError(
            "OpenRouter API key missing — create .openrouter_api_key or set OPENROUTER_API_KEY"
        )
    real_model = _openrouter_model_id(model)
    extra_headers = {
        "HTTP-Referer": "https://temple-iam.local",
        "X-Title": "NODUS Agent",
    }
    return _chat_openai_compatible(
        messages, real_model, tools, OPENROUTER_URL, api_key, extra_headers,
    )


# ── Backend Anthropic (traduction de format) ──────────────────────────────────

def _to_anthropic_tools(tools: Optional[list]) -> list:
    """
    Convertit des tools OpenAI vers le format Anthropic.

    OpenAI:   {type:function, function:{name, description, parameters}}
    Anthropic:{name, description, input_schema}

    Args:
        tools: Liste de tools OpenAI (ou None)

    Returns:
        Liste de tools Anthropic (vide si None).
    """
    if not tools:
        return []
    out = []
    for t in tools:
        fn = t.get("function", {})
        out.append({
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
        })
    return out


def _to_anthropic_messages(messages: list) -> Tuple[str, list]:
    """
    Convertit l'historique Ollama-style vers (system, messages) Anthropic.

    - role system            → concaténé dans la chaîne system (param séparé)
    - role user (str)        → {role:user, content:[{type:text,text}]}
    - role assistant         → blocs text + tool_use (depuis tool_calls)
    - role tool              → {role:user, content:[{type:tool_result,
                                tool_use_id, content}]}

    Args:
        messages: Historique (format Ollama)

    Returns:
        Tuple (system_str, anthropic_messages).
    """
    system_parts: List[str] = []
    out: List[dict] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content") or ""
        if role == "system":
            if content:
                system_parts.append(content)
        elif role == "user":
            out.append({"role": "user", "content": [{"type": "text", "text": content}]})
        elif role == "assistant":
            blocks: List[dict] = []
            if content:
                blocks.append({"type": "text", "text": content})
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function", {})
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"_raw": args}
                blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id", "call_0"),
                    "name": fn.get("name", ""),
                    "input": args,
                })
            out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
        elif role == "tool":
            out.append({"role": "user", "content": [{
                "type": "tool_result",
                "tool_use_id": m.get("tool_call_id", "call_0"),
                "content": content,
            }]})
    return "\n\n".join(system_parts), out


def _from_anthropic_response(data: dict) -> dict:
    """
    Normalise une réponse Anthropic vers le format de la boucle.

    Anthropic renvoie content = liste de blocs [{type:text,text},
    {type:tool_use, id, name, input}]. On reconstruit un message assistant
    Ollama-style.

    Args:
        data: JSON de réponse Anthropic

    Returns:
        Message assistant normalisé.
    """
    blocks = data.get("content") or []
    text_parts: List[str] = []
    tool_calls: List[dict] = []
    for block in blocks:
        btype = block.get("type")
        if btype == "text":
            text_parts.append(block.get("text", ""))
        elif btype == "tool_use":
            tool_calls.append({
                "id": block.get("id", "call_0"),
                "function": {
                    "name": block.get("name", ""),
                    "arguments": block.get("input", {}),
                },
            })
    normalized = {"role": "assistant", "content": "".join(text_parts)}
    if tool_calls:
        normalized["tool_calls"] = tool_calls
    return normalized


def _chat_anthropic(messages: list, model: str, tools: Optional[list]) -> dict:
    """
    Appel Anthropic Messages API avec traduction de format complète.

    Args:
        messages: Historique (format Ollama)
        model:    Nom du modèle Claude
        tools:    TOOL_SCHEMAS (format OpenAI)

    Returns:
        Message assistant normalisé.

    Raises:
        RuntimeError: si la clé API est absente.
    """
    api_key = load_api_key("anthropic")
    if not api_key:
        raise RuntimeError(
            "Anthropic API key missing — create .anthropic_api_key or set ANTHROPIC_API_KEY"
        )
    system, anthropic_messages = _to_anthropic_messages(messages)
    payload: dict = {
        "model": model,
        "max_tokens": ANTHROPIC_MAX_TOKENS,
        "messages": anthropic_messages,
    }
    if system:
        payload["system"] = system
    anthropic_tools = _to_anthropic_tools(tools)
    if anthropic_tools:
        payload["tools"] = anthropic_tools
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "Content-Type": "application/json",
    }
    resp = requests.post(ANTHROPIC_URL, json=payload, headers=headers, timeout=API_TIMEOUT)
    resp.raise_for_status()
    return _from_anthropic_response(resp.json())


# ── Backend Gemini (traduction de format, SDK google-genai) ───────────────────

def _gemini_model_id(model: str) -> str:
    """
    Retire le préfixe 'gemini:' pour obtenir l'id de modèle réel.

    Fonction pure (préserve la casse de l'id réel).

    Args:
        model: Nom complet (ex: 'gemini:gemini-2.5-flash')

    Returns:
        Id de modèle Gemini (ex: 'gemini-2.5-flash').

    Example:
        >>> _gemini_model_id("gemini:gemini-2.5-flash")
        'gemini-2.5-flash'
        >>> _gemini_model_id("plain-model")
        'plain-model'
    """
    if model.lower().startswith(GEMINI_PREFIX):
        return model[len(GEMINI_PREFIX):]
    return model


def _vertex_model_id(model: str) -> str:
    """
    Retire le préfixe 'vertex:' pour obtenir l'id de modèle réel.

    Miroir de _gemini_model_id (préserve la casse de l'id réel).

    Args:
        model: Nom complet (ex: 'vertex:gemini-2.5-flash')

    Returns:
        Id de modèle Vertex AI (ex: 'gemini-2.5-flash').

    Example:
        >>> _vertex_model_id("vertex:gemini-2.5-flash")
        'gemini-2.5-flash'
        >>> _vertex_model_id("plain-model")
        'plain-model'
    """
    if model.lower().startswith(VERTEX_PREFIX):
        return model[len(VERTEX_PREFIX):]
    return model


def _vertex_project() -> str:
    """
    Projet Google Cloud requis pour l'appel Vertex AI.

    L'id du projet (pas le nom affiché) se lit dans GOOGLE_CLOUD_PROJECT.

    Raises:
        RuntimeError: si la variable d'environnement est absente.
    """
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
    if not project:
        raise RuntimeError(
            "Vertex AI project missing — set GOOGLE_CLOUD_PROJECT "
            "(your GCP project id, e.g. GOOGLE_CLOUD_PROJECT=nodus-hackathon-2026)"
        )
    return project


def _vertex_location() -> str:
    """
    Région Vertex AI (GOOGLE_CLOUD_LOCATION, sinon GOOGLE_CLOUD_REGION,
    défaut 'us-central1').
    """
    return (os.environ.get("GOOGLE_CLOUD_LOCATION") or
            os.environ.get("GOOGLE_CLOUD_REGION") or "us-central1").strip() or "us-central1"


def _to_gemini_contents(messages: list) -> Tuple[str, list]:
    """
    Convertit l'historique Ollama-style vers (system, contents) Gemini.

    - role system            → chaîne system (param system_instruction séparé)
    - role user (str)        → Content(role="user", parts=[Part(text=…)])
    - role assistant         → Content(role="model") : blocs text + function_call
                               (depuis tool_calls) ; id → nom mémorisé pour
                               associer les résultats d'outil
    - role tool              → Content(role="user") : Part(function_response=…)
                               avec le NOM de la fonction d'origine (Gemini
                               l'exige, contrairement à OpenAI/Anthropic)

    Args:
        messages: Historique (format Ollama)

    Returns:
        Tuple (system_str, gemini_contents).
    """
    system_parts: List[str] = []
    contents: list = []
    fn_by_call_id: Dict[str, str] = {}

    # Import tardif du paquet types (levé à l'appel, pas à l'import du module).
    from google.genai import types

    for m in messages:
        role = m.get("role")
        content = m.get("content") or ""
        if role == "system":
            if content:
                system_parts.append(content)
        elif role == "user":
            contents.append(types.Content(
                role="user", parts=[types.Part(text=content)],
            ))
        elif role == "assistant":
            parts: list = []
            if content:
                parts.append(types.Part(text=content))
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"_raw": args}
                cid = tc.get("id", f"call_{len(fn_by_call_id)}")
                fn_by_call_id[cid] = name
                parts.append(types.Part(
                    function_call=types.FunctionCall(name=name, args=args or {}),
                ))
            contents.append(types.Content(
                role="model", parts=parts or [types.Part(text="")],
            ))
        elif role == "tool":
            cid = m.get("tool_call_id", "")
            name = fn_by_call_id.get(cid, m.get("name", "?"))
            contents.append(types.Content(
                role="user",
                parts=[types.Part(function_response=types.FunctionResponse(
                    name=name,
                    response={"output": content, "success": m.get("success", True)},
                ))],
            ))
    return "\n\n".join(system_parts), contents


def _to_gemini_tools(tools: Optional[list]) -> Optional[list]:
    """
    Convertit des tools OpenAI vers le format Gemini (function_declarations).

    OpenAI:   {type:function, function:{name, description, parameters}}
    Gemini:   types.Tool(function_declarations=[FunctionDeclaration(name,
              description, parameters)])

    Args:
        tools: Liste de tools OpenAI (ou None)

    Returns:
        Liste [types.Tool] Gemini (None si aucun tool).
    """
    if not tools:
        return None
    from google.genai import types

    declarations = []
    for t in tools:
        fn = t.get("function", {})
        declarations.append(types.FunctionDeclaration(
            name=fn.get("name", ""),
            description=fn.get("description", ""),
            parameters=fn.get("parameters", {"type": "object", "properties": {}}),
        ))
    return [types.Tool(function_declarations=declarations)] if declarations else None


def _from_gemini_response(resp) -> dict:
    """
    Normalise une réponse Gemini vers le format de la boucle.

    Gemini renvoie candidates[0].content.parts = [Part(text=…),
    Part(function_call=FunctionCall(name, args))]. On reconstruit un message
    assistant Ollama-style (arguments en dict, comme Anthropic — la boucle
    accepte str JSON ou dict).

    Args:
        resp: Objet réponse google.genai GenerateContentResponse

    Returns:
        Message assistant normalisé.
    """
    cands = getattr(resp, "candidates", None) or []
    if not cands:
        return {"role": "assistant", "content": ""}
    parts = getattr(getattr(cands[0], "content", None), "parts", None) or []
    text_parts: List[str] = []
    tool_calls: List[dict] = []
    for part in parts:
        text = getattr(part, "text", None)
        if text:
            text_parts.append(text)
        fc = getattr(part, "function_call", None)
        if fc is not None:
            args: dict = {}
            raw_args = getattr(fc, "args", None)
            if raw_args:
                try:
                    args = dict(raw_args)
                except Exception:
                    args = {"_raw": str(raw_args)}
            tool_calls.append({
                "id": getattr(fc, "id", None) or f"call_{len(tool_calls)}",
                "function": {"name": getattr(fc, "name", ""), "arguments": args},
            })
    normalized = {"role": "assistant", "content": "".join(text_parts)}
    if tool_calls:
        normalized["tool_calls"] = tool_calls
    return normalized


def _chat_gemini(messages: list, model: str, tools: Optional[list]) -> dict:
    """
    Appel Gemini (SDK officiel google-genai, fonction calling native).

    Le nom de modèle est préfixé 'gemini:' ; on le retire avant l'appel.

    Args:
        messages: Historique (format Ollama)
        model:    Nom du modèle (ex: 'gemini:gemini-2.5-flash')
        tools:    TOOL_SCHEMAS (format OpenAI)

    Returns:
        Message assistant normalisé (Ollama-style).

    Raises:
        RuntimeError: si la clé API ou le paquet google-genai est absent.
    """
    api_key = load_api_key("gemini")
    if not api_key:
        raise RuntimeError(
            "Gemini API key missing — create .gemini_api_key or set GEMINI_API_KEY"
        )
    try:
        from google import genai
    except ImportError:
        raise RuntimeError(
            "google-genai package not installed — pip install google-genai"
        )
    real_model = _gemini_model_id(model)
    system, contents = _to_gemini_contents(messages)
    if not contents:
        from google.genai import types
        contents = [types.Content(role="user", parts=[types.Part(text="Continue.")])]
    gemini_tools = _to_gemini_tools(tools)
    config: dict = {}
    if system:
        config["system_instruction"] = system
    if gemini_tools:
        config["tools"] = gemini_tools
    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model=real_model,
        contents=contents,
        config=config,
    )
    return _from_gemini_response(resp)


def _chat_vertex(messages: list, model: str, tools: Optional[list]) -> dict:
    """
    Appel Vertex AI — Google Cloud Agent Builder (google-genai, vertexai=True).

    Même traduction que le backend Gemini (contents/tools/réponse identiques) ;
    seule l'authentification change : ADC Google Cloud au lieu d'une clé API.
    L'exécuteur tourne donc sur le runtime de la plateforme Agent Builder
    (Vertex AI / Gemini Enterprise), conformément au brief du hackathon.

    Args:
        messages: Historique (format Ollama)
        model:    Nom du modèle (ex: 'vertex:gemini-2.5-flash')
        tools:    TOOL_SCHEMAS (format OpenAI)

    Returns:
        Message assistant normalisé (Ollama-style).

    Raises:
        RuntimeError: si GOOGLE_CLOUD_PROJECT / GOOGLE_APPLICATION_CREDENTIALS
        manquants, ou paquet google-genai absent.
    """
    project = _vertex_project()
    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip():
        raise RuntimeError(
            "Vertex AI credentials missing — set GOOGLE_APPLICATION_CREDENTIALS "
            "(service-account JSON) or run `gcloud auth application-default login`"
        )
    try:
        from google import genai
    except ImportError:
        raise RuntimeError(
            "google-genai package not installed — pip install google-genai"
        )
    real_model = _vertex_model_id(model)
    system, contents = _to_gemini_contents(messages)
    if not contents:
        from google.genai import types
        contents = [types.Content(role="user", parts=[types.Part(text="Continue.")])]
    gemini_tools = _to_gemini_tools(tools)
    config: dict = {}
    if system:
        config["system_instruction"] = system
    if gemini_tools:
        config["tools"] = gemini_tools
    client = genai.Client(vertexai=True, project=project, location=_vertex_location())
    resp = client.models.generate_content(
        model=real_model,
        contents=contents,
        config=config,
    )
    return _from_gemini_response(resp)


# ── Dispatcher ────────────────────────────────────────────────────────────────

def chat_api(messages: list, model: str, tools: Optional[list]) -> dict:
    """
    Route vers le backend API approprié (DeepSeek, OpenRouter, Anthropic,
    Gemini, Vertex AI).

    NE gère PAS Ollama (laissé à nodus_agent._chat pour préserver le chemin
    local existant). Appeler uniquement quand detect_backend != "ollama".

    Args:
        messages: Historique
        model:    Nom du modèle
        tools:    TOOL_SCHEMAS

    Returns:
        Message assistant normalisé (Ollama-style).

    Raises:
        ValueError: si le backend n'est pas un backend API.
        RuntimeError: si NODUS_HACKATHON=1 et le modèle n'est pas Google Cloud AI.
    """
    assert_hackathon_llm_model(model)
    backend = detect_backend(model)
    if backend == "deepseek":
        return _chat_deepseek(messages, model, tools)
    if backend == "openrouter":
        return _chat_openrouter(messages, model, tools)
    if backend == "anthropic":
        return _chat_anthropic(messages, model, tools)
    if backend == "gemini":
        return _chat_gemini(messages, model, tools)
    if backend == "vertex":
        return _chat_vertex(messages, model, tools)
    raise ValueError(f"chat_api called for non-API backend: {backend}")
