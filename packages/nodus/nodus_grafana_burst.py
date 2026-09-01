#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
⚡ NODUS — burst d'annotations Grafana (test visuel live)
=========================================================
Pousse un mini-run complet (task → plan → tool_calls → tool_result → verdict
→ result) sur Grafana Cloud en annotations, via le serveur MCP officiel
`mcp-grafana`, puis relit les annotations pour vérification.

Usage :
    python nodus_grafana_burst.py
    python nodus_grafana_burst.py --uid <dashboard-uid>   # réutiliser un dash

Credentials lues depuis .env.grafana (gitignoré) :
    GRAFANA_URL=...
    GRAFANA_SERVICE_ACCOUNT_TOKEN=glsa_...

À l'issue, le script affiche l'URL du dashboard créé à ouvrir dans le
navigateur : les annotations taggées `nodus` s'y affichent comme des marqueurs
sur la timeline.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, List

_HERE = Path(__file__).resolve().parent
_ENV_FILE = _HERE / ".env.grafana"


def _load_env_file(path: Path) -> Dict[str, str]:
    """Lit un fichier KEY=VALUE simple (ignore # et lignes vides)."""
    env: Dict[str, str] = {}
    if not path.is_file():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        env[key.strip()] = val.strip()
    return env


def _mcp_ready() -> bool:
    """Le launcher mcp-grafana est-il disponible ?"""
    from nodus_grafana import mcp_grafana_command
    return mcp_grafana_command() is not None


_RATE_LIMIT_SLEEP_S = 0.4  # Grafana Cloud limite ~par seconde ; espace les appels.


def _burst_events(sink, delay_s: float = _RATE_LIMIT_SLEEP_S) -> List[str]:
    """Mini-run complet → annotations (espacées pour éviter le 429 rate-limit).
    Retourne la liste des texts poussés."""
    import time

    texts: List[str] = []
    events = [
        ("task", dict(task="Refactor le module de cache pour utiliser l'atomicité")),
        ("plan", dict(source="nodus", names=["read_file", "edit_file", "glob"])),
        ("tool_call", dict(name="read_file", args={"file_path": "cache.py"})),
        ("tool_result", dict(name="read_file", success=True, output="class Cache: ...")),
        ("tool_call", dict(name="edit_file", args={"file_path": "cache.py"})),
        ("tool_result", dict(name="edit_file", success=True, output="patched atomicity")),
        ("verdict", dict(message="fichier vérifié : contient atomic_rename")),
        ("result", dict(answer="Cache refactoré (atomic), 2 fichiers touchés")),
    ]
    for kind, fields in events:
        sink.record(kind, **fields)
        if delay_s > 0:
            time.sleep(delay_s)
    return sink.events


def _dashboard_json(uid: str, panel_id: int = 1) -> dict:
    """Dashboard minimal : un panel timeline qui affiche les annotations taggées nodus.

    Le datasource des annotations NATIVES est {"type":"grafana","uid":"-- Grafana --"}
    (PAS {"type":"datasource","uid":"grafana"} — ref inexistante, couche muette).
    Les annotations sont org-level (créées par create_annotation sans dashboardUid)
    → affichées par une couche dashboard `type:"tags"` (query "nodus").
    """
    return {
        "dashboard": {
            "title": "NODUS — Agent scope (demo)",
            "uid": uid,
            "tags": ["nodus", "agentic-cinema"],
            "schemaVersion": 39,
            "version": 0,
            "time": {"from": "now-1h", "to": "now"},
            "timezone": "utc",
            "refresh": "5s",
            # Annotation layers au niveau DASHBOARD (pas panel) — la couche
            # tags "nodus" affiche les annotations org-level taggées nodus.
            "annotations": {
                "list": [
                    {
                        "builtIn": 1,
                        "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                        "enable": True,
                        "hide": True,
                        "iconColor": "rgba(0, 211, 255, 1)",
                        "name": "Annotations & Alerts",
                        "type": "dashboard",
                    },
                    {
                        "name": "NODUS events",
                        "enable": True,
                        "hide": False,
                        "iconColor": "purple",
                        "type": "tags",
                        "query": "nodus",
                        "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                    },
                ]
            },
            "panels": [
                {
                    "id": panel_id,
                    "type": "timeseries",
                    "title": "Run NODUS — timeline des événements",
                    "gridPos": {"h": 10, "w": 24, "x": 0, "y": 0},
                    "datasource": {"type": "prometheus", "uid": "grafanacloud-prom"},
                    "fieldConfig": {"defaults": {}, "overrides": []},
                    "options": {"legend": {"displayMode": "list", "placement": "bottom"}},
                    "targets": [{"refId": "A", "expr": "vector(0)", "legendFormat": "baseline"}],
                }
            ],
        },
        "overwrite": True,
    }


def _create_scope_dashboard(sink, uid: str) -> str:
    """Crée/écrase le dashboard scope via l'API Grafana. Retourne son URL."""
    url = os.environ.get("GRAFANA_URL", "").strip().rstrip("/")
    body = {"dashboard": _dashboard_json(uid)["dashboard"], "overwrite": True}
    qname = "mcp-grafana.grafana_api_request"
    res = sink._bridge.call(
        qname,
        {"method": "POST", "endpoint": "/api/dashboards/db", "body": __import__("json").dumps(body)},
    )
    # res est le JSON du dashboard : {status, slug, uid, url, ...}
    url = url or "https://<stack>.grafana.net"
    if isinstance(res, dict) and res.get("url"):
        return f"{url}{res['url']}"
    return f"{url}/d/{uid}"


def main(argv: List[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    import argparse
    p = argparse.ArgumentParser(description="Burst d'annotations Grafana (test visuel live)")
    p.add_argument("--uid", default="nodus-agent-scope", help="UID du dashboard scope")
    args = p.parse_args(argv)

    env = _load_env_file(_ENV_FILE)
    url = env.get("GRAFANA_URL", "").strip()
    token = env.get("GRAFANA_SERVICE_ACCOUNT_TOKEN", "").strip()
    if not url or not token:
        print("❌ .env.grafana incomplet (ou absent).")
        print(f"   Remplis GRAFANA_URL et GRAFANA_SERVICE_ACCOUNT_TOKEN dans :")
        print(f"   {_ENV_FILE}")
        return 1

    if not _mcp_ready():
        print("❌ Launcher mcp-grafana introuvable (pip install mcp-grafana ou set NODUS_GRAFANA_SERVER).")
        return 1

    # Les env vars doivent être visibles du sink qui lit os.environ en fallback.
    os.environ.setdefault("GRAFANA_URL", url)
    os.environ.setdefault("GRAFANA_SERVICE_ACCOUNT_TOKEN", token)

    from nodus_grafana import GrafanaSink

    sink = GrafanaSink(mode="mcp", url=url, token=token)
    if sink.mode != "mcp":
        print("❌ Connexion MCP échouée (fallback mock). Erreurs du sink :")
        for e in sink.errors:
            print(f"   - {e}")
        return 1
    print(f"✅ Connecté à {url} via mcp-grafana")

    _burst_events(sink)
    print(f"✅ {len(sink.events)} événements poussés en annotations")

    # Dashboard scope → visuel dans le navigateur
    try:
        dash_url = _create_scope_dashboard(sink, args.uid)
        print(f"✅ Dashboard scope OK : {dash_url}")
    except Exception as exc:
        print(f"⚠️ Dashboard scope non créé ({exc}) — annotations quand même sur le stack.")

    # Relecture des annotations pour prouver l'aller-retour
    try:
        res = sink._bridge.call(
            "mcp-grafana.get_annotations",
            {"tags": ["nodus"], "matchAny": True, "limit": 50},
        )
        print(f"✅ get_annotations(tags=[nodus]) → {res}")
    except Exception as exc:
        print(f"⚠️ get_annotations failed: {exc}")

    sink.close()
    print(f"\n🌐 Ouvre le dashboard dans ton navigateur : {dash_url if 'dash_url' in dir() else url}")
    print("   (time range = last 15 min — les annotations y sont des marqueurs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
