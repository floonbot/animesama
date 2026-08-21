import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_PROBE_ENV = """
import json, os
import engine.config.settings as s
print(json.dumps({
    "root": str(s.ROOT_DIR),
    "downloads": str(s.DOWNLOADS_DIR),
    "scans": str(s.SCANS_DIR),
    "downloads_exists": os.path.isdir(str(s.DOWNLOADS_DIR)),
    "scans_exists": os.path.isdir(str(s.SCANS_DIR)),
}))
"""

_PROBE_FROZEN = """
import json, os, sys
sys.frozen = True
sys.executable = os.environ["FAKE_EXE"]
import engine.config.settings as s
dl = s.get_downloads_dir()
sc = s.get_scans_dir()
print(json.dumps({
    "root": str(s.ROOT_DIR),
    "downloads": str(s.DOWNLOADS_DIR),
    "scans": str(s.SCANS_DIR),
    "get_downloads": str(dl),
    "get_scans": str(sc),
    "downloads_exists": os.path.isdir(str(dl)),
    "scans_exists": os.path.isdir(str(sc)),
    "root_entries": sorted(os.listdir(str(s.ROOT_DIR))),
}))
"""


def _run_probe(code: str, env_extra: dict) -> dict:
    env = dict(os.environ)
    env.pop("DOWNLOADS_DIR", None)
    env.pop("SCANS_DIR", None)
    # La sonde mesure justement l'emplacement *par defaut* : elle ne doit pas
    # heriter de la redirection que conftest.py pose pour toute la session.
    env.pop("ANIMESAMA_DATA_DIR", None)
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, f"probe failed:\n{proc.stdout}\n{proc.stderr}"
    lignes = [ligne for ligne in proc.stdout.splitlines() if ligne.strip()]
    assert lignes, f"probe sans sortie:\n{proc.stderr}"
    return json.loads(lignes[-1])


def test_import_settings_cree_les_dossiers_configures(tmp_path):
    dl = tmp_path / "ghost_dl"
    sc = tmp_path / "ghost_sc"

    info = _run_probe(_PROBE_ENV, {"DOWNLOADS_DIR": str(dl), "SCANS_DIR": str(sc)})

    assert Path(info["downloads"]) == dl
    assert Path(info["scans"]) == sc
    assert info["downloads_exists"] is True
    assert info["scans_exists"] is True
    assert dl.is_dir()
    assert sc.is_dir()


def test_import_settings_cree_les_dossiers_par_defaut(tmp_path):
    fake_root = tmp_path / "app"
    fake_root.mkdir()

    info = _run_probe(_PROBE_FROZEN, {"FAKE_EXE": str(fake_root / "AnimeSama.exe")})

    assert Path(info["root"]) == fake_root
    assert Path(info["downloads"]) == fake_root / "downloads"
    assert Path(info["scans"]) == fake_root / "scans"
    assert Path(info["get_downloads"]) == fake_root / "downloads"
    assert Path(info["get_scans"]) == fake_root / "scans"
    assert info["downloads_exists"] is True
    assert info["scans_exists"] is True
    assert "data" in info["root_entries"]
    assert "downloads" in info["root_entries"]
    assert "scans" in info["root_entries"]
    assert (fake_root / "downloads").is_dir()
    assert (fake_root / "scans").is_dir()


def test_scan_download_materialise_la_racine_scans_absente(tmp_path):
    from engine.download.methods import images

    racine = tmp_path / "ghost_scans"
    dossier = racine / "Mon Oeuvre" / "Scan VF"
    assert not racine.exists()

    res = images.scan_download("mon-oeuvre", "vf", [], str(dossier))

    assert res is None
    assert racine.is_dir()
    assert dossier.is_dir()


def test_ffmpeg_materialise_la_racine_downloads_absente(tmp_path, monkeypatch):
    from engine.download.methods import ffmpeg_engine

    racine = tmp_path / "ghost_downloads"
    dossier = racine / "Mon Anime" / "Saison 1"
    assert not racine.exists()

    def _popen_boom(*a, **k):
        raise FileNotFoundError("ffmpeg absent")

    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg_engine, "_estimer_duree_hls", lambda *a: 0.0)
    monkeypatch.setattr(ffmpeg_engine.subprocess, "Popen", _popen_boom)

    res = ffmpeg_engine.ffmpeg_download("http://host/x.m3u8", str(dossier), "ep")

    assert res is None
    assert racine.is_dir()
    assert dossier.is_dir()


def test_health_disk_omet_les_racines_absentes(tmp_path, monkeypatch):
    import engine.config.settings as cfg
    from web.api.routes import health as health_mod

    monkeypatch.setattr(cfg, "get_downloads_dir", lambda: tmp_path / "ghost_dl")
    monkeypatch.setattr(cfg, "get_scans_dir", lambda: tmp_path / "ghost_sc")

    out = asyncio.run(health_mod.health())

    assert out["ok"] is True
    assert "downloads" not in out["disk"]
    assert "scans" not in out["disk"]
    assert "temp" in out["disk"]


def test_librairie_degrade_proprement_sans_racine(tmp_path, monkeypatch):
    import engine.config.settings as cfg
    import engine.library.scanner as scanner

    monkeypatch.setattr(cfg, "get_downloads_dir", lambda: tmp_path / "ghost_dl")
    monkeypatch.setattr(cfg, "get_scans_dir", lambda: tmp_path / "ghost_sc")
    scanner.invalider_cache_dossiers()
    scanner.invalider_cache_librairie()
    try:
        assert scanner.dossiers_actifs() == []
        assert scanner.scan_librairie_sync() == {"animes": [], "total": 0, "tronque": False}
    finally:
        scanner.invalider_cache_dossiers()
        scanner.invalider_cache_librairie()


def test_refresh_library_on_success_invalide_le_cache_librairie(tmp_path, monkeypatch):
    import engine.config.settings as cfg
    import engine.library.scanner as scanner
    from web.api.routes import sse as sse_mod

    dl = tmp_path / "dl"
    dl.mkdir()
    sc = tmp_path / "sc"
    monkeypatch.setattr(cfg, "get_downloads_dir", lambda: dl)
    monkeypatch.setattr(cfg, "get_scans_dir", lambda: sc)
    scanner.invalider_cache_dossiers()
    scanner.invalider_cache_librairie()
    try:
        assert scanner.dossiers_actifs() == [dl.resolve()]
        scanner.librairie_cache_set({"animes": [], "total": 0, "tronque": False})
        assert scanner.librairie_cache_get() is not None
        sc.mkdir()

        sse_mod._refresh_library_on_success("episode_done", {"succes": True, "skipped": False})

        assert scanner.librairie_cache_get() is None
        assert scanner.dossiers_actifs() == [dl.resolve()]
    finally:
        scanner.invalider_cache_dossiers()
        scanner.invalider_cache_librairie()


def test_refresh_library_on_success_gating_inchange(tmp_path, monkeypatch):
    import engine.config.settings as cfg
    import engine.library.scanner as scanner
    from web.api.routes import sse as sse_mod

    dl = tmp_path / "dl"
    dl.mkdir()
    sc = tmp_path / "sc"
    monkeypatch.setattr(cfg, "get_downloads_dir", lambda: dl)
    monkeypatch.setattr(cfg, "get_scans_dir", lambda: sc)
    scanner.invalider_cache_dossiers()
    try:
        assert scanner.dossiers_actifs() == [dl.resolve()]
        sc.mkdir()

        sse_mod._refresh_library_on_success("episode_done", {"succes": True, "skipped": True})

        assert scanner.dossiers_actifs() == [dl.resolve()]
    finally:
        scanner.invalider_cache_dossiers()
