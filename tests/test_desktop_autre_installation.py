"""`python desktop.py` ne se branche plus sur une autre installation.

Le port 7843 est commun aux sources, au dossier de build et a l'application
installee — qui se lance au demarrage de Windows si l'option est cochee. Quand
le port etait pris, la fenetre des sources s'ouvrait sans un mot sur le serveur
installe : on croyait tester son code, on regardait l'ancien paquet. Meme garde
que tests-e2e/garde-serveur.js : on refuse de montrer un autre code que le sien.
Une seconde fenetre de la meme installation, elle, se branche comme avant.
"""

import functools
import http.server
import json
import sys
import threading

import pytest

import desktop
from engine.auth import storage
from engine.version import empreinte_installation


class _Webview:
    def __init__(self):
        self.fenetres: list[dict] = []
        self.demarre = False

    def create_window(self, *a, **k):
        self.fenetres.append({"args": a, **k})
        return object()

    def start(self, *a, **k):
        self.demarre = True


@pytest.fixture
def lancement(monkeypatch):
    wv = _Webview()
    monkeypatch.setitem(sys.modules, "webview", wv)
    monkeypatch.setattr(desktop.server, "wait_for_server", lambda *a, **k: True)
    monkeypatch.setattr(desktop.server, "start_server", lambda *a, **k: pytest.fail("serveur relance"))

    def lancer(installation_en_ecoute: str) -> _Webview:
        monkeypatch.setattr(desktop.server, "installation_en_ecoute", lambda *a, **k: installation_en_ecoute)
        desktop.main()
        return wv

    return lancer


def test_meme_installation_la_fenetre_se_branche(lancement):
    wv = lancement(empreinte_installation())

    assert len(wv.fenetres) == 1
    assert wv.fenetres[0]["args"][1].startswith("http://127.0.0.1:")
    assert "html" not in wv.fenetres[0]
    assert wv.demarre


@pytest.mark.parametrize("autre", ["0123456789ab", ""], ids=["autre-installation", "inconnue"])
def test_autre_installation_ou_inconnue_la_fenetre_refuse_et_l_explique(lancement, autre):
    wv = lancement(autre)

    assert len(wv.fenetres) == 1
    page = wv.fenetres[0]["html"]
    assert "port" in page and "PORT" in page
    assert wv.demarre


def test_la_sante_expose_l_empreinte_de_l_installation(client):
    build = client.get("/api/health").json()["build"]

    assert build["installation"] == empreinte_installation()


def test_l_empreinte_est_celle_du_trousseau():
    # Changer son calcul rendrait illisible le cookies.enc deja sur disque.
    assert storage._empreinte_installation() == empreinte_installation()


class _Sante(http.server.BaseHTTPRequestHandler):
    reponse = b""

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(self.reponse)

    def log_message(self, *a):
        pass


@pytest.mark.parametrize(
    ("reponse", "attendu"),
    [
        (json.dumps({"build": {"installation": "abcdef012345"}}).encode(), "abcdef012345"),
        (json.dumps({"build": {"version": "2.0.0"}}).encode(), ""),
        (b"<html>autre programme</html>", ""),
    ],
    ids=["meme-champ", "version-d-avant", "autre-programme"],
)
def test_installation_en_ecoute_lit_la_sante_du_serveur(monkeypatch, reponse, attendu):
    import engine.config.settings as settings

    gestionnaire = type("H", (_Sante,), {"reponse": reponse})
    serveur = http.server.HTTPServer(("127.0.0.1", 0), functools.partial(gestionnaire))
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    monkeypatch.setattr(settings, "PORT", serveur.server_address[1])
    try:
        assert desktop.server.installation_en_ecoute() == attendu
    finally:
        serveur.shutdown()


def test_installation_en_ecoute_sans_serveur(monkeypatch):
    import socket

    import engine.config.settings as settings

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    libre = s.getsockname()[1]
    s.close()
    monkeypatch.setattr(settings, "PORT", libre)

    assert desktop.server.installation_en_ecoute(timeout=0.5) == ""
