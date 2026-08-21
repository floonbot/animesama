"""Regression: the check-updates and coherence-librairie routes had no exception
guard (unlike the rest of the API), so an engine error surfaced as a 500. They
now return a graceful default with erreur=True.
"""


def test_check_updates_returns_graceful_default_on_error(client, monkeypatch):
    import web.api.routes.anime.updates as updates_route

    async def _boom(refresh=False):
        raise RuntimeError("engine down")

    monkeypatch.setattr(updates_route, "check_updates_async", _boom)
    r = client.get("/api/anime/check-updates")
    assert r.status_code == 200
    body = r.json()
    assert body["erreur"] is True
    assert body["animes"] == []


def test_coherence_returns_graceful_default_on_error(client, monkeypatch):
    import web.api.routes.anime.updates as updates_route

    async def _boom():
        raise RuntimeError("engine down")

    monkeypatch.setattr(updates_route, "verifier_coherence_librairie", _boom)
    r = client.get("/api/anime/coherence-librairie")
    assert r.status_code == 200
    body = r.json()
    assert body["erreur"] is True
    assert body["incoherents"] == []
