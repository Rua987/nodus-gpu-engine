#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏛️ TEMPLE IAM - Tests anti-SSRF par redirection (nodus_tools.tool_web_fetch)
⚡ GAP : la garde _is_blocked_url ne validait QUE l'URL initiale. Avec
   allow_redirects=True, un serveur public renvoyant 30x vers
   http://169.254.169.254/ (métadonnées cloud) ou http://127.0.0.1/ était
   suivi automatiquement par requests, SANS repasser par la garde.
   Fix : allow_redirects=False + suivi manuel revalidé à chaque saut.
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import nodus_tools  # noqa: E402
from nodus_tools import tool_web_fetch, MAX_FETCH_REDIRECTS  # noqa: E402


# ---------------------------------------------------------------------------
# Faux objet réponse façon requests (streaming + redirections)
# ---------------------------------------------------------------------------
class FakeResp:
    def __init__(self, status=200, location=None, body=b"OK PUBLIC BODY"):
        self.status_code = status
        # content-type texte par défaut : sans lui, web_fetch traite le corps
        # comme binaire et le body texte n'apparaît pas dans la sortie.
        self.headers = {"content-type": "text/plain"}
        if location is not None:
            self.headers["Location"] = location
        self._body = body
        self.closed = False

    @property
    def is_redirect(self):
        return self.status_code in (301, 302, 303, 307) and "Location" in self.headers

    @property
    def is_permanent_redirect(self):
        return self.status_code in (301, 308) and "Location" in self.headers

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=8192):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]

    def close(self):
        self.closed = True


def _allow_public_dns():
    """getaddrinfo factice : tout hôte 'public' résout vers une IP publique."""
    def fake_getaddrinfo(host, *a, **k):
        # Les hôtes internes gardent leur vraie résolution via la garde ;
        # ici on force les hôtes de test publics vers une IP publique.
        if host in ("evil.example.com", "good.example.com", "hop.example.com"):
            return [(2, 1, 6, "", ("93.184.216.34", 80))]
        # 169.254.x / 127.x doivent ressembler à du loopback/link-local
        return [(2, 1, 6, "", (host, 80))]
    return fake_getaddrinfo


# ---------------------------------------------------------------------------
# 1. Un redirect vers les métadonnées cloud DOIT être bloqué
# ---------------------------------------------------------------------------
def test_redirect_to_metadata_is_blocked():
    responses = [
        FakeResp(status=302, location="http://169.254.169.254/latest/meta-data/"),
    ]

    def fake_get(url, **kwargs):
        # Sécurité du test : si le code suivait la redirection, il appellerait
        # fake_get avec l'URL métadonnées -> on le détecterait.
        assert "169.254.169.254" not in url, "garde SSRF contournée : requête métadonnées émise !"
        assert kwargs.get("allow_redirects") is False, "allow_redirects doit être False"
        return responses.pop(0)

    with patch("nodus_tools.socket.getaddrinfo", _allow_public_dns()), \
         patch("nodus_tools.requests.get", side_effect=fake_get):
        r = tool_web_fetch("http://evil.example.com/start")

    assert r.success is False
    assert "blocked redirect" in (r.error or "").lower(), r.error


# ---------------------------------------------------------------------------
# 2. Un redirect vers 127.0.0.1 DOIT être bloqué
# ---------------------------------------------------------------------------
def test_redirect_to_loopback_is_blocked():
    def fake_get(url, **kwargs):
        assert "127.0.0.1" not in url, "garde SSRF contournée : requête loopback émise !"
        return FakeResp(status=301, location="http://127.0.0.1:8080/admin")

    with patch("nodus_tools.socket.getaddrinfo", _allow_public_dns()), \
         patch("nodus_tools.requests.get", side_effect=fake_get):
        r = tool_web_fetch("http://evil.example.com/start")

    assert r.success is False
    assert "blocked redirect" in (r.error or "").lower(), r.error


# ---------------------------------------------------------------------------
# 3. Un redirect relatif vers un chemin interne malveillant est bloqué
#    (Location relative résolue puis revalidée)
# ---------------------------------------------------------------------------
def test_relative_redirect_resolved_and_revalidated():
    # 1er saut public -> 2e saut Location ABSOLUE vers metadata
    seq = [
        FakeResp(status=302, location="http://hop.example.com/next"),
        FakeResp(status=302, location="http://169.254.169.254/"),
    ]

    def fake_get(url, **kwargs):
        assert "169.254" not in url
        return seq.pop(0)

    with patch("nodus_tools.socket.getaddrinfo", _allow_public_dns()), \
         patch("nodus_tools.requests.get", side_effect=fake_get):
        r = tool_web_fetch("http://evil.example.com/start")

    assert r.success is False
    assert "blocked redirect" in (r.error or "").lower(), r.error


# ---------------------------------------------------------------------------
# 4. Trop de redirections (boucle) -> refus propre
# ---------------------------------------------------------------------------
def test_too_many_redirects():
    def fake_get(url, **kwargs):
        # boucle infinie entre hôtes publics
        return FakeResp(status=302, location="http://hop.example.com/loop")

    with patch("nodus_tools.socket.getaddrinfo", _allow_public_dns()), \
         patch("nodus_tools.requests.get", side_effect=fake_get):
        r = tool_web_fetch("http://good.example.com/start")

    assert r.success is False
    assert "too many redirects" in (r.error or "").lower(), r.error


# ---------------------------------------------------------------------------
# 5. Un redirect LÉGITIME vers un hôte public DOIT réussir (pas de faux positif)
# ---------------------------------------------------------------------------
def test_legitimate_public_redirect_succeeds():
    seq = [
        FakeResp(status=302, location="http://good.example.com/final"),
        FakeResp(status=200, body=b"FINAL PUBLIC CONTENT"),
    ]

    def fake_get(url, **kwargs):
        return seq.pop(0)

    with patch("nodus_tools.socket.getaddrinfo", _allow_public_dns()), \
         patch("nodus_tools.requests.get", side_effect=fake_get):
        r = tool_web_fetch("http://good.example.com/start")

    assert r.success is True, r.error
    assert "FINAL PUBLIC CONTENT" in r.output


# ---------------------------------------------------------------------------
# 5b. Redirect annoncé mais SANS header Location -> refus propre (cas limite)
# ---------------------------------------------------------------------------
def test_redirect_without_location_is_refused():
    def fake_get(url, **kwargs):
        return FakeResp(status=302, location="")  # is_redirect True, Location vide

    with patch("nodus_tools.socket.getaddrinfo", _allow_public_dns()), \
         patch("nodus_tools.requests.get", side_effect=fake_get):
        r = tool_web_fetch("http://good.example.com/start")

    assert r.success is False
    assert "without location" in (r.error or "").lower(), r.error


# ---------------------------------------------------------------------------
# 6. Réponse directe 200 sans redirection : comportement nominal
# ---------------------------------------------------------------------------
def test_direct_200_no_redirect():
    def fake_get(url, **kwargs):
        return FakeResp(status=200, body=b"HELLO PUBLIC")

    with patch("nodus_tools.socket.getaddrinfo", _allow_public_dns()), \
         patch("nodus_tools.requests.get", side_effect=fake_get):
        r = tool_web_fetch("http://good.example.com/page")

    assert r.success is True, r.error
    assert "HELLO PUBLIC" in r.output


def test_dns_rebind_pins_ip_literal():
    """2e résolution DNS vers loopback ne doit pas changer la cible HTTP."""
    calls = {"n": 0}

    def rebind_gai(host, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return [(2, 1, 6, "", ("93.184.216.34", 0))]
        return [(2, 1, 6, "", ("127.0.0.1", 0))]

    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["host"] = (kwargs.get("headers") or {}).get("Host")
        resp = FakeResp(status=200, body=b"PINNED OK")
        return resp

    with patch("nodus_tools.socket.getaddrinfo", side_effect=rebind_gai), \
         patch("nodus_tools.requests.get", side_effect=fake_get):
        r = tool_web_fetch("http://rebind.evil.example/secret")

    assert r.success is True, r.error
    assert calls["n"] == 1
    assert "93.184.216.34" in captured["url"]
    assert captured["host"] == "rebind.evil.example"
    assert "rebind.evil.example" not in captured["url"]


if __name__ == "__main__":
    sys.exit(__import__("pytest").main([__file__, "-v"]))
