
WRITE_HEADERS = {"origin": "http://localhost:7843"}

def test_unknown_host_rejected(client):
    r = client.get("/api/health", headers={"host": "evil.example.com"})
    assert r.status_code == 421

def test_csrf_blocks_foreign_origin(client):
    r = client.post("/api/download/pause", headers={"origin": "http://evil.example.com"})
    assert r.status_code == 403

def test_csrf_allows_same_origin(client):
    r = client.post("/api/download/pause", headers={"origin": "http://localhost:7843"})
    assert r.status_code == 200

def test_csrf_blocks_missing_origin_and_referer(client):
    r = client.post("/api/download/pause")
    assert r.status_code == 403

def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["version"]

def test_download_status(client, monkeypatch):
    from engine.services.download_service import download_service
    monkeypatch.setattr(download_service, "statut",
                        lambda: {"en_cours": None, "queue": [], "historique": [], "elapsed": 0, "en_pause": False})
    r = client.get("/api/download/status")
    assert r.status_code == 200
    assert r.json()["queue"] == []

def test_download_pause_reprendre(client, monkeypatch):
    from engine.services.download_service import download_service
    monkeypatch.setattr(download_service, "pause", lambda: {"ok": True, "en_pause": True})
    monkeypatch.setattr(download_service, "reprendre", lambda: {"ok": True, "en_pause": False})
    assert client.post("/api/download/pause", headers=WRITE_HEADERS).json()["en_pause"] is True
    assert client.post("/api/download/reprendre", headers=WRITE_HEADERS).json()["en_pause"] is False

def test_download_annuler(client, monkeypatch):
    from engine.services.download_service import download_service
    monkeypatch.setattr(download_service, "annuler", lambda: {"ok": True})
    assert client.post("/api/download/annuler", headers=WRITE_HEADERS).json()["ok"] is True

def test_download_episode_valid_and_malformed(client, monkeypatch):
    async def _fake_add(item):
        return {"ok": True, "message": "ajouté"}
    from engine.services.download_service import download_service
    monkeypatch.setattr(download_service, "ajouter_episode", _fake_add)
    r = client.post("/api/download/episode", headers=WRITE_HEADERS,
                    json={"ep": {"url": "x", "titre": "t"}, "episodes": []})
    assert r.status_code == 200 and r.json()["ok"] is True
    r2 = client.post("/api/download/episode", headers=WRITE_HEADERS, json={"episodes": []})
    assert r2.status_code == 422

def test_download_direct_url_too_short(client):
    r = client.post("/api/download/direct", headers=WRITE_HEADERS,
                    json={"url": "short", "headers": {}, "nom_fichier": ""})
    assert r.status_code == 422

def test_download_direct_ok(client, monkeypatch):
    async def _fake(url, nom, headers):
        return {"ok": True}
    from engine.services.download_service import download_service
    monkeypatch.setattr(download_service, "ajouter_direct", _fake)
    r = client.post("/api/download/direct", headers=WRITE_HEADERS,
                    json={"url": "https://example.com/video.m3u8", "headers": {}, "nom_fichier": "v"})
    assert r.status_code == 200 and r.json()["ok"] is True

def test_download_deplacer(client, monkeypatch):
    from engine.download import queue as qmod
    calls = {}

    def _fake_deplacer(a, b):
        calls["args"] = (a, b)
        return True

    monkeypatch.setattr(qmod.queue, "deplacer", _fake_deplacer)
    r = client.post("/api/download/deplacer", headers=WRITE_HEADERS, json={"from": 0, "to": 2})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert calls["args"] == (0, 2)

def test_download_retirer(client, monkeypatch):
    from engine.download import queue as qmod
    monkeypatch.setattr(qmod.queue, "retirer", lambda i: i == 0)
    assert client.delete("/api/download/queue/0", headers=WRITE_HEADERS).json()["ok"] is True

def test_download_breakers(client):
    r = client.get("/api/download/breakers")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert isinstance(r.json()["breakers"], dict)

def test_download_metrics(client):
    r = client.get("/api/download/metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert isinstance(body["metrics"], dict)
    assert isinstance(body["resume"], dict)
    assert "queue_depth" in body["resume"]

def test_metrics_alias(client):
    r = client.get("/api/metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "queue_depth" in body["resume"]

def test_metrics_exposes_per_host_and_winner_fields(client):
    resume = client.get("/api/metrics").json()["resume"]
    assert "par_hote" in resume
    assert "par_hote_canonique" in resume
    assert "extraction_par_lien" in resume
    assert isinstance(resume.get("hotes_supportes"), list)
    assert "hotes_degrades" in resume
    names = {h["name"] for h in resume["hotes_supportes"]}
    assert {"sibnet", "vudeo", "doodstream"} <= names

def test_settings_get(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    assert isinstance(r.json(), dict)

def test_auth_status_reflects_state(client, monkeypatch):
    from engine.auth.manager import auth_manager
    monkeypatch.setattr(auth_manager, "_logged_in", False)
    r = client.get("/api/auth/status")
    assert r.status_code == 200
    assert r.json()["connected"] is False

def test_cover_redirects_on_miss(client, monkeypatch):
    from engine.cache import cover_images
    monkeypatch.setattr(cover_images, "cached_file", lambda u: None)
    monkeypatch.setattr(cover_images, "warm", lambda u: None)
    r = client.get("/api/anime/cover", params={"u": "https://example.com/x.jpg"},
                   follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "https://example.com/x.jpg"

def test_cover_rejects_non_http(client):
    r = client.get("/api/anime/cover", params={"u": "ftp://nope/x.jpg"}, follow_redirects=False)
    assert r.status_code == 400

def test_cover_rejects_ssrf_link_local(client):
    r = client.get("/api/anime/cover", params={"u": "http://169.254.169.254/latest/meta-data/"},
                   follow_redirects=False)
    assert r.status_code == 400

def test_stream_rejects_non_video_extension(client):
    r = client.get("/api/anime/stream", params={"fichier": "/tmp/secret.txt"})
    assert r.status_code == 400

def test_supprimer_rejects_non_media_extension(client):
    r = client.post("/api/anime/supprimer", headers=WRITE_HEADERS, json={"fichier": "/tmp/secret.txt"})
    assert r.status_code == 200 and r.json()["ok"] is False

def test_covers_get(client):
    r = client.get("/api/anime/covers")
    assert r.status_code == 200
    assert isinstance(r.json(), dict)
