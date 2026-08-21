import asyncio
import json
import types

from fastapi import FastAPI
from fastapi.testclient import TestClient

import engine.config.settings as settings_mod
import web.api.app as app_mod

ORIGIN = "http://localhost:7843"


def test_build_cors_origins_dedup_order():
    origins = app_mod._build_cors_origins("127.0.0.1", 7843)
    assert origins == [
        "http://127.0.0.1:7843",
        "http://localhost:7843",
    ]


def test_build_allowed_hosts_frozenset_contents():
    hosts = app_mod._build_allowed_hosts("127.0.0.1", 7843)
    assert isinstance(hosts, frozenset)
    assert hosts == frozenset({
        "localhost:7843",
        "127.0.0.1:7843",
        "127.0.0.1",
        "localhost",
    })


def _fake_request(origin, cors_origins):
    headers = types.SimpleNamespace(get=lambda key, default=None: origin if key == "origin" else default)
    url = types.SimpleNamespace(path="/api/boom")
    state = types.SimpleNamespace(cors_origins=cors_origins)
    app = types.SimpleNamespace(state=state)
    return types.SimpleNamespace(method="POST", url=url, headers=headers, app=app)


def test_global_exception_handler_returns_500_body():
    request = _fake_request(None, frozenset())
    response = asyncio.run(app_mod._global_exception_handler(request, RuntimeError("boom")))
    assert response.status_code == 500
    assert json.loads(response.body) == {"erreur": "Une erreur interne est survenue.", "ok": False}


def test_global_exception_handler_no_acao_when_origin_absent():
    request = _fake_request(None, frozenset({ORIGIN}))
    response = asyncio.run(app_mod._global_exception_handler(request, ValueError("x")))
    assert "Access-Control-Allow-Origin" not in response.headers
    assert "Vary" not in response.headers


def test_global_exception_handler_no_acao_when_origin_not_allowed():
    request = _fake_request("http://evil.example.com", frozenset({ORIGIN}))
    response = asyncio.run(app_mod._global_exception_handler(request, ValueError("x")))
    assert "Access-Control-Allow-Origin" not in response.headers
    assert "Vary" not in response.headers


def test_global_exception_handler_echoes_allowed_origin():
    request = _fake_request(ORIGIN, frozenset({ORIGIN}))
    response = asyncio.run(app_mod._global_exception_handler(request, RuntimeError("boom")))
    assert response.status_code == 500
    assert response.headers["Access-Control-Allow-Origin"] == ORIGIN
    assert response.headers["Vary"] == "Origin"


def test_host_guard_rejects_unknown_host(client):
    r = client.get("/api/breakers", headers={"host": "evil.example"})
    assert r.status_code == 421
    assert r.json() == {"ok": False, "erreur": "Host non autorisé"}


def test_host_guard_post_missing_origin_and_referer_on_unrouted_path(client):
    r = client.post("/api/does-not-exist")
    assert r.status_code == 403
    assert r.json() == {"ok": False, "erreur": "En-tête Origin/Referer manquant (CSRF)"}


def test_host_guard_post_foreign_origin_on_unrouted_path(client):
    r = client.post("/api/does-not-exist", headers={"origin": "http://evil.example.com"})
    assert r.status_code == 403
    assert r.json() == {"ok": False, "erreur": "Origine non autorisée (CSRF)"}


def test_host_guard_referer_derived_origin_passes(client):
    referer = f"http://localhost:{settings_mod.PORT}/index.html"
    r = client.post("/api/does-not-exist", headers={"referer": referer})
    assert r.status_code in (404, 405)


def test_host_guard_referer_foreign_origin_blocked(client):
    r = client.post(
        "/api/does-not-exist",
        headers={"referer": "http://evil.example.com/page"},
    )
    assert r.status_code == 403
    assert r.json() == {"ok": False, "erreur": "Origine non autorisée (CSRF)"}


def _make_static_app(tmp_dir):
    (tmp_dir / "index.html").write_text("<html><body>hi</body></html>", encoding="utf-8")
    (tmp_dir / "style.css").write_text("body{color:red}", encoding="utf-8")
    (tmp_dir / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    app = FastAPI()
    app.mount("/", app_mod.CachedStaticFiles(directory=str(tmp_dir), html=True), name="static")
    return TestClient(app)


def test_cached_static_html_headers(tmp_path):
    c = _make_static_app(tmp_path)
    r = c.get("/index.html")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=60"
    assert r.headers["content-security-policy"] == app_mod.CSP
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"


def test_cached_static_css_headers(tmp_path):
    c = _make_static_app(tmp_path)
    r = c.get("/style.css")
    assert r.status_code == 200
    assert "max-age=300" in r.headers["cache-control"]
    assert "content-security-policy" not in r.headers
    assert "x-frame-options" not in r.headers
    assert r.headers["x-content-type-options"] == "nosniff"


def test_cached_static_image_headers(tmp_path):
    c = _make_static_app(tmp_path)
    r = c.get("/logo.png")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=86400, stale-while-revalidate=604800"
    assert "content-security-policy" not in r.headers
