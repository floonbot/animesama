"""Regression: a Referer without a scheme must not bypass the CSRF origin check.

Previously, when Origin was absent and Referer had no scheme, the derived origin
fell back to None and the `origin is not None and ...` guard silently ALLOWED the
unsafe write. It must be denied.
"""


def test_referer_without_scheme_is_denied(client):
    r = client.post("/api/does-not-exist", headers={"referer": "localhost/index.html"})
    assert r.status_code == 403
    assert r.json() == {"ok": False, "erreur": "Origine non autorisée (CSRF)"}


def test_referer_bare_path_is_denied(client):
    r = client.post("/api/does-not-exist", headers={"referer": "/index.html"})
    assert r.status_code == 403
    assert r.json() == {"ok": False, "erreur": "Origine non autorisée (CSRF)"}


def test_valid_scheme_referer_still_passes(client):
    from engine.config import settings as settings_mod

    referer = f"http://localhost:{settings_mod.PORT}/index.html"
    r = client.post("/api/does-not-exist", headers={"referer": referer})
    assert r.status_code in (404, 405)
