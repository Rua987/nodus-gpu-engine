#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ NODUS — Grafana Cloud telemetry sink
⚡ Stream chaque étape d'un run (tâche → plan → tool calls → verdicts → résultat)
   vers Grafana Cloud via le serveur MCP officiel `mcp-grafana`.

Deux modes :
  - mock (défaut) : aucun token requis, événements collectés en mémoire + JSONL
    (déterministe, testé hors-ligne, idéal pour la démo de développement).
  - mcp (live)    : se connecte à `mcp-grafana` (stdio) via `McpBridge` et
    mappe chaque événement sur `create_annotation` du serveur `mcp-grafana`
    (tags = nodus,kind). Les tools sont namespacés par le nom auto-déclaré du
    serveur (`mcp-grafana.*`), pas par la clé de config mcp.json (`grafana.*`).

Le planificateur Nodus garde son vocabulaire de 8 outils natifs ; Grafana est la
couche *observabilité* du harnais : le dashboard devient le « scope » de l'agent.
Aucun échec MCP ne casse jamais un run (fallback silencieux + compteur).
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Les événements normalisés du harnais (une ligne JSON chacun).
EVENT_KINDS = ("task", "plan", "tool_call", "tool_result", "verdict", "result")

# Tags Grafana fixes pour retrouver les annotations d'un run.
_TAGS = ["nodus", "agentic-cinema"]


def _now() -> str:
    """Horodatage ISO-8601 UTC."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def mcp_grafana_command(override: Optional[str] = None):
    """Résout la commande de lancement du serveur `mcp-grafana`.

    Retourne (command, args) ou None si aucun lanceur n'est disponible.
    Ordre de résolution :
      1) override explicite (`NODUS_GRAFANA_SERVER` ou argument) ;
      2) console script pip `mcp-grafana` (même paquet PyPI que uvx ; log sur
         stderr → transport stdio propre) ;
      3) `uvx mcp-grafana` (officiel, PyPI) ;
      4) `npx -y @leval/mcp-grafana` (npm — log sur stdout, transport pollué :
         dernier recours).
    Le premier token est résolu via `shutil.which` : sur Windows, `npx.CMD`
    ne se lance pas par nom nu (WinError 2) mais par chemin complet.
    """
    import shlex
    import shutil

    spec = (override or os.environ.get("NODUS_GRAFANA_SERVER") or "").strip()
    if spec:
        parts = shlex.split(spec)
        if parts:
            resolved = shutil.which(parts[0]) or parts[0]
            return resolved, parts[1:]
    for name, args in (("mcp-grafana", []), ("uvx", ["mcp-grafana"]), ("npx", ["-y", "@leval/mcp-grafana"])):
        resolved = shutil.which(name)
        if resolved:
            return resolved, args
    return None


class GrafanaSink:
    """Enregistre les événements d'un run Nodus vers Grafana Cloud.

    Args:
        mode:      "mock" (défaut) | "mcp" | "off"
        url:       Grafana instance URL (ex https://my.grafana.net). En mode
                   mcp, défaut = env GRAFANA_URL.
        token:     Service account token (glsa_…). En mode mcp, défaut = env
                   GRAFANA_SERVICE_ACCOUNT_TOKEN.
        jsonl_path: En mode mock, écrire les événements aussi en JSONL.
    """

    def __init__(
        self,
        mode: str = "mock",
        url: Optional[str] = None,
        token: Optional[str] = None,
        jsonl_path: Optional[str] = None,
    ) -> None:
        self.mode = mode
        self.events: List[Dict[str, Any]] = []
        self.errors: List[str] = []
        self.pushed = 0  # annotations confirmées par Grafana (create_annotation OK)
        self._jsonl = None
        self._bridge = None  # McpBridge (import tardif — évite le coût mcp en mock)
        if jsonl_path:
            self._jsonl = Path(jsonl_path)
            self._jsonl.parent.mkdir(parents=True, exist_ok=True)

        if mode == "mcp":
            self._connect_mcp(url=url, token=token)

    # ── Connexion MCP (live) ───────────────────────────────────────────────

    def _connect_mcp(self, url: Optional[str], token: Optional[str]) -> None:
        """Démarre le serveur mcp-grafana (stdio) et l'enregistre dans le bridge."""
        url = url or os.environ.get("GRAFANA_URL", "").strip()
        token = token or os.environ.get("GRAFANA_SERVICE_ACCOUNT_TOKEN", "").strip()
        if not url or not token:
            self.errors.append(
                "mcp mode requires GRAFANA_URL and GRAFANA_SERVICE_ACCOUNT_TOKEN "
                "(set env vars or pass url=/token=). Falling back to mock."
            )
            self.mode = "mock"
            return
        try:
            from nodus_mcp_client import McpBridge
        except ImportError:
            self.errors.append("mcp package not installed (pip install mcp). Falling back to mock.")
            self.mode = "mock"
            return

        # mcp-grafana : uvx (officiel) puis npx (npm) — résolu en chemin
        # complet via shutil.which (sur Windows, npx.CMD exige le chemin).
        import tempfile
        import uuid
        import json as _json

        cmd = mcp_grafana_command()
        if cmd is None:
            self.errors.append(
                "mcp-grafana launcher not found: install uvx or node/npx, or set "
                "NODUS_GRAFANA_SERVER. Falling back to mock."
            )
            self.mode = "mock"
            return
        command, args = cmd

        server_env = {
            "GRAFANA_URL": url,
            "GRAFANA_SERVICE_ACCOUNT_TOKEN": token,
        }
        # Multi-org: mcp-grafana lit GRAFANA_ORG_ID (id numérique de l'org).
        # Sans lui, le serveur utilise org_id=0 → 503 sur les opérations.
        _org = (os.environ.get("GRAFANA_ORG_ID") or "").strip()
        if _org:
            server_env["GRAFANA_ORG_ID"] = _org
        config = {
            "mcpServers": {
                "grafana": {
                    "command": command,
                    "args": args,
                    "env": server_env,
                }
            }
        }
        cfg_dir = Path(tempfile.gettempdir()) / f"nodus_mcp_{uuid.uuid4().hex[:8]}"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        cfg_path = cfg_dir / "mcp.json"
        cfg_path.write_text(_json.dumps(config), encoding="utf-8")

        bridge = McpBridge()
        err = bridge.connect_servers(str(cfg_path), ("grafana",))
        if err:
            self.errors.append(f"grafana MCP connect failed: {err}")
            bridge.close()
            self.mode = "mock"
            return
        self._bridge = bridge
        self.mode = "mcp"

    def _resolve_tool(self, bare_name: str) -> Optional[str]:
        """Nom qualifié réel d'un outil : le serveur s'auto-nomme
        ('mcp-grafana.create_annotation'), pas la clé de config mcp.json
        ('grafana.create_annotation'). Retourne None si l'outil est absent."""
        registry = getattr(self._bridge, "registry", None)
        if registry is None:
            return None
        entries = getattr(registry, "entries", None) or {}
        exact = f"mcp-grafana.{bare_name}"
        if exact in entries:
            return exact
        suffix = "." + bare_name
        for qname in entries:
            if qname.endswith(suffix):
                return qname
        return None

    # ── API publique ───────────────────────────────────────────────────────

    def record(self, kind: str, **fields: Any) -> Optional[Dict[str, Any]]:
        """Enregistre un événement structuré. Retourne l'événement (None si off)."""
        if self.mode == "off":
            return None
        if kind not in EVENT_KINDS:
            kind = "task"  # kind inconnu → ne jamais bloquer un run
        evt: Dict[str, Any] = {"ts": _now(), "kind": kind}
        evt.update(fields)
        self.events.append(evt)
        if self._jsonl is not None:
            with self._jsonl.open("a", encoding="utf-8") as f:
                f.write(json.dumps(evt, ensure_ascii=False) + "\n")

        if self.mode == "mcp" and self._bridge is not None:
            self._push_annotation(evt)
        return evt

    def _push_annotation(self, evt: Dict[str, Any]) -> None:
        """Mode live : crée une annotation Grafana à partir d'un événement.

        Les annotations sont attachées au dashboard scope (dashboardUid+panelId)
        pour qu'elles apparaissent via la couche NATIVE "Annotations & Alerts"
        (builtIn). Sans dashboardUid, elles sont org-level et dépendent d'une
        couche tags qui ne rend pas fiablement côté frontend.
        """
        try:
            qname = self._resolve_tool("create_annotation")
            if qname is None:
                self.errors.append(
                    "create_annotation: mcp-grafana tool not registered "
                    "(server down?)"
                )
                return
            text = _annotation_text(evt)
            payload = {"text": text, "tags": _TAGS + [f"nodus:{evt['kind']}"]}
            uid = os.environ.get("NODUS_GRAFANA_DASHBOARD_UID", "nodus-agent-scope")
            payload["dashboardUid"] = uid
            payload["panelId"] = int(os.environ.get("NODUS_GRAFANA_PANEL_ID", "1"))
            result = self._bridge.call(qname, payload)
            if getattr(result, "success", None) is False:
                err = str(getattr(result, "error", "?"))
                # 429 = rate-limit (Grafana Cloud) : un seul retry court.
                if "429" in err:
                    time.sleep(1.0)
                    result = self._bridge.call(qname, payload)
                    if getattr(result, "success", None) is not False:
                        self.pushed += 1
                        return
                self.errors.append(f"create_annotation rejected: {err}")
            else:
                self.pushed += 1
        except Exception as exc:  # jamais fatal
            self.errors.append(f"create_annotation failed: {exc}")

    def search_dashboards(self, query: str = "") -> Any:
        """Mode live : liste les dashboards (read — bon pour la démo)."""
        if self.mode != "mcp" or self._bridge is None:
            return {"mode": self.mode, "error": "search_dashboards requires mcp mode"}
        qname = self._resolve_tool("search_dashboards")
        if qname is None:
            return {"mode": self.mode, "error": "search_dashboards tool not registered"}
        return self._bridge.call(qname, {"query": query})

    def dashboard_summary(self, uid: str) -> Any:
        if self.mode != "mcp" or self._bridge is None:
            return {"mode": self.mode, "error": "dashboard_summary requires mcp mode"}
        qname = self._resolve_tool("get_dashboard_summary")
        if qname is None:
            return {"mode": self.mode, "error": "dashboard_summary tool not registered"}
        return self._bridge.call(qname, {"uid": uid})

    def summary(self) -> str:
        """Vue humaine (terminal / vidéo) : timeline compacte du run."""
        lines: List[str] = []
        for evt in self.events:
            kind = evt["kind"]
            if kind == "task":
                lines.append(f"▶ task: {evt.get('task', '')[:120]}")
            elif kind == "plan":
                names = evt.get("names")
                lines.append(f"  ∘ plan [{evt.get('source', '?')}]: {names}")
            elif kind == "tool_call":
                lines.append(f"    ↳ tool {evt.get('name')} {evt.get('args', '')}")
            elif kind == "tool_result":
                ok = "✓" if evt.get("success") else "✗"
                preview = str(evt.get("output", ""))[:80].replace("\n", " ")
                lines.append(f"      {ok} {preview}")
            elif kind == "verdict":
                lines.append(f"  ! verdict: {evt.get('message', '')}")
            elif kind == "result":
                lines.append(f"● result: {evt.get('answer', '')[:120]}")
        return "\n".join(lines) if lines else "(no events)"

    def close(self) -> None:
        if self._bridge is not None:
            try:
                self._bridge.close()
            except Exception:
                pass
            self._bridge = None

    def __enter__(self) -> "GrafanaSink":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def _annotation_text(evt: Dict[str, Any]) -> str:
    """Réduit un événement à un texte d'annotation lisible."""
    kind = evt["kind"]
    if kind == "task":
        return f"task: {evt.get('task', '')[:200]}"
    if kind == "plan":
        return f"plan [{evt.get('source', '?')}]: {evt.get('names')}"
    if kind == "tool_call":
        return f"tool {evt.get('name')}: {str(evt.get('args', ''))[:120]}"
    if kind == "tool_result":
        status = "ok" if evt.get("success") else "error"
        return f"tool {evt.get('name')} → {status}: {str(evt.get('output', ''))[:100]}"
    if kind == "verdict":
        return f"verdict: {evt.get('message', '')[:200]}"
    return f"result: {str(evt.get('answer', ''))[:200]}"


def sink_from_env() -> GrafanaSink:
    """Sink piloté par l'environnement (pratique pour la démo) :
       NODUS_GRAFANA=mcp → live (GRAFANA_URL + GRAFANA_SERVICE_ACCOUNT_TOKEN) ;
       NODUS_GRAFANA=jsonl:/path → mock + JSONL ; sinon mock."""
    spec = os.environ.get("NODUS_GRAFANA", "").strip()
    if spec == "mcp":
        return GrafanaSink(mode="mcp")
    if spec.startswith("jsonl:"):
        return GrafanaSink(mode="mock", jsonl_path=spec.split(":", 1)[1])
    if spec == "off":
        return GrafanaSink(mode="off")
    return GrafanaSink(mode="mock")
