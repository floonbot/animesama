from unittest.mock import Mock

WRITE_HEADERS = {"origin": "http://localhost:7843"}


def test_status_exception_returns_default_shape(client, monkeypatch):
    """A raising statut() degrades to the documented empty-status fallback, not a 500."""
    from engine.services.download_service import download_service

    monkeypatch.setattr(
        download_service, "statut", Mock(side_effect=RuntimeError("boom"))
    )

    r = client.get("/api/download/status")
    assert r.status_code == 200
    assert r.json() == {
        "en_cours": None,
        "queue": [],
        "historique": [],
        "elapsed": 0,
        "en_pause": False,
    }


def test_episode_service_exception_returns_structured_error(client, monkeypatch):
    """A raising ajouter_episode degrades to ok=False with the queue-error message."""
    from engine.services.download_service import download_service

    async def _boom(item):
        raise RuntimeError("queue down")

    monkeypatch.setattr(download_service, "ajouter_episode", _boom)

    r = client.post(
        "/api/download/episode",
        headers=WRITE_HEADERS,
        json={"ep": {"url": "u", "titre": "t"}, "episodes": []},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": False, "message": "Erreur ajout queue"}


def test_direct_forwards_url_nom_headers_in_order(client, monkeypatch):
    """The route forwards url, nom_fichier and headers positionally to ajouter_direct."""
    from engine.services.download_service import download_service

    captured = {}

    async def _add(url, nom, headers):
        captured["args"] = (url, nom, headers)
        return {"ok": True, "position": 1, "nom": nom}

    monkeypatch.setattr(download_service, "ajouter_direct", _add)

    r = client.post(
        "/api/download/direct",
        headers=WRITE_HEADERS,
        json={
            "url": "https://example.com/video.m3u8",
            "headers": {"Referer": "https://example.com"},
            "nom_fichier": "monfichier",
        },
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "position": 1, "nom": "monfichier"}
    assert captured["args"] == (
        "https://example.com/video.m3u8",
        "monfichier",
        {"Referer": "https://example.com"},
    )


def test_direct_service_ok_false_passthrough(client, monkeypatch):
    """A service refusal (ok=False) is forwarded verbatim by the direct route."""
    from engine.services.download_service import download_service

    async def _refuse(url, nom, headers):
        return {"ok": False, "message": "URL refusée (sécurité)"}

    monkeypatch.setattr(download_service, "ajouter_direct", _refuse)

    r = client.post(
        "/api/download/direct",
        headers=WRITE_HEADERS,
        json={"url": "https://10.0.0.1/internal.m3u8", "headers": {}, "nom_fichier": ""},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": False, "message": "URL refusée (sécurité)"}


def test_direct_service_exception_returns_structured_error(client, monkeypatch):
    """A raising ajouter_direct degrades to ok=False with the queue-error message."""
    from engine.services.download_service import download_service

    async def _boom(url, nom, headers):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(download_service, "ajouter_direct", _boom)

    r = client.post(
        "/api/download/direct",
        headers=WRITE_HEADERS,
        json={"url": "https://example.com/x.m3u8", "headers": {}, "nom_fichier": "v"},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": False, "message": "Erreur ajout queue"}


def test_scan_happy_path_passthrough_and_forwarded_args(client, monkeypatch):
    """A valid scan body forwards slug/oeuvre/lang/chapitres/nom and returns the service dict."""
    from engine.services.download_service import download_service

    captured = {}

    async def _add(slug, oeuvre, lang, chapitres, nom):
        captured["args"] = (slug, oeuvre, lang, chapitres, nom)
        return {"ok": True, "position": 2, "nom": nom, "total": len(chapitres)}

    monkeypatch.setattr(download_service, "ajouter_scan", _add)

    r = client.post(
        "/api/download/scan",
        headers=WRITE_HEADERS,
        json={
            "slug": "naruto",
            "oeuvre": "Naruto",
            "lang": "vf",
            "chapitres": ["1", "2", "3"],
            "nom": "Naruto Manga",
        },
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "position": 2, "nom": "Naruto Manga", "total": 3}
    assert captured["args"] == (
        "naruto",
        "Naruto",
        "vf",
        ["1", "2", "3"],
        "Naruto Manga",
    )


def test_scan_service_ok_false_passthrough(client, monkeypatch):
    """A service-level refusal (e.g. invalid slug) is forwarded verbatim."""
    from engine.services.download_service import download_service

    async def _refuse(slug, oeuvre, lang, chapitres, nom):
        return {"ok": False, "message": "Slug invalide"}

    monkeypatch.setattr(download_service, "ajouter_scan", _refuse)

    r = client.post(
        "/api/download/scan",
        headers=WRITE_HEADERS,
        json={"slug": "bad", "oeuvre": "Bad", "chapitres": ["1"]},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": False, "message": "Slug invalide"}


def test_scan_service_exception_returns_structured_error(client, monkeypatch):
    """A raising ajouter_scan degrades to ok=False with the queue-error message."""
    from engine.services.download_service import download_service

    async def _boom(slug, oeuvre, lang, chapitres, nom):
        raise RuntimeError("scan down")

    monkeypatch.setattr(download_service, "ajouter_scan", _boom)

    r = client.post(
        "/api/download/scan",
        headers=WRITE_HEADERS,
        json={"slug": "naruto", "oeuvre": "Naruto", "chapitres": ["1"]},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": False, "message": "Erreur ajout queue"}


def test_annuler_exception_returns_ok_false(client, monkeypatch):
    """A raising annuler() degrades to a bare ok=False, not a 500."""
    from engine.services.download_service import download_service

    monkeypatch.setattr(
        download_service, "annuler", Mock(side_effect=RuntimeError("boom"))
    )

    r = client.post("/api/download/annuler", headers=WRITE_HEADERS)
    assert r.status_code == 200
    assert r.json() == {"ok": False}


def test_pause_exception_returns_ok_false_en_pause_false(client, monkeypatch):
    """A raising pause() degrades to ok=False, en_pause=False."""
    from engine.services.download_service import download_service

    monkeypatch.setattr(
        download_service, "pause", Mock(side_effect=RuntimeError("boom"))
    )

    r = client.post("/api/download/pause", headers=WRITE_HEADERS)
    assert r.status_code == 200
    assert r.json() == {"ok": False, "en_pause": False}


def test_reprendre_exception_returns_ok_false_en_pause_false(client, monkeypatch):
    """A raising reprendre() degrades to ok=False, en_pause=False."""
    from engine.services.download_service import download_service

    monkeypatch.setattr(
        download_service, "reprendre", Mock(side_effect=RuntimeError("boom"))
    )

    r = client.post("/api/download/reprendre", headers=WRITE_HEADERS)
    assert r.status_code == 200
    assert r.json() == {"ok": False, "en_pause": False}


def test_retirer_maps_false_result(client, monkeypatch):
    """queue.retirer returning False is mapped to ok=False by the route."""
    from engine.download import queue as qmod

    monkeypatch.setattr(qmod.queue, "retirer", lambda i: False)

    r = client.delete("/api/download/queue/3", headers=WRITE_HEADERS)
    assert r.status_code == 200
    assert r.json() == {"ok": False}


def test_retirer_exception_returns_ok_false(client, monkeypatch):
    """A raising queue.retirer degrades to ok=False, not a 500."""
    from engine.download import queue as qmod

    def _boom(_i):
        raise RuntimeError("locked")

    monkeypatch.setattr(qmod.queue, "retirer", _boom)

    r = client.delete("/api/download/queue/0", headers=WRITE_HEADERS)
    assert r.status_code == 200
    assert r.json() == {"ok": False}


def test_deplacer_default_from_alias_and_to(client, monkeypatch):
    """An empty deplacer body uses the from/to defaults (0, 0) and forwards them."""
    from engine.download import queue as qmod

    calls = {}

    def _dep(a, b):
        calls["args"] = (a, b)
        return True

    monkeypatch.setattr(qmod.queue, "deplacer", _dep)

    r = client.post("/api/download/deplacer", headers=WRITE_HEADERS, json={})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert calls["args"] == (0, 0)


def test_deplacer_maps_false_result(client, monkeypatch):
    """queue.deplacer returning False is mapped to ok=False by the route."""
    from engine.download import queue as qmod

    monkeypatch.setattr(qmod.queue, "deplacer", lambda a, b: False)

    r = client.post(
        "/api/download/deplacer", headers=WRITE_HEADERS, json={"from": 1, "to": 5}
    )
    assert r.status_code == 200
    assert r.json() == {"ok": False}


def test_deplacer_exception_returns_ok_false(client, monkeypatch):
    """A raising queue.deplacer degrades to ok=False, not a 500."""
    from engine.download import queue as qmod

    def _boom(_a, _b):
        raise RuntimeError("boom")

    monkeypatch.setattr(qmod.queue, "deplacer", _boom)

    r = client.post(
        "/api/download/deplacer", headers=WRITE_HEADERS, json={"from": 0, "to": 1}
    )
    assert r.status_code == 200
    assert r.json() == {"ok": False}


def test_breakers_reports_etat(client, monkeypatch):
    """The breakers route exposes the etat_breakers mapping under ok=True."""
    from engine.download import _host_breakers as hb

    monkeypatch.setattr(hb, "etat_breakers", lambda: {"cdn.example": "open"})

    r = client.get("/api/download/breakers")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "breakers": {"cdn.example": "open"}}


def test_breakers_exception_returns_empty(client, monkeypatch):
    """A raising etat_breakers degrades to ok=False with an empty breakers map."""
    from engine.download import _host_breakers as hb

    monkeypatch.setattr(hb, "etat_breakers", Mock(side_effect=RuntimeError("boom")))

    r = client.get("/api/download/breakers")
    assert r.status_code == 200
    assert r.json() == {"ok": False, "breakers": {}}


def test_metrics_includes_queue_depth_from_queue(client, monkeypatch):
    """The metrics route augments resume with queue_depth taken from the queue statut."""
    from engine.download import queue as qmod
    from engine.observability import metrics as metrics_mod

    monkeypatch.setattr(metrics_mod.metrics, "snapshot", lambda: {"items_termines": 7})
    monkeypatch.setattr(
        metrics_mod.metrics, "resume_detaille", lambda *a, **k: {"telechargements": 7}
    )
    monkeypatch.setattr(
        qmod.queue, "statut", lambda: {"queue": [{"a": 1}, {"b": 2}, {"c": 3}]}
    )

    r = client.get("/api/download/metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["metrics"] == {"items_termines": 7}
    assert body["resume"]["telechargements"] == 7
    assert body["resume"]["queue_depth"] == 3


def test_metrics_includes_gauges(client, monkeypatch):
    """The metrics route exposes the gauges map for the diagnostic dashboard."""
    from engine.observability import metrics as metrics_mod

    monkeypatch.setattr(
        metrics_mod.metrics, "gauges", lambda: {"sse_clients": 2, "queue_depth_max": 5}
    )
    r = client.get("/api/download/metrics")
    assert r.status_code == 200
    assert r.json()["gauges"] == {"sse_clients": 2, "queue_depth_max": 5}


def test_metrics_queue_depth_fallback_on_queue_error(client, monkeypatch):
    """If the queue statut raises, metrics still returns ok=True without queue_depth."""
    from engine.download import queue as qmod
    from engine.observability import metrics as metrics_mod

    monkeypatch.setattr(metrics_mod.metrics, "snapshot", lambda: {})
    monkeypatch.setattr(metrics_mod.metrics, "resume_detaille", lambda *a, **k: {"telechargements": 0})
    monkeypatch.setattr(
        qmod.queue, "statut", Mock(side_effect=RuntimeError("queue broken"))
    )

    r = client.get("/api/download/metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "queue_depth" not in body["resume"]


def test_metrics_exception_returns_empty(client, monkeypatch):
    """A raising resume_detaille degrades to ok=False with an empty metrics map."""
    from engine.observability import metrics as metrics_mod

    monkeypatch.setattr(
        metrics_mod.metrics,
        "resume_detaille",
        Mock(side_effect=RuntimeError("boom")),
    )

    r = client.get("/api/download/metrics")
    assert r.status_code == 200
    assert r.json() == {"ok": False, "metrics": {}}
