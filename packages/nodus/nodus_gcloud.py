#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
☁️ NODUS — Google Cloud Storage delivery sink
⚡ Livre les artefacts produits par un run (ex: shoot-day brief) vers
   Google Cloud Storage via le SDK officiel `google-cloud-storage`.

Deux modes :
  - mock (défaut) : aucune creds requise, uploads déterministes collectés en
    mémoire + JSONL (`gs://{bucket}/{destination}` simulé, testé hors-ligne).
  - real (live)   : import tardif `google.cloud.storage`, bucket résolu depuis
    GCLOUD_BUCKET, authentification ADC (`GOOGLE_APPLICATION_CREDENTIALS`).
    Tout défaut (SDK absent, creds/bucket manquants, réseau) retombe sur le
    mode mock avec un message dans `errors` — JAMAIS fatal (pattern Grafana).

Le planificateur Nodus garde son vocabulaire de 8 outils natifs ; `gcs_upload`
est un *capability tool* du harnais (comme l'observabilité Grafana) : livrer le
produit final. Aucun échec cloud ne casse jamais un run.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Kind d'événements d'un upload GCS (une ligne JSON chacun).
GCS_EVENT_KINDS = ("upload",)


def _now() -> str:
    """Horodatage ISO-8601 UTC."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _bytes_of(path: Optional[str], content: Optional[str]) -> Tuple[Optional[str], int, Optional[str]]:
    """Résout le contenu à uploader vers un fichier local + sa taille.

    Retourne (local_path, size, error). Si `content` est fourni, écrit un
    fichier temporaire (jamais de faux chemin). Si `local_path` est fourni,
    vérifie que le fichier existe. Fonction quasi-pure (tempfile).
    """
    if content is not None:
        if not isinstance(content, str) or not content.strip():
            return None, 0, "gcs_upload: content must be a non-empty string"
        fd, tmp = tempfile.mkstemp(suffix=".upload", prefix="nodus_gcs_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as exc:
            return None, 0, f"gcs_upload: cannot write temp file: {exc}"
        return tmp, len(content.encode("utf-8")), None
    if not path:
        return None, 0, "gcs_upload: provide 'local_path' or 'content'"
    try:
        size = Path(path).stat().st_size
    except OSError as exc:
        return None, 0, f"gcs_upload: cannot read {path!r}: {exc}"
    if not size:
        return None, 0, f"gcs_upload: {path!r} is empty"
    return path, size, None


class GcsClient:
    """Livre les artefacts d'un run Nodus vers Google Cloud Storage.

    Args:
        mode:       "mock" (défaut) | "real" | "off"
        bucket:     Nom du bucket (défaut : env GCLOUD_BUCKET).
        jsonl_path: En mode mock, écrire les événements aussi en JSONL.

    En mode "real", creds via ADC (`GOOGLE_APPLICATION_CREDENTIALS` ou
    `gcloud auth`) + `GCLOUD_BUCKET`. Sans eux → fallback mock + erreur.
    """

    def __init__(
        self,
        mode: str = "mock",
        bucket: Optional[str] = None,
        jsonl_path: Optional[str] = None,
    ) -> None:
        self.mode = mode
        self.bucket = (bucket or os.environ.get("GCLOUD_BUCKET", "")).strip()
        self.events: List[Dict[str, Any]] = []
        self.errors: List[str] = []
        self._jsonl = None
        self._client = None  # google.cloud.storage.Client — import tardif
        if jsonl_path:
            self._jsonl = Path(jsonl_path)
            self._jsonl.parent.mkdir(parents=True, exist_ok=True)

        if mode == "real":
            self._connect_real()

    # ── Connexion (live) ───────────────────────────────────────────────────

    def _connect_real(self) -> None:
        """Vérifie bucket + creds ADC, initialise le client (sinon → mock)."""
        if not self.bucket:
            self.errors.append(
                "real mode requires GCLOUD_BUCKET (set env var or pass bucket=). "
                "Falling back to mock."
            )
            self.mode = "mock"
            return
        if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip():
            self.errors.append(
                "real mode requires GOOGLE_APPLICATION_CREDENTIALS "
                "(service-account JSON) or `gcloud auth application-default login`. "
                "Falling back to mock."
            )
            self.mode = "mock"
            return
        try:
            from google.cloud import storage

            client = storage.Client()
            client.get_bucket(self.bucket)  # valide l'accès réel
            self._client = client
            self.mode = "real"
        except Exception as exc:
            self.errors.append(
                f"google-cloud-storage init failed: {exc}. Falling back to mock."
            )
            self._client = None
            self.mode = "mock"

    # ── API publique ───────────────────────────────────────────────────────

    def upload(
        self,
        local_path: Optional[str] = None,
        destination: Optional[str] = None,
        bucket: Optional[str] = None,
        content: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Upload un artefact vers Google Cloud Storage.

        Args:
            local_path:  Fichier local à uploader (chemin ancré par le harnais).
            destination: Chemin objet dans le bucket (ex "production/brief.md").
            bucket:      Bucket cible (défaut : self.bucket).
            content:     Alternative à local_path : écrire ce texte puis uploader.

        Returns:
            (success, output). Ne lève JAMAIS pour une panne d'infra — le harnais
            enregistre l'échec et continue (pattern Grafana).

        Examples:
            >>> client = GcsClient(mode="mock", bucket="nodus-media-demo")
            >>> ok, out = client.upload(destination="production/brief.md", content="hello")
            >>> ok and "gs://nodus-media-demo/production/brief.md" in out
            True
        """
        if self.mode == "off":
            return False, "(gcs off)"
        if not destination:
            return False, "gcs_upload: missing 'destination' (object path in the bucket)"
        bucket = bucket or self.bucket
        if not bucket:
            return False, "gcs_upload: no bucket (set GCLOUD_BUCKET or pass bucket=)"

        local, size, err = _bytes_of(local_path, content)
        if err:
            return False, err

        destination = destination.lstrip("/")
        gs_uri = f"gs://{bucket}/{destination}"
        self.record("upload", destination=destination, bucket=bucket,
                    size=size, mode=self.mode)

        if self.mode == "real" and self._client is not None:
            try:
                blob = self._client.bucket(bucket).blob(destination)
                blob.upload_from_filename(local, timeout=120)
                output = f"{gs_uri} ({size} bytes) [real]"
            except Exception as exc:  # jamais fatal
                self.errors.append(f"gcs_upload failed: {exc}")
                return False, f"gcs_upload failed: {exc}"
        else:
            output = f"{gs_uri} ({size} bytes) [mock]"
        if content is not None and local:
            try:
                Path(local).unlink(missing_ok=True)  # temp file
            except OSError:
                pass
        return True, output

    def record(self, kind: str, **fields: Any) -> Optional[Dict[str, Any]]:
        """Enregistre un événement d'upload structuré (None si off)."""
        if self.mode == "off":
            return None
        if kind not in GCS_EVENT_KINDS:
            kind = "upload"  # kind inconnu → ne jamais bloquer un run
        evt: Dict[str, Any] = {"ts": _now(), "kind": kind}
        evt.update(fields)
        self.events.append(evt)
        if self._jsonl is not None:
            with self._jsonl.open("a", encoding="utf-8") as f:
                f.write(json.dumps(evt, ensure_ascii=False) + "\n")
        return evt

    def summary(self) -> str:
        """Vue humaine (terminal / vidéo) : timeline des uploads."""
        lines: List[str] = []
        for evt in self.events:
            if evt["kind"] == "upload":
                lines.append(
                    f"  ⬆ upload {evt.get('destination')} -> "
                    f"gs://{evt.get('bucket')}/{evt.get('destination')} "
                    f"({evt.get('size', 0)} bytes) [{evt.get('mode')}]"
                )
        return "\n".join(lines) if lines else "(no uploads)"

    def close(self) -> None:
        # Le client storage n'expose pas de close() explicite ; on libère la ref.
        self._client = None

    def __enter__(self) -> "GcsClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def gcs_from_env() -> GcsClient:
    """Client piloté par l'environnement (pratique pour la démo) :
       NODUS_GCLOUD=real → live (GCLOUD_BUCKET + GOOGLE_APPLICATION_CREDENTIALS) ;
       NODUS_GCLOUD=jsonl:/path → mock + JSONL ; sinon mock."""
    spec = os.environ.get("NODUS_GCLOUD", "").strip()
    if spec == "real":
        return GcsClient(mode="real")
    if spec.startswith("jsonl:"):
        return GcsClient(mode="mock", jsonl_path=spec.split(":", 1)[1])
    if spec == "off":
        return GcsClient(mode="off")
    return GcsClient(mode="mock")
