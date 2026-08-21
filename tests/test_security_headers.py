import zipfile

import web.api.app as app_mod


def test_media_bytes_response_has_nosniff(client, monkeypatch, tmp_path):
    from engine.library import scanner

    cbz = tmp_path / "chap.cbz"
    with zipfile.ZipFile(cbz, "w") as zf:
        zf.writestr("page1.png", b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(scanner, "est_dans_downloads", lambda f: True)

    r = client.get("/api/anime/scan-local-img", params={"fichier": str(cbz), "page": 0})
    assert r.status_code == 200
    assert r.headers.get("x-content-type-options") == "nosniff"


def test_api_json_response_has_nosniff_and_referrer_policy(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("referrer-policy") == "no-referrer"


def test_host_denied_response_also_carries_security_headers(client):
    r = client.get("/api/health", headers={"host": "evil.example"})
    assert r.status_code == 421
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("referrer-policy") == "no-referrer"


def test_static_html_keeps_csp_and_security_headers(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers.get("content-security-policy") == app_mod.CSP
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("referrer-policy") == "no-referrer"


def test_csp_style_src_has_no_unsafe_inline():
    assert "style-src 'self'" in app_mod.CSP
    assert "'unsafe-inline'" not in app_mod.CSP


def test_served_html_has_no_inline_style_block(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "<style" not in r.text.lower()
