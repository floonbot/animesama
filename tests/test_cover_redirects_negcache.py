import http.server
import threading
import time

import pytest

import engine.cache.cover_images as ci

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00"
    b"\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class _Handler(http.server.BaseHTTPRequestHandler):
    plan: dict = {}
    hits: list = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        _Handler.hits.append(self.path)
        action = _Handler.plan.get(self.path, ("html", None))
        genre, cible = action
        if genre == "redirect":
            self.send_response(302)
            self.send_header("Location", cible)
            self.end_headers()
        elif genre == "image":
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(_PNG)))
            self.end_headers()
            self.wfile.write(_PNG)
        else:
            corps = b"<html>nope</html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(corps)))
            self.end_headers()
            self.wfile.write(corps)


@pytest.fixture
def serveur(monkeypatch, tmp_path):
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    _Handler.plan = {}
    _Handler.hits = []

    monkeypatch.setattr(ci, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(ci, "is_safe_url", lambda _u: True)
    monkeypatch.setattr(ci, "pin_target", lambda _u: ("127.0.0.1", "127.0.0.1"))
    ci.vider_cache_negatif()
    with ci._inflight_lock:
        ci._inflight.clear()

    base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield base
    srv.shutdown()
    srv.server_close()
    ci.vider_cache_negatif()


def test_redirection_vers_une_vraie_image_est_mise_en_cache(serveur):
    _Handler.plan = {"/a.jpg": ("redirect", f"{serveur}/vraie.png"), "/vraie.png": ("image", None)}

    chemin = ci.fetch_and_store(f"{serveur}/a.jpg")

    assert chemin is not None
    assert chemin.exists()
    assert chemin.read_bytes()[:8] == _PNG[:8]
    assert _Handler.hits == ["/a.jpg", "/vraie.png"]


def test_deux_redirections_maximum(serveur):
    _Handler.plan = {
        "/1": ("redirect", f"{serveur}/2"),
        "/2": ("redirect", f"{serveur}/3"),
        "/3": ("redirect", f"{serveur}/4"),
        "/4": ("image", None),
    }

    chemin = ci.fetch_and_store(f"{serveur}/1")

    assert chemin is None
    assert _Handler.hits == ["/1", "/2", "/3"]


def test_cache_negatif_un_seul_fetch_pour_trois_warm(serveur):
    _Handler.plan = {"/html": ("html", None)}
    url = f"{serveur}/html"

    for _ in range(3):
        ci.warm(url)
        ci._executor_attendre()

    assert _Handler.hits == ["/html"]


def test_redirection_vers_ip_privee_refusee_et_memorisee(serveur, monkeypatch):
    _Handler.plan = {"/piege": ("redirect", "http://169.254.169.254/latest/meta-data")}
    autorises = []

    def _faux_safe(u):
        autorises.append(u)
        return "169.254" not in u

    monkeypatch.setattr(ci, "is_safe_url", _faux_safe)
    url = f"{serveur}/piege"

    assert ci.fetch_and_store(url) is None
    assert any("169.254" in u for u in autorises)
    assert ci._est_en_echec(url)


def test_echec_expire_apres_le_ttl(serveur, monkeypatch):
    _Handler.plan = {"/html": ("html", None)}
    url = f"{serveur}/html"

    ci.fetch_and_store(url)
    assert ci._est_en_echec(url)

    plus_tard = time.time() + ci.NEG_TTL + 1
    monkeypatch.setattr(ci.time, "time", lambda: plus_tard)
    assert not ci._est_en_echec(url)


def test_cache_negatif_borne(serveur, monkeypatch):
    monkeypatch.setattr(ci, "NEG_MAX", 10)
    for i in range(40):
        ci._marquer_echec(f"http://exemple.test/{i}")

    assert len(ci._echecs) <= 40
    assert ci._est_en_echec("http://exemple.test/39")


def test_shutdown_vide_le_cache_negatif(serveur):
    ci._marquer_echec("http://exemple.test/x")
    assert ci._echecs

    ci.vider_cache_negatif()

    assert not ci._echecs
