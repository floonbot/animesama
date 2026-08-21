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


def _base_settings() -> dict:
    return dict(BASE_SETTINGS)


@pytest.fixture(autouse=True)
def reset_nm3u8dl_cache():
    import engine.download.methods.nm3u8dl as nm3u8dl

    nm3u8dl._settings_cache = None
    nm3u8dl._settings_cache_ts = 0.0
    yield
    nm3u8dl._settings_cache = None
    nm3u8dl._settings_cache_ts = 0.0


@pytest.fixture
def patched_settings_io(monkeypatch):
    import web.api.routes.settings as settings_mod

    captured = {}

    def _save(s):
        captured["s"] = dict(s)
        return True

    monkeypatch.setattr(settings_mod, "load_settings", _base_settings)
    monkeypatch.setattr(settings_mod, "save_settings", _save)
    return captured


def test_downloads_dir_change_invalidates_all_caches(client, monkeypatch, patched_settings_io):
    """Changing downloads_dir invalidates downloads/dossiers/librairie caches and nm3u8dl cache."""
    import engine.download.methods.nm3u8dl as nm3u8dl
    import web.api.routes.settings as settings_mod
    from engine.config import settings as cfg_settings
    from engine.library import scanner

    nm3u8dl._settings_cache = {"qualite": "1080"}
    nm3u8dl._settings_cache_ts = 123.0

    monkeypatch.setattr(settings_mod, "_valider_dossier", lambda c: (True, "/x"))

    inval_dl = Mock()
    inval_scans = Mock()
    inval_dossiers = Mock()
    inval_lib = Mock()
    monkeypatch.setattr(cfg_settings, "invalider_downloads_dir_cache", inval_dl)
    monkeypatch.setattr(cfg_settings, "invalider_scans_dir_cache", inval_scans)
    monkeypatch.setattr(scanner, "invalider_cache_dossiers", inval_dossiers)
    monkeypatch.setattr(scanner, "invalider_cache_librairie", inval_lib)

    r = client.post("/api/settings", headers=WRITE_HEADERS, json={"downloads_dir": "/some/path"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["settings"]["downloads_dir"] == "/x"

    inval_dl.assert_called_once()
    inval_dossiers.assert_called_once()
    inval_lib.assert_called_once()
    inval_scans.assert_not_called()

    assert nm3u8dl._settings_cache is None
    assert nm3u8dl._settings_cache_ts == 0.0


def test_scans_dir_change_invalidates_scans_but_not_downloads_or_nm3u8dl(client, monkeypatch, patched_settings_io):
    """Changing only scans_dir invalidates scans/dossiers/librairie but not downloads-dir or nm3u8dl."""
    import engine.download.methods.nm3u8dl as nm3u8dl
    import web.api.routes.settings as settings_mod
    from engine.config import settings as cfg_settings
    from engine.library import scanner

    nm3u8dl._settings_cache = {"qualite": "1080"}
    nm3u8dl._settings_cache_ts = 999.0

    monkeypatch.setattr(settings_mod, "_valider_dossier", lambda c: (True, "/x"))

    inval_dl = Mock()
    inval_scans = Mock()
    inval_dossiers = Mock()
    inval_lib = Mock()
    monkeypatch.setattr(cfg_settings, "invalider_downloads_dir_cache", inval_dl)
    monkeypatch.setattr(cfg_settings, "invalider_scans_dir_cache", inval_scans)
    monkeypatch.setattr(scanner, "invalider_cache_dossiers", inval_dossiers)
    monkeypatch.setattr(scanner, "invalider_cache_librairie", inval_lib)

    r = client.post("/api/settings", headers=WRITE_HEADERS, json={"scans_dir": "/scans/path"})
    assert r.status_code == 200
    assert r.json()["settings"]["scans_dir"] == "/x"

    inval_scans.assert_called_once()
    inval_dossiers.assert_called_once()
    inval_lib.assert_called_once()
    inval_dl.assert_not_called()

    assert nm3u8dl._settings_cache == {"qualite": "1080"}
    assert nm3u8dl._settings_cache_ts == 999.0


@pytest.mark.parametrize("envoye,attendu", [("vf", "VF"), ("vostfr", "VOSTFR"), ("VoStFr", "VOSTFR")])
def test_langue_defaut_normalised_to_upper(client, patched_settings_io, envoye, attendu):
    """A recognised langue_defaut is upper-cased before being persisted."""
    r = client.post("/api/settings", headers=WRITE_HEADERS, json={"langue_defaut": envoye})
    assert r.status_code == 200
    assert r.json()["settings"]["langue_defaut"] == attendu
    assert patched_settings_io["s"]["langue_defaut"] == attendu


def test_langue_defaut_invalid_value_left_unchanged(client, patched_settings_io):
    """An unrecognised langue_defaut leaves the existing value untouched."""
    r = client.post("/api/settings", headers=WRITE_HEADERS, json={"langue_defaut": "espagnol"})
    assert r.status_code == 200
    assert r.json()["settings"]["langue_defaut"] == "VOSTFR"
    assert patched_settings_io["s"]["langue_defaut"] == "VOSTFR"


@pytest.mark.parametrize(
    "champ,envoye,attendu",
    [
        ("notifications", True, True),
        ("notifications", False, False),
        ("son_notif", False, False),
        ("confirm_suppr", False, False),
        ("skip_existants", True, True),
    ],
)
def test_boolean_flags_coerced_to_bool(client, patched_settings_io, champ, envoye, attendu):
    """Each boolean flag is coerced and persisted as a real bool."""
    r = client.post("/api/settings", headers=WRITE_HEADERS, json={champ: envoye})
    assert r.status_code == 200
    valeur = r.json()["settings"][champ]
    assert valeur is attendu
    assert patched_settings_io["s"][champ] is attendu


def test_no_dir_change_leaves_nm3u8dl_cache_intact(client, monkeypatch, patched_settings_io):
    """A body with no qualite/thread_count/downloads_dir leaves the nm3u8dl cache untouched."""
    import engine.download.methods.nm3u8dl as nm3u8dl

    nm3u8dl._settings_cache = {"qualite": "720"}
    nm3u8dl._settings_cache_ts = 555.0

    r = client.post("/api/settings", headers=WRITE_HEADERS, json={"notifications": True})
    assert r.status_code == 200
    assert r.json()["ok"] is True

    assert nm3u8dl._settings_cache == {"qualite": "720"}
    assert nm3u8dl._settings_cache_ts == 555.0


def test_qualite_change_resets_nm3u8dl_cache_without_dir_invalidation(client, monkeypatch, patched_settings_io):
    """A qualite change resets the nm3u8dl cache but does not touch dossiers/librairie caches."""
    import engine.download.methods.nm3u8dl as nm3u8dl
    from engine.library import scanner

    nm3u8dl._settings_cache = {"qualite": "480"}
    nm3u8dl._settings_cache_ts = 42.0

    inval_dossiers = Mock()
    monkeypatch.setattr(scanner, "invalider_cache_dossiers", inval_dossiers)

    r = client.post("/api/settings", headers=WRITE_HEADERS, json={"qualite": "1080"})
    assert r.status_code == 200
    assert r.json()["settings"]["qualite"] == "1080"

    assert nm3u8dl._settings_cache is None
    assert nm3u8dl._settings_cache_ts == 0.0
    inval_dossiers.assert_not_called()


@pytest.fixture
def patched_files(monkeypatch):
    import web.api.routes.anime.files as files_mod
    from engine.library import scanner

    opened = []
    monkeypatch.setattr(files_mod, "_open_in_file_manager", lambda d: opened.append(d))
    monkeypatch.setattr(scanner, "est_dans_downloads", lambda f: True)
    monkeypatch.setattr(files_mod.os.path, "exists", lambda f: True)
    return files_mod, scanner, opened


def test_ouvrir_dossier_rejects_outside_downloads(client, monkeypatch, patched_files):
    """A path outside downloads is refused and the file manager is never invoked."""
    files_mod, scanner, opened = patched_files
    monkeypatch.setattr(scanner, "est_dans_downloads", lambda f: False)

    r = client.post("/api/anime/ouvrir-dossier", headers=WRITE_HEADERS, json={"fichier": "/x/y.mp4"})
    assert r.status_code == 200
    assert r.json() == {"ok": False, "message": "Chemin non autorisé"}
    assert opened == []


def test_ouvrir_dossier_authorization_runs_before_filesystem(client, monkeypatch, patched_files):
    """Security contract: the est_dans_downloads gate runs BEFORE the user path is stat'd."""
    files_mod, scanner, opened = patched_files
    cible = "/x/unauthorised.mp4"
    exists_calls = []
    monkeypatch.setattr(scanner, "est_dans_downloads", lambda f: False)
    monkeypatch.setattr(files_mod.os.path, "exists", lambda f: exists_calls.append(f) or True)

    r = client.post("/api/anime/ouvrir-dossier", headers=WRITE_HEADERS, json={"fichier": cible})
    assert r.json() == {"ok": False, "message": "Chemin non autorisé"}
    assert cible not in exists_calls
    assert opened == []


def test_thread_count_change_resets_nm3u8dl_cache(client, patched_settings_io):
    """A thread_count-only change resets the nm3u8dl settings cache (concurrency gate)."""
    import engine.download.methods.nm3u8dl as nm3u8dl

    nm3u8dl._settings_cache = {"qualite": "480"}
    nm3u8dl._settings_cache_ts = 42.0

    r = client.post("/api/settings", headers=WRITE_HEADERS, json={"thread_count": 8})
    assert r.status_code == 200
    assert r.json()["settings"]["thread_count"] == 8
    assert nm3u8dl._settings_cache is None
    assert nm3u8dl._settings_cache_ts == 0.0


def test_ouvrir_dossier_missing_file(client, monkeypatch, patched_files):
    """A missing file yields 'Fichier introuvable' and never opens a folder."""
    files_mod, scanner, opened = patched_files
    monkeypatch.setattr(files_mod.os.path, "exists", lambda f: False)

    r = client.post("/api/anime/ouvrir-dossier", headers=WRITE_HEADERS, json={"fichier": "/dl/y.mp4"})
    assert r.status_code == 200
    assert r.json() == {"ok": False, "message": "Fichier introuvable"}
    assert opened == []


def test_ouvrir_dossier_success_opens_parent_directory(client, patched_files):
    """An authorised existing file opens its parent directory in the file manager."""
    import os

    files_mod, scanner, opened = patched_files

    cible = "/dl/anime/ep1.mp4"
    r = client.post("/api/anime/ouvrir-dossier", headers=WRITE_HEADERS, json={"fichier": cible})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert opened == [os.path.dirname(os.path.abspath(cible))]


def test_ouvrir_dossier_open_failure_returns_structured_error(client, monkeypatch, patched_files):
    """A raising file-manager opener degrades to ok=False with a structured message."""
    files_mod, scanner, opened = patched_files

    def _boom(_d):
        raise RuntimeError("no display")

    monkeypatch.setattr(files_mod, "_open_in_file_manager", _boom)

    r = client.post("/api/anime/ouvrir-dossier", headers=WRITE_HEADERS, json={"fichier": "/dl/y.mp4"})
    assert r.status_code == 200
    assert r.json() == {"ok": False, "message": "Impossible d'ouvrir le dossier"}


def test_open_in_file_manager_win32_uses_startfile(monkeypatch):
    """On win32 the opener dispatches to os.startfile with the folder path."""
    import web.api.routes.anime.files as files_mod

    startfile_calls = []
    popen_calls = []
    monkeypatch.setattr(files_mod.sys, "platform", "win32")
    monkeypatch.setattr(files_mod.os, "startfile", lambda d: startfile_calls.append(d), raising=False)
    monkeypatch.setattr(files_mod.subprocess, "Popen", lambda args: popen_calls.append(args))

    files_mod._open_in_file_manager("/some/dir")
    assert startfile_calls == ["/some/dir"]
    assert popen_calls == []


def test_open_in_file_manager_darwin_uses_open(monkeypatch):
    """On darwin the opener spawns the 'open' command for the folder."""
    import web.api.routes.anime.files as files_mod

    startfile_calls = []
    popen_calls = []
    monkeypatch.setattr(files_mod.sys, "platform", "darwin")
    monkeypatch.setattr(files_mod.os, "startfile", lambda d: startfile_calls.append(d), raising=False)
    monkeypatch.setattr(files_mod.subprocess, "Popen", lambda args: popen_calls.append(args))

    files_mod._open_in_file_manager("/some/dir")
    assert popen_calls == [["open", "/some/dir"]]
    assert startfile_calls == []


def test_open_in_file_manager_linux_uses_xdg_open(monkeypatch):
    """On other platforms the opener spawns xdg-open for the folder."""
    import web.api.routes.anime.files as files_mod

    startfile_calls = []
    popen_calls = []
    monkeypatch.setattr(files_mod.sys, "platform", "linux")
    monkeypatch.setattr(files_mod.os, "startfile", lambda d: startfile_calls.append(d), raising=False)
    monkeypatch.setattr(files_mod.subprocess, "Popen", lambda args: popen_calls.append(args))

    files_mod._open_in_file_manager("/some/dir")
    assert popen_calls == [["xdg-open", "/some/dir"]]
    assert startfile_calls == []
