import asyncio
import zipfile
from unittest.mock import Mock

import pytest

import engine.config.logging_setup  # noqa: F401

WRITE_HEADERS = {"origin": "http://localhost:7843"}

BASE_SETTINGS = {
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
    return dict(BASE_SETTINGS)


@pytest.fixture(autouse=True)
def _reset_nm3u8dl_cache():
    import engine.download.methods.nm3u8dl as nm3u8dl

    lock = nm3u8dl._settings_cache_lock
    with lock:
        cache_snap = nm3u8dl._settings_cache
        ts_snap = nm3u8dl._settings_cache_ts
        nm3u8dl._settings_cache = None
        nm3u8dl._settings_cache_ts = 0.0
    yield
    with lock:
        nm3u8dl._settings_cache = cache_snap
        nm3u8dl._settings_cache_ts = ts_snap


@pytest.fixture
def patched_settings_io(monkeypatch):
    import web.api.routes.settings as settings_mod

    captured = {}

    def _save(s):
        captured["s"] = dict(s)
        return True

    monkeypatch.setattr(settings_mod, "load_settings", _fresh_settings)
    monkeypatch.setattr(settings_mod, "save_settings", _save)
    return captured


def test_valider_dossier_not_writable_returns_false(monkeypatch, tmp_path):
    import web.api.routes.settings as settings_mod
    from web.api.routes.settings import _valider_dossier

    cible = tmp_path / "ro"
    cible.mkdir()

    monkeypatch.setattr(settings_mod.os, "access", lambda p, mode: False)

    ok, msg = _valider_dossier(str(cible))
    assert ok is False
    assert "non accessible en écriture" in msg
    assert str(cible) in msg


def test_valider_dossier_oserror_branch(monkeypatch, tmp_path):
    import web.api.routes.settings as settings_mod
    from web.api.routes.settings import _valider_dossier

    cible = tmp_path / "missing"

    real_mkdir = settings_mod.Path.mkdir

    def _boom_mkdir(self, *a, **k):
        if str(self) == str(cible):
            raise OSError("read-only file system")
        return real_mkdir(self, *a, **k)

    monkeypatch.setattr(settings_mod.Path, "mkdir", _boom_mkdir)

    ok, msg = _valider_dossier(str(cible))
    assert ok is False
    assert msg.startswith("Impossible de créer/accéder au dossier")


def test_valider_dossier_valueerror_branch():
    from web.api.routes.settings import _valider_dossier

    ok, msg = _valider_dossier("bad\x00path")
    assert ok is False
    assert msg == "Chemin invalide"


def test_update_settings_thread_count_non_int_returns_message(client, monkeypatch, patched_settings_io):
    import web.api.routes.settings as settings_mod

    class _Body:
        qualite = None
        thread_count = object()
        downloads_dir = None
        scans_dir = None
        notifications = None
        son_notif = None
        confirm_suppr = None
        skip_existants = None
        langue_defaut = None

    res = asyncio.run(settings_mod.update_settings(_Body()))
    assert res == {"ok": False, "message": "thread_count doit être un entier"}


def test_update_settings_downloads_dir_invalid_returns_message(client, monkeypatch, patched_settings_io):
    import web.api.routes.settings as settings_mod

    monkeypatch.setattr(settings_mod, "_valider_dossier", lambda c: (False, "boom-dl"))

    r = client.post("/api/settings", headers=WRITE_HEADERS, json={"downloads_dir": "/x"})
    assert r.status_code == 200
    assert r.json() == {"ok": False, "message": "boom-dl"}


def test_update_settings_scans_dir_invalid_returns_message(client, monkeypatch, patched_settings_io):
    import web.api.routes.settings as settings_mod

    monkeypatch.setattr(settings_mod, "_valider_dossier", lambda c: (False, "boom-scans"))

    r = client.post("/api/settings", headers=WRITE_HEADERS, json={"scans_dir": "/x"})
    assert r.status_code == 200
    assert r.json() == {"ok": False, "message": "boom-scans"}


def test_update_settings_dir_cache_invalidation_exception_swallowed(client, monkeypatch, patched_settings_io):
    import web.api.routes.settings as settings_mod
    from engine.config import settings as cfg_settings

    monkeypatch.setattr(settings_mod, "_valider_dossier", lambda c: (True, "/resolved"))

    def _boom():
        raise RuntimeError("cache module exploded")

    monkeypatch.setattr(cfg_settings, "invalider_downloads_dir_cache", _boom)

    r = client.post("/api/settings", headers=WRITE_HEADERS, json={"downloads_dir": "/x"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["settings"]["downloads_dir"] == "/resolved"


def test_update_settings_nm3u8dl_cache_invalidation_exception_swallowed(client, monkeypatch, patched_settings_io):
    import engine.download.methods.nm3u8dl as nm3u8dl

    class _BoomLock:
        def __enter__(self):
            raise RuntimeError("lock exploded")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(nm3u8dl, "_settings_cache_lock", _BoomLock())

    r = client.post("/api/settings", headers=WRITE_HEADERS, json={"qualite": "1080"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["settings"]["qualite"] == "1080"


@pytest.fixture
def authorized_media(monkeypatch):
    from engine.library import scanner

    monkeypatch.setattr(scanner, "est_dans_downloads", lambda f: True)
    return scanner


def test_supprimer_rejects_outside_downloads(client, monkeypatch, tmp_path):
    from engine.library import scanner

    cible = tmp_path / "ep.mp4"
    cible.write_bytes(b"data")
    monkeypatch.setattr(scanner, "est_dans_downloads", lambda f: False)

    r = client.post("/api/anime/supprimer", headers=WRITE_HEADERS, json={"fichier": str(cible)})
    assert r.status_code == 200
    assert r.json() == {"ok": False, "message": "Chemin non autorisé"}
    assert cible.exists()


def test_supprimer_missing_file_returns_introuvable(client, authorized_media, tmp_path):
    cible = tmp_path / "absent.mp4"

    r = client.post("/api/anime/supprimer", headers=WRITE_HEADERS, json={"fichier": str(cible)})
    assert r.status_code == 200
    assert r.json() == {"ok": False, "message": "Fichier introuvable"}


def test_valider_cbz_not_a_file_returns_404(client, authorized_media, tmp_path):
    dossier = tmp_path / "looks_like.cbz"
    dossier.mkdir()

    r = client.get("/api/anime/scan-local", params={"fichier": str(dossier)})
    assert r.status_code == 404
    assert r.json()["detail"] == "Fichier introuvable"


def _build_cbz(path):
    payloads = {
        "page1.png": b"\x89PNG-one",
        "page2.jpg": b"JPEG-two",
    }
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in payloads.items():
            zf.writestr(name, data)
    return payloads


def test_scan_local_img_read_failure_returns_400(client, monkeypatch, authorized_media, tmp_path):
    import web.api.routes.anime.files as files_mod

    cbz = tmp_path / "chap.cbz"
    _build_cbz(cbz)

    real_zipfile = files_mod.zipfile.ZipFile

    class _BoomZip:
        def __init__(self, *a, **k):
            self._zf = real_zipfile(*a, **k)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return self._zf.__exit__(*a)

        def namelist(self):
            return self._zf.namelist()

        def read(self, name):
            raise OSError("zip member unreadable")

    monkeypatch.setattr(files_mod.zipfile, "ZipFile", _BoomZip)

    r = client.get("/api/anime/scan-local-img", params={"fichier": str(cbz), "page": 0})
    assert r.status_code == 400
    assert r.json()["detail"] == "Lecture CBZ impossible"


@pytest.fixture
def _isole_covers_cache():
    from engine.cache import covers as covers_mod

    with covers_mod._covers_lock_thread:
        snapshot = dict(covers_mod._covers_cache)
        covers_mod._covers_cache.clear()
    yield covers_mod._covers_cache
    with covers_mod._covers_lock_thread:
        covers_mod._covers_cache.clear()
        covers_mod._covers_cache.update(snapshot)


def test_update_covers_non_dict_direct_call_returns_format_invalide(_isole_covers_cache):
    import web.api.routes.anime.covers as covers_route
    from web.api.routes.anime._models import CoversBody

    body = CoversBody.model_construct(covers=[1, 2, 3])
    res = asyncio.run(covers_route.update_covers(body))
    assert res == {"ok": False, "message": "Format invalide"}


def test_update_covers_skips_non_string_key_or_value(client, monkeypatch, _isole_covers_cache):
    import web.api.routes.anime.covers as covers_route

    monkeypatch.setattr(covers_route, "_save_covers", Mock(return_value=True))

    covers = {
        "ok_key": "https://x/a.jpg",
        "num_val": 123,
        "list_val": ["https://x/b.jpg"],
    }
    r = client.post("/api/anime/covers", headers=WRITE_HEADERS, json={"covers": covers})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["ajoutes"] == 1
    assert set(_isole_covers_cache) == {"ok_key"}


def test_get_librairie_double_check_returns_cache_after_lock(client, monkeypatch):
    from engine.library import scanner

    state = {"calls": 0}
    cached = {"animes": [{"x": 1}], "total": 1, "tronque": False}

    def _get():
        state["calls"] += 1
        if state["calls"] == 1:
            return None
        return cached

    scan = Mock()
    monkeypatch.setattr(scanner, "librairie_cache_get", _get)
    monkeypatch.setattr(scanner, "scan_librairie_sync", scan)

    r = client.get("/api/anime/librairie")
    assert r.status_code == 200
    assert r.json() == cached
    assert state["calls"] == 2
    scan.assert_not_called()


def test_check_updates_route_forwards_refresh(client, monkeypatch):
    import web.api.routes.anime.updates as updates_route

    captured = {}

    async def _fake(refresh):
        captured["refresh"] = refresh
        return {"updates": [], "total": 0}

    monkeypatch.setattr(updates_route, "check_updates_async", _fake)

    r = client.get("/api/anime/check-updates", params={"refresh": "true"})
    assert r.status_code == 200
    assert r.json() == {"updates": [], "total": 0}
    assert captured["refresh"] is True


def test_coherence_librairie_route_passthrough(client, monkeypatch):
    import web.api.routes.anime.updates as updates_route

    async def _fake():
        return {"ok": True, "incoherences": []}

    monkeypatch.setattr(updates_route, "verifier_coherence_librairie", _fake)

    r = client.get("/api/anime/coherence-librairie")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "incoherences": []}


def test_dl_episode_non_dict_ep_direct_call_returns_message():
    import web.api.routes.download as dl_mod

    body = dl_mod.DlEpisodeBody.model_construct(ep="not-a-dict", episodes=[])
    res = asyncio.run(dl_mod.dl_episode(body))
    assert res == {"ok": False, "message": "ep manquant ou invalide"}


def test_dl_episode_no_dict_episode_direct_call_returns_message():
    import web.api.routes.download as dl_mod

    body = dl_mod.DlEpisodeBody.model_construct(ep={"url": "u"}, episodes=["x", 5])
    res = asyncio.run(dl_mod.dl_episode(body))
    assert res == {"ok": False, "message": "Aucun épisode valide"}


def test_login_request_empty_password_after_strip_raises():
    from pydantic import ValidationError

    from web.api.models import LoginRequest

    with pytest.raises(ValidationError) as exc:
        LoginRequest(pseudo="utilisateur_test", password="   ")
    assert "mot de passe ne peut pas être vide" in str(exc.value)
