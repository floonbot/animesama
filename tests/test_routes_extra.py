import asyncio
import zipfile
from unittest.mock import Mock

import pytest

import engine.config.logging_setup  # noqa: F401

WRITE_HEADERS = {"origin": "http://localhost:7843"}

DEFAULT_SETTINGS_SNAPSHOT = {
    "qualite": "auto",
    "thread_count": 16,
    "downloads_dir": "",
    "scans_dir": "",
    "notifications": True,
    "son_notif": True,
    "confirm_suppr": True,
    "skip_existants": True,
    "langue_defaut": "VOSTFR",
}

def _fresh_settings() -> dict:
    return dict(DEFAULT_SETTINGS_SNAPSHOT)

def test_settings_post_invalid_qualite_returns_ok_false(client, monkeypatch):
    """An unsupported quality string is rejected with ok=False and never persisted."""
    import web.api.routes.settings as settings_mod

    save = Mock(return_value=True)
    monkeypatch.setattr(settings_mod, "load_settings", _fresh_settings)
    monkeypatch.setattr(settings_mod, "save_settings", save)

    r = client.post("/api/settings", headers=WRITE_HEADERS, json={"qualite": "4k"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "480" in body["message"] and "1080" in body["message"]
    save.assert_not_called()

def test_settings_post_invalid_qualite_lists_sorted_valides(client, monkeypatch):
    """The rejection message exposes the sorted set of accepted qualities."""
    import web.api.routes.settings as settings_mod
    from engine.config.user_settings import QUALITES_VALIDES

    monkeypatch.setattr(settings_mod, "load_settings", _fresh_settings)
    monkeypatch.setattr(settings_mod, "save_settings", Mock(return_value=True))

    r = client.post("/api/settings", headers=WRITE_HEADERS, json={"qualite": "zzz"})
    assert str(sorted(QUALITES_VALIDES)) in r.json()["message"]

@pytest.mark.parametrize("envoye,attendu", [(999, 32), (0, 1), (50, 32), (-5, 1)])
def test_settings_post_thread_count_clamped_and_persisted(client, monkeypatch, envoye, attendu):
    """thread_count is clamped into [1, 32] in the dict handed to save_settings."""
    import web.api.routes.settings as settings_mod

    captured = {}

    def _save(s):
        captured["s"] = dict(s)
        return True

    monkeypatch.setattr(settings_mod, "load_settings", _fresh_settings)
    monkeypatch.setattr(settings_mod, "save_settings", _save)

    r = client.post("/api/settings", headers=WRITE_HEADERS, json={"thread_count": envoye})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert captured["s"]["thread_count"] == attendu

def test_settings_post_save_failure_returns_disk_message(client, monkeypatch):
    """A failing save_settings surfaces the disk-error message with ok=False."""
    import web.api.routes.settings as settings_mod

    monkeypatch.setattr(settings_mod, "load_settings", _fresh_settings)
    monkeypatch.setattr(settings_mod, "save_settings", Mock(return_value=False))

    r = client.post("/api/settings", headers=WRITE_HEADERS, json={"qualite": "auto"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["message"] == "Sauvegarde impossible (disque ?)"

def test_valider_dossier_empty_string_passthrough():
    """An empty path is accepted verbatim without touching the filesystem."""
    from web.api.routes.settings import _valider_dossier

    assert _valider_dossier("") == (True, "")

def test_valider_dossier_creates_missing_directory(tmp_path):
    """A non-existent path is created and the resolved string is returned."""
    from web.api.routes.settings import _valider_dossier

    cible = tmp_path / "nouveau" / "downloads"
    ok, val = _valider_dossier(str(cible))
    assert ok is True
    assert cible.is_dir()
    assert val == str(cible)

def test_valider_dossier_rejects_existing_file(tmp_path):
    """Pointing at a regular file is rejected as not-a-directory."""
    from web.api.routes.settings import _valider_dossier

    f = tmp_path / "pas_un_dossier.txt"
    f.write_text("x", encoding="utf-8")
    ok, msg = _valider_dossier(str(f))
    assert ok is False
    assert "Ce n'est pas un dossier" in msg

@pytest.fixture
def reset_login_throttle(monkeypatch):
    import web.api.routes.auth as auth_mod

    async def _no_sleep(_s):
        return None

    monkeypatch.setattr(auth_mod.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(auth_mod, "_last_login_ts", 0.0)
    yield auth_mod
    monkeypatch.setattr(auth_mod, "_last_login_ts", 0.0)

def test_login_rate_limit_returns_429(client, monkeypatch, reset_login_throttle):
    """A saturated login queue (wait>=MAX) is refused with 429 before any backend call."""
    auth_mod = reset_login_throttle
    from engine.auth.manager import auth_manager

    monkeypatch.setattr(auth_mod.time, "time", lambda: 1000.0)
    monkeypatch.setattr(auth_mod, "_last_login_ts", 1000.0 + 10.0)

    login_async = Mock()
    monkeypatch.setattr(auth_manager, "login_async", login_async)

    r = client.post(
        "/api/auth/login",
        headers=WRITE_HEADERS,
        json={"pseudo": "utilisateur_test", "password": "secret"},
    )
    assert r.status_code == 429
    assert "Trop de tentatives" in r.json()["detail"]
    login_async.assert_not_called()

@pytest.mark.parametrize(
    "payload",
    [
        {"pseudo": "", "password": "secret"},
        {"pseudo": "utilisateur_test", "password": ""},
        {"password": "secret"},
    ],
)
def test_login_request_validation_422(client, monkeypatch, reset_login_throttle, payload):
    """Empty pseudo, empty password, or missing pseudo is rejected by the model with 422."""
    auth_mod = reset_login_throttle
    monkeypatch.setattr(auth_mod.time, "time", lambda: 10_000.0)

    r = client.post("/api/auth/login", headers=WRITE_HEADERS, json=payload)
    assert r.status_code == 422

def test_login_happy_path_passthrough(client, monkeypatch, reset_login_throttle):
    """A valid body forwards the auth_manager.login_async result verbatim."""
    auth_mod = reset_login_throttle
    from engine.auth.manager import auth_manager

    monkeypatch.setattr(auth_mod.time, "time", lambda: 10_000.0)

    async def _login(email, password):
        return {"ok": True, "message": "Connecté !", "username": "u"}

    monkeypatch.setattr(auth_manager, "login_async", _login)

    r = client.post(
        "/api/auth/login",
        headers=WRITE_HEADERS,
        json={"pseudo": "utilisateur_test", "password": "secret"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["username"] == "u"

def test_logout_success_returns_ok_and_invokes_manager(client, monkeypatch):
    """A clean logout returns ok=True and actually calls auth_manager.logout."""
    from engine.auth.manager import auth_manager

    logout = Mock()
    monkeypatch.setattr(auth_manager, "logout", logout)

    r = client.post("/api/auth/logout", headers=WRITE_HEADERS)
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    logout.assert_called_once()

def test_logout_error_returns_structured_message(client, monkeypatch):
    """A raising logout degrades to ok=False with a structured message, not a 500."""
    from engine.auth.manager import auth_manager

    monkeypatch.setattr(auth_manager, "logout", Mock(side_effect=RuntimeError("boom")))

    r = client.post("/api/auth/logout", headers=WRITE_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["message"] == "Erreur pendant la déconnexion"

def test_get_episodes_rejects_offsite_url(client, monkeypatch):
    """An off-site URL that still satisfies the length gate is refused with 400."""
    from engine.scraping import scraper

    called = Mock()
    monkeypatch.setattr(scraper, "get_episodes_async", called, raising=False)

    r = client.get("/api/anime/episodes", params={"url": "https://evil.example.com/page"})
    assert r.status_code == 400
    assert r.json()["detail"] == "URL non autorisée"
    called.assert_not_called()

def test_get_episodes_too_short_url_422(client):
    """A URL shorter than the minimum length is rejected by query validation."""
    r = client.get("/api/anime/episodes", params={"url": "short"})
    assert r.status_code == 422

def test_get_episodes_onsite_url_passthrough(client, monkeypatch):
    """An on-site URL reaches get_episodes_async and its dict is returned."""
    from engine.scraping import scraper

    async def _fake(url):
        return {"titre": "X", "episodes": [1, 2], "langues": ["vostfr"], "total": 2}

    monkeypatch.setattr(scraper, "get_episodes_async", _fake, raising=False)

    r = client.get(
        "/api/anime/episodes",
        params={"url": "https://anime-sama.to/catalogue/x"},
    )
    assert r.status_code == 200
    assert r.json()["total"] == 2

def test_scan_chapitres_invalid_slug_400(client):
    """A path-traversal-ish slug is rejected with 400 before any fetch."""
    r = client.get("/api/anime/scan", params={"slug": "../etc", "lang": "vf"})
    assert r.status_code == 400
    assert r.json()["detail"] == "Slug invalide"

def test_scan_chapitres_lang_too_long_422(client):
    """A lang query longer than 4 chars is rejected by validation."""
    r = client.get("/api/anime/scan", params={"slug": "naruto", "lang": "toolong"})
    assert r.status_code == 422

def test_scan_chapitres_valid_slug_passthrough(client, monkeypatch):
    """A valid slug routes to get_scan_info and returns its dict."""
    from engine.scraping import scan as scan_mod

    async def _fake(slug, lang):
        return {"ok": True, "chapitres": [1, 2, 3]}

    monkeypatch.setattr(scan_mod, "get_scan_info", _fake)

    r = client.get("/api/anime/scan", params={"slug": "naruto", "lang": "vf"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "chapitres": [1, 2, 3]}

def test_recherche_exception_fallback_shape(client, monkeypatch):
    """A failing search backend degrades to an empty result set, not a 500."""
    from engine.scraping import scraper

    async def _boom(q, known_covers=None):
        raise RuntimeError("backend down")

    monkeypatch.setattr(scraper, "search_async", _boom, raising=False)

    r = client.get("/api/anime/recherche", params={"q": "naruto"})
    assert r.status_code == 200
    assert r.json() == {"animes": [], "total": 0}

def test_recherche_success_total_matches_length(client, monkeypatch):
    """On success total equals the number of returned animes."""
    from engine.scraping import scraper

    async def _ok(q, known_covers=None):
        return [{"a": 1}, {"a": 2}, {"a": 3}]

    monkeypatch.setattr(scraper, "search_async", _ok, raising=False)

    r = client.get("/api/anime/recherche", params={"q": "naruto"})
    body = r.json()
    assert body["total"] == 3
    assert len(body["animes"]) == 3

@pytest.fixture
def isole_covers_cache():
    from engine.cache import covers as covers_mod

    snapshot = dict(covers_mod._covers_cache)
    covers_mod._covers_cache.clear()
    yield covers_mod._covers_cache
    covers_mod._covers_cache.clear()
    covers_mod._covers_cache.update(snapshot)

def test_update_covers_non_dict_rejected_by_model(client, monkeypatch, isole_covers_cache):
    """A non-dict covers payload is rejected by the pydantic gate with 422.

    The route's own ``Format invalide`` branch is unreachable from HTTP because
    ``CoversBody.covers`` is typed ``dict`` and pydantic validates first.
    """
    import web.api.routes.anime.covers as covers_route

    save = Mock(return_value=True)
    monkeypatch.setattr(covers_route, "_save_covers", save)

    r = client.post("/api/anime/covers", headers=WRITE_HEADERS, json={"covers": [1, 2]})
    assert r.status_code == 422
    save.assert_not_called()

def test_update_covers_too_many_entries(client, monkeypatch, isole_covers_cache):
    """A covers dict above the max-entries limit is refused with a max message."""
    import web.api.routes.anime.covers as covers_route
    from engine.cache.covers import COVERS_MAX_ENTRIES

    monkeypatch.setattr(covers_route, "_save_covers", Mock(return_value=True))

    big = {f"k{i}": f"https://x/{i}.jpg" for i in range(COVERS_MAX_ENTRIES + 1)}
    r = client.post("/api/anime/covers", headers=WRITE_HEADERS, json={"covers": big})
    assert r.json()["ok"] is False
    assert str(COVERS_MAX_ENTRIES) in r.json()["message"]

def test_update_covers_filters_bad_schemes_and_lengths(client, monkeypatch, isole_covers_cache):
    """Only http/https/data values within length limits are kept; the rest are dropped."""
    import web.api.routes.anime.covers as covers_route

    monkeypatch.setattr(covers_route, "_save_covers", Mock(return_value=True))

    covers = {
        "good_http": "http://x/a.jpg",
        "good_https": "https://x/b.jpg",
        "good_data": "data:image/png;base64,AAAA",
        "bad_ftp": "ftp://x/c.jpg",
        "bad_long_val": "https://x/" + ("z" * 600),
        ("k" * 201): "https://x/d.jpg",
    }
    r = client.post("/api/anime/covers", headers=WRITE_HEADERS, json={"covers": covers})
    body = r.json()
    assert body["ok"] is True
    assert body["ajoutes"] == 3
    assert set(isole_covers_cache) == {"good_http", "good_https", "good_data"}

def test_update_covers_dedup_early_return(client, monkeypatch, isole_covers_cache):
    """Re-posting an identical cover is a no-op that skips the disk save entirely."""
    import web.api.routes.anime.covers as covers_route

    isole_covers_cache["existant"] = "https://x/exists.jpg"
    save = Mock(return_value=True)
    monkeypatch.setattr(covers_route, "_save_covers", save)

    r = client.post(
        "/api/anime/covers",
        headers=WRITE_HEADERS,
        json={"covers": {"existant": "https://x/exists.jpg"}},
    )
    body = r.json()
    assert body["ok"] is True
    assert body["ajoutes"] == 0
    save.assert_not_called()

def test_cover_proxy_hit_serves_file(client, monkeypatch, tmp_path):
    """A cache hit serves the file with the immutable header and never warms."""
    from engine.cache import cover_images
    from web.api.routes.anime import covers as covers_route

    img = tmp_path / "cover.jpg"
    img.write_bytes(b"\xff\xd8\xff\xd9")

    warm = Mock()
    monkeypatch.setattr(covers_route, "is_safe_url", lambda u: True)
    monkeypatch.setattr(cover_images, "cached_file", lambda u: img)
    monkeypatch.setattr(cover_images, "warm", warm)

    r = client.get(
        "/api/anime/cover",
        params={"u": "https://anime-sama.to/img/cover.jpg"},
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=2592000, immutable"
    warm.assert_not_called()

@pytest.mark.parametrize(
    "dans_downloads,kind,statut_attendu",
    [
        (False, "file", 403),
        (True, "missing", 404),
        (True, "dir", 400),
        (True, "file", 200),
    ],
)
def test_stream_video_gate_chain(client, monkeypatch, tmp_path, dans_downloads, kind, statut_attendu):
    """stream_video applies the downloads/exists/isfile gate chain in order."""
    from engine.library import scanner

    if kind == "file":
        target = tmp_path / "ep.mp4"
        target.write_bytes(b"data")
    elif kind == "dir":
        target = tmp_path / "ep.mp4"
        target.mkdir()
    else:
        target = tmp_path / "ep.mp4"

    monkeypatch.setattr(scanner, "est_dans_downloads", lambda f: dans_downloads)

    r = client.get("/api/anime/stream", params={"fichier": str(target)})
    assert r.status_code == statut_attendu
    if statut_attendu == 200:
        assert r.headers["accept-ranges"] == "bytes"
        assert r.headers["content-type"] == "video/mp4"

def test_supprimer_episode_success_invalidates_caches(client, monkeypatch, tmp_path):
    """Deleting an in-downloads .cbz removes it and invalidates both caches."""
    import web.api.routes.anime.files as files_route
    from engine.library import scanner

    cbz = tmp_path / "chap.cbz"
    cbz.write_bytes(b"zip")

    monkeypatch.setattr(scanner, "est_dans_downloads", lambda f: True)
    inval_lib = Mock()
    inval_upd = Mock()
    monkeypatch.setattr(scanner, "invalider_cache_librairie", inval_lib)
    monkeypatch.setattr(files_route, "invalider_cache_updates", inval_upd)

    r = client.post("/api/anime/supprimer", headers=WRITE_HEADERS, json={"fichier": str(cbz)})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert not cbz.exists()
    inval_lib.assert_called_once()
    inval_upd.assert_called_once()

def test_supprimer_episode_oserror_returns_structured_error(client, monkeypatch, tmp_path):
    """An OSError during removal degrades to ok=False, not a 500."""
    import web.api.routes.anime.files as files_route
    from engine.library import scanner

    cbz = tmp_path / "chap.cbz"
    cbz.write_bytes(b"zip")

    monkeypatch.setattr(scanner, "est_dans_downloads", lambda f: True)

    def _boom(_p):
        raise OSError("locked")

    monkeypatch.setattr(files_route.os, "remove", _boom)

    r = client.post("/api/anime/supprimer", headers=WRITE_HEADERS, json={"fichier": str(cbz)})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["message"] == "Suppression impossible"

def _build_cbz(path):
    payloads = {
        "page1.png": b"\x89PNG-one",
        "page2.jpg": b"JPEG-two",
        "page3.jpeg": b"JPEG-three",
        "notes.txt": b"ignore me",
    }
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in payloads.items():
            zf.writestr(name, data)
    return payloads

def test_scan_local_counts_only_images(client, monkeypatch, tmp_path):
    """scan-local counts image members only and reports the stem as name."""
    from engine.library import scanner

    cbz = tmp_path / "MonChapitre.cbz"
    _build_cbz(cbz)
    monkeypatch.setattr(scanner, "est_dans_downloads", lambda f: True)

    r = client.get("/api/anime/scan-local", params={"fichier": str(cbz)})
    assert r.status_code == 200
    body = r.json()
    assert body == {"ok": True, "pages": 3, "nom": "MonChapitre"}

def test_scan_local_non_cbz_400(client, monkeypatch, tmp_path):
    """A non-.cbz path is rejected with 400."""
    from engine.library import scanner

    monkeypatch.setattr(scanner, "est_dans_downloads", lambda f: True)
    r = client.get("/api/anime/scan-local", params={"fichier": str(tmp_path / "x.mp4")})
    assert r.status_code == 400

def test_scan_local_outside_downloads_403(client, monkeypatch, tmp_path):
    """A .cbz outside the downloads dir is refused with 403."""
    from engine.library import scanner

    cbz = tmp_path / "x.cbz"
    cbz.write_bytes(b"zip")
    monkeypatch.setattr(scanner, "est_dans_downloads", lambda f: False)
    r = client.get("/api/anime/scan-local", params={"fichier": str(cbz)})
    assert r.status_code == 403

def test_scan_local_corrupt_zip_400(client, monkeypatch, tmp_path):
    """A corrupt .cbz yields the CBZ-illisible 400, not a 500."""
    from engine.library import scanner

    cbz = tmp_path / "broken.cbz"
    cbz.write_bytes(b"this is not a zip file at all")
    monkeypatch.setattr(scanner, "est_dans_downloads", lambda f: True)

    r = client.get("/api/anime/scan-local", params={"fichier": str(cbz)})
    assert r.status_code == 400
    assert r.json()["detail"] == "CBZ illisible"

def test_scan_local_img_returns_first_page_bytes(client, monkeypatch, tmp_path):
    """scan-local-img page=0 returns the first sorted image bytes and its media type."""
    from engine.library import scanner

    cbz = tmp_path / "chap.cbz"
    _build_cbz(cbz)
    monkeypatch.setattr(scanner, "est_dans_downloads", lambda f: True)

    with zipfile.ZipFile(cbz) as zf:
        attendu = zf.read("page1.png")

    r = client.get("/api/anime/scan-local-img", params={"fichier": str(cbz), "page": 0})
    assert r.status_code == 200
    assert r.content == attendu
    assert r.headers["content-type"] == "image/png"

def test_scan_local_img_out_of_range_404(client, monkeypatch, tmp_path):
    """A page index beyond the image count yields 404 Page hors limites."""
    from engine.library import scanner

    cbz = tmp_path / "chap.cbz"
    _build_cbz(cbz)
    monkeypatch.setattr(scanner, "est_dans_downloads", lambda f: True)

    r = client.get("/api/anime/scan-local-img", params={"fichier": str(cbz), "page": 99})
    assert r.status_code == 404
    assert r.json()["detail"] == "Page hors limites"

def test_scan_local_img_negative_page_422(client, monkeypatch, tmp_path):
    """A negative page index is rejected by the ge=0 query constraint."""
    from engine.library import scanner

    cbz = tmp_path / "chap.cbz"
    _build_cbz(cbz)
    monkeypatch.setattr(scanner, "est_dans_downloads", lambda f: True)

    r = client.get("/api/anime/scan-local-img", params={"fichier": str(cbz), "page": -1})
    assert r.status_code == 422

def test_get_librairie_cache_hit_skips_scan(client, monkeypatch):
    """A populated library cache is returned verbatim and the scan is skipped."""
    from engine.library import scanner

    cached = {"animes": [{"x": 1}], "total": 1, "tronque": False}
    scan = Mock()
    monkeypatch.setattr(scanner, "librairie_cache_get", lambda: cached)
    monkeypatch.setattr(scanner, "scan_librairie_sync", scan)

    r = client.get("/api/anime/librairie")
    assert r.status_code == 200
    assert r.json() == cached
    scan.assert_not_called()

def test_get_librairie_cache_miss_scans_and_sets(client, monkeypatch):
    """A cache miss runs the scan once and stores its result."""
    from engine.library import scanner

    result = {"animes": [], "total": 0, "tronque": False}
    monkeypatch.setattr(scanner, "librairie_cache_get", lambda: None)
    scan = Mock(return_value=result)
    set_cache = Mock()
    monkeypatch.setattr(scanner, "scan_librairie_sync", scan)
    monkeypatch.setattr(scanner, "librairie_cache_set", set_cache)

    r = client.get("/api/anime/librairie")
    assert r.status_code == 200
    assert r.json() == result
    scan.assert_called_once()
    set_cache.assert_called_once_with(result)

def test_get_librairie_scan_exception_fallback(client, monkeypatch):
    """A failing scan returns an empty library and never caches the failure."""
    from engine.library import scanner

    monkeypatch.setattr(scanner, "librairie_cache_get", lambda: None)
    monkeypatch.setattr(scanner, "scan_librairie_sync", Mock(side_effect=RuntimeError("io")))
    set_cache = Mock()
    monkeypatch.setattr(scanner, "librairie_cache_set", set_cache)

    r = client.get("/api/anime/librairie")
    assert r.status_code == 200
    assert r.json() == {"animes": [], "total": 0, "tronque": False}
    set_cache.assert_not_called()

def test_dl_scan_blank_chapitres_returns_ok_false(client, monkeypatch):
    """A chapter list of only blanks is rejected before the queue is touched."""
    from engine.services.download_service import download_service

    add = Mock()
    monkeypatch.setattr(download_service, "ajouter_scan", add)

    r = client.post(
        "/api/download/scan",
        headers=WRITE_HEADERS,
        json={"slug": "naruto", "oeuvre": "Naruto", "chapitres": ["", "   ", "\t"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["message"] == "Aucun chapitre sélectionné"
    add.assert_not_called()

def test_dl_scan_cleans_chapitres_before_submit(client, monkeypatch):
    """Whitespace-only chapter entries are stripped out before submission."""
    from engine.services.download_service import download_service

    captured = {}

    async def _add(slug, oeuvre, lang, chapitres, nom):
        captured["chapitres"] = chapitres
        return {"ok": True}

    monkeypatch.setattr(download_service, "ajouter_scan", _add)

    r = client.post(
        "/api/download/scan",
        headers=WRITE_HEADERS,
        json={"slug": "naruto", "oeuvre": "Naruto", "chapitres": ["1", " ", "2"]},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert captured["chapitres"] == ["1", "2"]

def test_dl_episode_passes_dict_episodes_through(client, monkeypatch):
    """A valid list of dict episodes reaches the service unchanged (happy path)."""
    from engine.services.download_service import download_service

    captured = {}

    async def _add(item):
        captured["item"] = item
        return {"ok": True}

    monkeypatch.setattr(download_service, "ajouter_episode", _add)

    ep = {"url": "u", "titre": "t"}
    r = client.post(
        "/api/download/episode",
        headers=WRITE_HEADERS,
        json={"ep": ep, "episodes": [{"url": "a"}, {"url": "b"}]},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert captured["item"]["episodes"] == [{"url": "a"}, {"url": "b"}]


def test_dl_episode_non_dict_entry_rejected_by_model(client):
    """Non-dict episode entries are rejected at the model boundary (422), never reaching the route."""
    ep = {"url": "u", "titre": "t"}
    r = client.post(
        "/api/download/episode",
        headers=WRITE_HEADERS,
        json={"ep": ep, "episodes": [{"url": "a"}, "not-a-dict", 123]},
    )
    assert r.status_code == 422

def test_dl_episode_empty_episodes_uses_ep(client, monkeypatch):
    """With no episodes list the single ep becomes the lone episode entry."""
    from engine.services.download_service import download_service

    captured = {}

    async def _add(item):
        captured["item"] = item
        return {"ok": True}

    monkeypatch.setattr(download_service, "ajouter_episode", _add)

    ep = {"url": "u", "titre": "t"}
    r = client.post(
        "/api/download/episode",
        headers=WRITE_HEADERS,
        json={"ep": ep, "episodes": []},
    )
    assert r.status_code == 200
    assert captured["item"]["episodes"] == [ep]

def test_download_scan_body_max_length_422(client):
    """A chapter list above the documented per-lot limit is rejected by validation."""
    r = client.post(
        "/api/download/scan",
        headers=WRITE_HEADERS,
        json={"slug": "x", "oeuvre": "y", "chapitres": ["c"] * 5001},
    )
    assert r.status_code == 422

def test_download_episode_body_max_length_422(client):
    """An episodes list above the per-lot limit is rejected by validation."""
    r = client.post(
        "/api/download/episode",
        headers=WRITE_HEADERS,
        json={"ep": {"url": "u"}, "episodes": [{"url": "u"}] * 501},
    )
    assert r.status_code == 422

@pytest.fixture
def isole_sse_state():
    import web.api.routes.sse as sse_mod

    listeners_snap = dict(sse_mod._listeners)
    loop_snap = sse_mod._main_loop
    shutdown_snap = sse_mod._shutdown_event
    warn_snap = dict(sse_mod._last_full_warn)
    yield sse_mod
    sse_mod._listeners.clear()
    sse_mod._listeners.update(listeners_snap)
    sse_mod._main_loop = loop_snap
    sse_mod._shutdown_event = shutdown_snap
    sse_mod._last_full_warn.clear()
    sse_mod._last_full_warn.update(warn_snap)

def test_sse_emit_non_serializable_fallback(isole_sse_state):
    """A non-serializable payload is fanned out as an error frame, not an exception."""
    import json

    sse_mod = isole_sse_state
    recu = {}

    async def _scenario():
        sse_mod.capture_loop_at_startup()
        q: asyncio.Queue = asyncio.Queue(maxsize=10)
        with sse_mod._listeners_lock:
            sse_mod._listeners[424242] = q
        sse_mod.emit("x", {"bad": set()})
        await asyncio.sleep(0)
        recu["frame"] = await q.get()

    asyncio.run(_scenario())

    frame = recu["frame"]
    assert frame.startswith("event: x\ndata: ")
    data = json.loads(frame.split("data: ", 1)[1].strip())
    assert data == {"type": "error", "message": "non serializable"}

def test_sse_emit_serializable_payload_delivered(isole_sse_state):
    """A serializable payload is delivered intact with its type and fields."""
    import json

    sse_mod = isole_sse_state
    recu = {}

    async def _scenario():
        sse_mod.capture_loop_at_startup()
        q: asyncio.Queue = asyncio.Queue(maxsize=10)
        with sse_mod._listeners_lock:
            sse_mod._listeners[535353] = q
        sse_mod.emit("queue_updated", {"n": 5})
        await asyncio.sleep(0)
        recu["frame"] = await q.get()

    asyncio.run(_scenario())

    data = json.loads(recu["frame"].split("data: ", 1)[1].strip())
    assert data == {"type": "queue_updated", "n": 5}

@pytest.mark.parametrize(
    "event_type,data,attendu",
    [
        ("queue_updated", {}, False),
        ("episode_done", {"succes": True, "skipped": True}, False),
        ("episode_done", {"succes": False}, False),
        ("episode_done", {"succes": True}, True),
    ],
)
def test_sse_refresh_library_on_success_gating(monkeypatch, event_type, data, attendu):
    """Caches are invalidated only for a real, non-skipped completion event."""
    import web.api.routes.sse as sse_mod
    from engine.library import scanner, updates

    inval_lib = Mock()
    inval_upd = Mock()
    monkeypatch.setattr(scanner, "invalider_cache_librairie", inval_lib)
    monkeypatch.setattr(updates, "invalider_cache_updates", inval_upd)

    sse_mod._refresh_library_on_success(event_type, data)

    if attendu:
        inval_lib.assert_called_once()
        inval_upd.assert_called_once()
    else:
        inval_lib.assert_not_called()
        inval_upd.assert_not_called()
