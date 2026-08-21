from unittest.mock import Mock

import pytest

WRITE_HEADERS = {"origin": "http://localhost:7843"}


@pytest.fixture(autouse=True)
def _isole_covers_cache():
    from engine.cache import covers as covers_mod

    with covers_mod._covers_lock_thread:
        snapshot = dict(covers_mod._covers_cache)
        covers_mod._covers_cache.clear()
    yield covers_mod._covers_cache
    with covers_mod._covers_lock_thread:
        covers_mod._covers_cache.clear()
        covers_mod._covers_cache.update(snapshot)


def test_get_favoris_no_refresh_passes_through(client, monkeypatch):
    """Without refresh the favorites list is returned and the cache is not invalidated."""
    from engine.scraping import scraper

    invalidate = Mock()

    async def _fav(force_refresh=False):
        assert force_refresh is False
        return [{"titre": "A"}, {"titre": "B"}]

    monkeypatch.setattr(scraper, "get_favorites_async", _fav, raising=False)
    monkeypatch.setattr(scraper, "invalidate_fav_cache", invalidate, raising=False)

    r = client.get("/api/anime/favoris")
    assert r.status_code == 200
    assert r.json() == {"animes": [{"titre": "A"}, {"titre": "B"}]}
    invalidate.assert_not_called()


def test_get_favoris_refresh_invalidates_then_forces(client, monkeypatch):
    """refresh=true awaits invalidate_fav_cache and forwards force_refresh=True."""
    from engine.scraping import scraper

    ordre = []

    async def _invalidate():
        ordre.append("invalidate")

    async def _fav(force_refresh=False):
        ordre.append(("fav", force_refresh))
        return []

    monkeypatch.setattr(scraper, "invalidate_fav_cache", _invalidate, raising=False)
    monkeypatch.setattr(scraper, "get_favorites_async", _fav, raising=False)

    r = client.get("/api/anime/favoris", params={"refresh": "true"})
    assert r.status_code == 200
    assert r.json() == {"animes": []}
    assert ordre == ["invalidate", ("fav", True)]


def test_get_favoris_none_result_becomes_empty_list(client, monkeypatch):
    """A None result from the backend is normalised to an empty list."""
    from engine.scraping import scraper

    async def _fav(force_refresh=False):
        return None

    monkeypatch.setattr(scraper, "get_favorites_async", _fav, raising=False)

    r = client.get("/api/anime/favoris")
    assert r.status_code == 200
    assert r.json() == {"animes": []}


def test_get_favoris_exception_fallback(client, monkeypatch):
    """A raising backend degrades to an empty animes list, not a 500."""
    from engine.scraping import scraper

    async def _boom(force_refresh=False):
        raise RuntimeError("backend down")

    monkeypatch.setattr(scraper, "get_favorites_async", _boom, raising=False)

    r = client.get("/api/anime/favoris")
    assert r.status_code == 200
    assert r.json() == {"animes": []}


def test_types_favoris_empty_urls_short_circuits(client, monkeypatch):
    """An empty url list returns an empty mapping without calling the detector."""
    from engine.scraping import scraper

    called = Mock()
    monkeypatch.setattr(scraper, "detecter_types_favoris_async", called, raising=False)

    r = client.post("/api/anime/types-favoris", headers=WRITE_HEADERS, json={"urls": []})
    assert r.status_code == 200
    assert r.json() == {"types": {}}
    called.assert_not_called()


def test_types_favoris_filters_non_strings_and_truncates(client, monkeypatch):
    """Non-string entries are dropped and the list is capped at 400 before detection."""
    from engine.scraping import scraper

    captured = {}

    async def _detect(urls):
        captured["urls"] = urls
        return {u: "anime" for u in urls}

    monkeypatch.setattr(scraper, "detecter_types_favoris_async", _detect, raising=False)

    payload = [f"u{i}" for i in range(450)]
    r = client.post("/api/anime/types-favoris", headers=WRITE_HEADERS, json={"urls": payload})
    assert r.status_code == 200
    assert len(captured["urls"]) == 400
    assert captured["urls"] == payload[:400]
    assert len(r.json()["types"]) == 400


def test_types_favoris_happy_path_returns_mapping(client, monkeypatch):
    """A valid list reaches the detector and its mapping is returned verbatim."""
    from engine.scraping import scraper

    async def _detect(urls):
        return {urls[0]: "scan"}

    monkeypatch.setattr(scraper, "detecter_types_favoris_async", _detect, raising=False)

    r = client.post(
        "/api/anime/types-favoris",
        headers=WRITE_HEADERS,
        json={"urls": ["https://anime-sama.to/catalogue/x"]},
    )
    assert r.status_code == 200
    assert r.json() == {"types": {"https://anime-sama.to/catalogue/x": "scan"}}


def test_types_favoris_exception_fallback(client, monkeypatch):
    """A raising detector degrades to an empty mapping."""
    from engine.scraping import scraper

    async def _boom(urls):
        raise RuntimeError("nope")

    monkeypatch.setattr(scraper, "detecter_types_favoris_async", _boom, raising=False)

    r = client.post(
        "/api/anime/types-favoris",
        headers=WRITE_HEADERS,
        json={"urls": ["https://anime-sama.to/catalogue/x"]},
    )
    assert r.status_code == 200
    assert r.json() == {"types": {}}


def test_get_episodes_exception_fallback_shape(client, monkeypatch):
    """A raising episodes backend on a safe URL returns the empty fallback dict."""
    import web.api.routes.anime.scraping as scraping_route
    from engine.scraping import scraper

    monkeypatch.setattr(scraping_route, "_est_url_site", lambda u: True)

    async def _boom(url):
        raise RuntimeError("io")

    monkeypatch.setattr(scraper, "get_episodes_async", _boom, raising=False)

    r = client.get(
        "/api/anime/episodes",
        params={"url": "https://anime-sama.to/catalogue/x"},
    )
    assert r.status_code == 200
    assert r.json() == {"titre": "", "episodes": [], "langues": [], "total": 0}


def test_scan_chapitres_exception_fallback_shape(client, monkeypatch):
    """A raising get_scan_info on a valid slug returns the structured error fallback."""
    from engine.scraping import scan as scan_mod

    async def _boom(slug, lang):
        raise RuntimeError("api down")

    monkeypatch.setattr(scan_mod, "get_scan_info", _boom)

    r = client.get("/api/anime/scan", params={"slug": "naruto", "lang": "vf"})
    assert r.status_code == 200
    assert r.json() == {"ok": False, "error": "Erreur scan", "chapitres": []}


def test_scan_pages_happy_path(client, monkeypatch):
    """A successful get_pages call is wrapped under the pages key."""
    from engine.scraping import scan as scan_mod

    async def _pages(oeuvre, chap, lang):
        return [{"page": 1, "url": "u1"}, {"page": 2, "url": "u2"}]

    monkeypatch.setattr(scan_mod, "get_pages", _pages)

    r = client.get(
        "/api/anime/scan-pages",
        params={"oeuvre": "Naruto", "chap": "12", "lang": "vf"},
    )
    assert r.status_code == 200
    assert r.json() == {"pages": [{"page": 1, "url": "u1"}, {"page": 2, "url": "u2"}]}


def test_scan_pages_exception_fallback(client, monkeypatch):
    """A raising get_pages degrades to an empty pages list."""
    from engine.scraping import scan as scan_mod

    async def _boom(oeuvre, chap, lang):
        raise RuntimeError("boom")

    monkeypatch.setattr(scan_mod, "get_pages", _boom)

    r = client.get(
        "/api/anime/scan-pages",
        params={"oeuvre": "Naruto", "chap": "12"},
    )
    assert r.status_code == 200
    assert r.json() == {"pages": []}


def test_scan_pages_missing_required_param_422(client):
    """Omitting the required chap query is rejected by validation before any fetch."""
    r = client.get("/api/anime/scan-pages", params={"oeuvre": "Naruto"})
    assert r.status_code == 422


def test_recherche_passes_covers_snapshot_as_known(client, monkeypatch, _isole_covers_cache):
    """recherche hands a snapshot of the covers cache to the search backend."""
    from engine.cache import covers as covers_mod
    from engine.scraping import scraper

    with covers_mod._covers_lock_thread:
        _isole_covers_cache["naruto"] = "https://x/n.jpg"

    captured = {}

    async def _search(q, known_covers=None):
        captured["q"] = q
        captured["known"] = known_covers
        return [{"slug": "naruto"}]

    monkeypatch.setattr(scraper, "search_async", _search, raising=False)

    r = client.get("/api/anime/recherche", params={"q": "naru"})
    assert r.status_code == 200
    assert r.json() == {"animes": [{"slug": "naruto"}], "total": 1}
    assert captured["q"] == "naru"
    assert captured["known"] == {"naruto": "https://x/n.jpg"}


def test_cover_proxy_unsafe_url_400(client, monkeypatch):
    """An unsafe URL is rejected with 400 before any cache lookup or warming."""
    import web.api.routes.anime.covers as covers_route
    from engine.cache import cover_images

    cached = Mock()
    warm = Mock()
    monkeypatch.setattr(covers_route, "is_safe_url", lambda u: False)
    monkeypatch.setattr(cover_images, "cached_file", cached)
    monkeypatch.setattr(cover_images, "warm", warm)

    r = client.get(
        "/api/anime/cover",
        params={"u": "http://169.254.169.254/latest/meta"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "URL invalide"
    cached.assert_not_called()
    warm.assert_not_called()


def test_cover_proxy_miss_warms_and_redirects(client, monkeypatch):
    """A cache miss warms the image and replies with a 307 redirect to the source."""
    import web.api.routes.anime.covers as covers_route
    from engine.cache import cover_images

    warm = Mock()
    monkeypatch.setattr(covers_route, "is_safe_url", lambda u: True)
    monkeypatch.setattr(cover_images, "cached_file", lambda u: None)
    monkeypatch.setattr(cover_images, "warm", warm)

    url = "https://anime-sama.to/img/miss.jpg"
    r = client.get("/api/anime/cover", params={"u": url}, follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == url
    warm.assert_called_once_with(url)


def test_get_covers_returns_cache_copy(client, monkeypatch, _isole_covers_cache):
    """GET /covers returns the current cache contents as a plain dict."""
    from engine.cache import covers as covers_mod

    with covers_mod._covers_lock_thread:
        _isole_covers_cache["k"] = "https://x/k.jpg"

    r = client.get("/api/anime/covers")
    assert r.status_code == 200
    assert r.json() == {"k": "https://x/k.jpg"}


def test_update_covers_happy_persists_snapshot_and_counts(client, monkeypatch, _isole_covers_cache):
    """A fresh cover is added, persisted via _save_covers, and counted in the reply."""
    import web.api.routes.anime.covers as covers_route

    captured = {}

    def _save(snapshot):
        captured["snapshot"] = dict(snapshot)
        return True

    monkeypatch.setattr(covers_route, "_save_covers", _save)

    r = client.post(
        "/api/anime/covers",
        headers=WRITE_HEADERS,
        json={"covers": {"naruto": "https://x/n.jpg"}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body == {"ok": True, "total": 1, "ajoutes": 1}
    assert captured["snapshot"] == {"naruto": "https://x/n.jpg"}
    assert dict(_isole_covers_cache) == {"naruto": "https://x/n.jpg"}


def test_update_covers_disk_failure_still_ok(client, monkeypatch, _isole_covers_cache):
    """A failing disk save still reports ok=True with the RAM cache updated."""
    import web.api.routes.anime.covers as covers_route

    monkeypatch.setattr(covers_route, "_save_covers", Mock(return_value=False))

    r = client.post(
        "/api/anime/covers",
        headers=WRITE_HEADERS,
        json={"covers": {"k": "https://x/k.jpg"}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["ajoutes"] == 1
    assert dict(_isole_covers_cache) == {"k": "https://x/k.jpg"}


def test_update_covers_truncates_when_over_max(client, monkeypatch, _isole_covers_cache):
    """When the cache exceeds the cap after update it is truncated to the most-recent entries."""
    import web.api.routes.anime.covers as covers_route

    monkeypatch.setattr(covers_route, "COVERS_MAX_ENTRIES", 3)
    monkeypatch.setattr(covers_route, "_save_covers", Mock(return_value=True))

    with covers_route._covers_lock_thread:
        _isole_covers_cache.update(
            {"a": "https://x/a.jpg", "b": "https://x/b.jpg", "c": "https://x/c.jpg"}
        )

    r = client.post(
        "/api/anime/covers",
        headers=WRITE_HEADERS,
        json={"covers": {"d": "https://x/d.jpg"}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["ajoutes"] == 1
    assert body["total"] == 3
    assert set(_isole_covers_cache) == {"b", "c", "d"}
