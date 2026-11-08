import os

import pytest

import engine.config.settings as settings_mod
import engine.config.user_settings as user_settings
import engine.download.methods._nm3u8dl_parsing as nm3u8dl_parsing
import engine.download.methods._ytdlp_parsing as ytdlp_parsing
import engine.download.methods.nm3u8dl as nm3u8dl
import engine.download.methods.ytdlp_engine as ytdlp_engine
from engine.config.settings import DEFAULT_USER_AGENT


@pytest.fixture(autouse=True)
def _snapshot_module_globals():
    ytdlp_saved = (ytdlp_engine._YTDLP_PATH, ytdlp_engine._ARIA2C_PATH)
    nm_saved = (
        nm3u8dl._NM3U8DL_PATH,
        nm3u8dl._NM3U8DL_LAST_SEARCH_TS,
        nm3u8dl._settings_cache,
        nm3u8dl._settings_cache_ts,
    )
    yield
    ytdlp_engine._YTDLP_PATH, ytdlp_engine._ARIA2C_PATH = ytdlp_saved
    (
        nm3u8dl._NM3U8DL_PATH,
        nm3u8dl._NM3U8DL_LAST_SEARCH_TS,
        nm3u8dl._settings_cache,
        nm3u8dl._settings_cache_ts,
    ) = nm_saved


class _FakeClock:
    def __init__(self, value=1000.0):
        self.value = value

    def __call__(self):
        return self.value


class _RecordingPopen:
    def __init__(self):
        self.cmd = None

    def __call__(self, cmd, *args, **kwargs):
        self.cmd = list(cmd)
        raise FileNotFoundError("popen should not actually launch")


def _adjacent(cmd, flag, value):
    pairs = [(cmd[i], cmd[i + 1]) for i in range(len(cmd) - 1)]
    return (flag, value) in pairs


def test_find_exe_returns_root_bin_path(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_mod, "ROOT_DIR", tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    target = bin_dir / "yt-dlp.exe"
    target.write_bytes(b"x")

    which_calls = []
    monkeypatch.setattr(
        ytdlp_engine.shutil, "which", lambda n: which_calls.append(n) or None
    )

    res = ytdlp_engine._find_exe(["yt-dlp.exe", "yt-dlp"])

    assert res == str(target)
    assert which_calls == []


def test_find_exe_falls_back_to_which(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_mod, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(
        ytdlp_engine.os.path, "exists", lambda p: False
    )
    monkeypatch.setattr(
        ytdlp_engine.shutil,
        "which",
        lambda n: "/usr/bin/yt-dlp" if n == "yt-dlp" else None,
    )

    res = ytdlp_engine._find_exe(["yt-dlp.exe", "yt-dlp"])

    assert res == "/usr/bin/yt-dlp"


def test_find_exe_returns_none_when_nothing_found(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_mod, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(ytdlp_engine.os.path, "exists", lambda p: False)
    monkeypatch.setattr(ytdlp_engine.shutil, "which", lambda n: None)

    assert ytdlp_engine._find_exe(["yt-dlp.exe", "yt-dlp"]) is None


def test_get_ytdlp_path_returns_cached_when_exists(monkeypatch):
    ytdlp_engine._YTDLP_PATH = "/cached/yt-dlp"
    monkeypatch.setattr(ytdlp_engine.os.path, "exists", lambda p: True)

    def _boom(_noms):
        raise AssertionError("_find_exe must not be called")

    monkeypatch.setattr(ytdlp_engine, "_find_exe", _boom)

    assert ytdlp_engine._get_ytdlp_path() == "/cached/yt-dlp"


def test_get_ytdlp_path_research_when_cached_missing(monkeypatch):
    ytdlp_engine._YTDLP_PATH = "/stale/yt-dlp"
    monkeypatch.setattr(ytdlp_engine.os.path, "exists", lambda p: False)
    monkeypatch.setattr(ytdlp_engine, "_find_exe", lambda noms: "/fresh/yt-dlp")

    assert ytdlp_engine._get_ytdlp_path() == "/fresh/yt-dlp"
    assert ytdlp_engine._YTDLP_PATH == "/fresh/yt-dlp"


def test_get_aria2c_path_returns_cached_when_exists(monkeypatch):
    ytdlp_engine._ARIA2C_PATH = "/cached/aria2c"
    monkeypatch.setattr(ytdlp_engine.os.path, "exists", lambda p: True)

    def _boom(_noms):
        raise AssertionError("_find_exe must not be called")

    monkeypatch.setattr(ytdlp_engine, "_find_exe", _boom)

    assert ytdlp_engine._get_aria2c_path() == "/cached/aria2c"


def test_get_aria2c_path_research_when_cached_missing(monkeypatch):
    ytdlp_engine._ARIA2C_PATH = None
    monkeypatch.setattr(ytdlp_engine.os.path, "exists", lambda p: False)
    monkeypatch.setattr(ytdlp_engine, "_find_exe", lambda noms: "/fresh/aria2c")

    assert ytdlp_engine._get_aria2c_path() == "/fresh/aria2c"
    assert ytdlp_engine._ARIA2C_PATH == "/fresh/aria2c"


def test_ytdlp_trouver_fichier_exact_name_ext(tmp_path, monkeypatch):
    monkeypatch.setattr(ytdlp_engine, "TAILLE_MIN_FICHIER", 10)
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"x" * 64)

    res = ytdlp_engine._trouver_fichier_final(str(tmp_path), "ep")

    assert res == str(final)


def test_ytdlp_trouver_fichier_exact_below_threshold_then_listdir(tmp_path, monkeypatch):
    monkeypatch.setattr(ytdlp_engine, "TAILLE_MIN_FICHIER", 50)
    small = tmp_path / "ep.mp4"
    small.write_bytes(b"x" * 10)
    big = tmp_path / "ep.f137.mkv"
    big.write_bytes(b"y" * 100)

    res = ytdlp_engine._trouver_fichier_final(str(tmp_path), "ep")

    assert res == str(big)


def test_ytdlp_trouver_fichier_listdir_all_too_small_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(ytdlp_engine, "TAILLE_MIN_FICHIER", 1000)
    (tmp_path / "ep.mp4").write_bytes(b"x" * 10)
    (tmp_path / "ep.part2.mkv").write_bytes(b"y" * 20)

    assert ytdlp_engine._trouver_fichier_final(str(tmp_path), "ep") is None


def test_ytdlp_trouver_fichier_missing_dir_returns_none(tmp_path):
    missing = tmp_path / "nope"
    assert ytdlp_engine._trouver_fichier_final(str(missing), "ep") is None


def test_ytdlp_download_no_exe_returns_none_and_warns_callback(tmp_path, monkeypatch):
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: None)

    calls = []
    res = ytdlp_engine.ytdlp_download(
        "http://host/v", str(tmp_path), "ep",
        callback=lambda p, t: calls.append((p, t)),
    )

    assert res is None
    assert len(calls) == 1
    assert calls[0][0] == 0.0
    assert "introuvable" in calls[0][1]


def test_ytdlp_download_invalid_url_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")

    def _no_makedirs(*a, **k):
        raise AssertionError("makedirs must not run on invalid url")

    monkeypatch.setattr(ytdlp_engine.os, "makedirs", _no_makedirs)

    res = ytdlp_engine.ytdlp_download("ftp://host/v", str(tmp_path), "ep")

    assert res is None


def test_ytdlp_download_aria2c_active_wires_command(tmp_path, monkeypatch):
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp_engine, "_get_aria2c_path", lambda: "/bin/aria2c")
    monkeypatch.setattr(user_settings, "load_settings", lambda: {"qualite": "auto"})

    captured = {}

    def _fake_construire(exe, url, dossier, nom, headers, qualite, aria2c=None, travail=None):
        captured["aria2c"] = aria2c
        captured["qualite"] = qualite
        return [exe, url]

    monkeypatch.setattr(ytdlp_engine, "_construire_commande", _fake_construire)

    rec = _RecordingPopen()
    monkeypatch.setattr(ytdlp_engine.subprocess, "Popen", rec)

    res = ytdlp_engine.ytdlp_download("http://host/v", str(tmp_path), "ep")

    assert res is None
    assert captured["aria2c"] == "/bin/aria2c"
    assert captured["qualite"] == "auto"
    assert rec.cmd == ["yt-dlp", "http://host/v"]


def test_ytdlp_download_settings_exception_uses_default_quality(tmp_path, monkeypatch):
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp_engine, "_get_aria2c_path", lambda: None)

    def _boom():
        raise RuntimeError("settings unavailable")

    monkeypatch.setattr(user_settings, "load_settings", _boom)

    captured = {}

    def _fake_construire(exe, url, dossier, nom, headers, qualite, aria2c=None, travail=None):
        captured["qualite"] = qualite
        return [exe, url]

    monkeypatch.setattr(ytdlp_engine, "_construire_commande", _fake_construire)
    monkeypatch.setattr(ytdlp_engine.subprocess, "Popen", _RecordingPopen())

    ytdlp_engine.ytdlp_download("http://host/v", str(tmp_path), "ep")

    assert captured["qualite"] == "auto"


def test_ytdlp_construire_commande_quality_1080_and_referer(tmp_path):
    cmd = ytdlp_parsing.construire_commande(
        "yt-dlp", "http://host/v", str(tmp_path), "ep",
        {"referer": "http://ref/"}, qualite="1080p",
    )

    assert _adjacent(cmd, "--format", "bestvideo[height<=1080]+bestaudio/best[height<=1080]")
    assert _adjacent(cmd, "--referer", "http://ref/")
    assert "--downloader" not in cmd


def test_ytdlp_construire_commande_quality_720(tmp_path):
    cmd = ytdlp_parsing.construire_commande(
        "yt-dlp", "http://host/v", str(tmp_path), "ep", {}, qualite="720",
    )
    assert _adjacent(cmd, "--format", "bestvideo[height<=720]+bestaudio/best[height<=720]")


def test_ytdlp_construire_commande_quality_480(tmp_path):
    cmd = ytdlp_parsing.construire_commande(
        "yt-dlp", "http://host/v", str(tmp_path), "ep", {}, qualite="480",
    )
    assert _adjacent(cmd, "--format", "bestvideo[height<=480]+bestaudio/best[height<=480]")


def test_ytdlp_construire_commande_quality_unknown_uses_best(tmp_path):
    cmd = ytdlp_parsing.construire_commande(
        "yt-dlp", "http://host/v", str(tmp_path), "ep", {}, qualite="4000",
    )
    assert _adjacent(cmd, "--format", "best")


def test_ytdlp_construire_commande_auto_format(tmp_path):
    cmd = ytdlp_parsing.construire_commande(
        "yt-dlp", "http://host/v", str(tmp_path), "ep", {}, qualite="auto",
    )
    assert _adjacent(
        cmd, "--format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
    )


def test_ytdlp_construire_commande_aria2c_block_and_cookie(tmp_path):
    cmd = ytdlp_parsing.construire_commande(
        "yt-dlp", "http://host/v", str(tmp_path), "ep",
        {"cookie": "sid=1"}, qualite="auto", aria2c="/bin/aria2c",
    )

    assert _adjacent(cmd, "--downloader", "aria2c")
    di = cmd.index("--downloader-args")
    assert cmd[di + 1].startswith("aria2c:")
    assert _adjacent(cmd, "--add-header", "Cookie:sid=1")


def test_ytdlp_construire_commande_sibnet_forces_referer_and_extractor(tmp_path):
    cmd = ytdlp_parsing.construire_commande(
        "yt-dlp", "https://video.sibnet.ru/clip", str(tmp_path), "ep",
        {"referer": "http://ignored/"}, qualite="auto",
    )

    assert _adjacent(cmd, "--referer", "https://video.sibnet.ru/")
    assert _adjacent(cmd, "--add-header", "Origin:https://video.sibnet.ru")
    assert _adjacent(cmd, "--extractor-args", "sibnet:quality=1080")
    assert "http://ignored/" not in cmd


def test_find_nm3u8dl_returns_root_path(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_mod, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(nm3u8dl.sys, "argv", ["main.py"])
    target = tmp_path / "N_m3u8DL-RE.exe"
    target.write_bytes(b"x")
    monkeypatch.setattr(nm3u8dl.shutil, "which", lambda n: None)

    assert nm3u8dl._find_nm3u8dl() == str(target)


def test_find_nm3u8dl_returns_none_when_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_mod, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(nm3u8dl.sys, "argv", ["main.py"])
    monkeypatch.setattr(nm3u8dl.os.path, "exists", lambda p: False)
    monkeypatch.setattr(nm3u8dl.shutil, "which", lambda n: None)

    assert nm3u8dl._find_nm3u8dl() is None


def test_get_nm3u8dl_path_cached_when_exists(monkeypatch):
    nm3u8dl._NM3U8DL_PATH = "/cached/N_m3u8DL-RE"
    monkeypatch.setattr(nm3u8dl.os.path, "exists", lambda p: True)

    def _boom():
        raise AssertionError("_find_nm3u8dl must not be called")

    monkeypatch.setattr(nm3u8dl, "_find_nm3u8dl", _boom)

    assert nm3u8dl._get_nm3u8dl_path() == "/cached/N_m3u8DL-RE"


def test_get_nm3u8dl_path_cooldown_blocks_research(monkeypatch):
    nm3u8dl._NM3U8DL_PATH = None
    nm3u8dl._NM3U8DL_LAST_SEARCH_TS = 1000.0
    monkeypatch.setattr(nm3u8dl.os.path, "exists", lambda p: False)
    monkeypatch.setattr(nm3u8dl.time, "time", _FakeClock(1005.0))

    def _boom():
        raise AssertionError("research blocked by cooldown")

    monkeypatch.setattr(nm3u8dl, "_find_nm3u8dl", _boom)

    assert nm3u8dl._get_nm3u8dl_path() is None


def test_get_nm3u8dl_path_research_after_cooldown(monkeypatch):
    nm3u8dl._NM3U8DL_PATH = None
    nm3u8dl._NM3U8DL_LAST_SEARCH_TS = 1000.0
    monkeypatch.setattr(nm3u8dl.os.path, "exists", lambda p: False)
    monkeypatch.setattr(nm3u8dl.time, "time", _FakeClock(2000.0))
    monkeypatch.setattr(nm3u8dl, "_find_nm3u8dl", lambda: "/fresh/N_m3u8DL-RE")

    assert nm3u8dl._get_nm3u8dl_path() == "/fresh/N_m3u8DL-RE"
    assert nm3u8dl._NM3U8DL_PATH == "/fresh/N_m3u8DL-RE"
    assert nm3u8dl._NM3U8DL_LAST_SEARCH_TS == 2000.0


def test_nm3u8dl_trouver_fichier_above_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(nm3u8dl, "TAILLE_MIN_FICHIER", 50)
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"x" * 100)

    assert nm3u8dl._trouver_fichier_final(str(tmp_path), "ep") == str(final)


def test_nm3u8dl_trouver_fichier_at_threshold_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(nm3u8dl, "TAILLE_MIN_FICHIER", 50)
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"x" * 50)

    assert nm3u8dl._trouver_fichier_final(str(tmp_path), "ep") is None


def test_nm3u8dl_trouver_fichier_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(nm3u8dl, "TAILLE_MIN_FICHIER", 1)
    assert nm3u8dl._trouver_fichier_final(str(tmp_path), "ep") is None


def test_nm3u8dl_download_no_exe_returns_none_and_callback(tmp_path, monkeypatch):
    monkeypatch.setattr(nm3u8dl, "_get_nm3u8dl_path", lambda: None)

    calls = []
    res = nm3u8dl.nm3u8dl_download(
        "http://host/x.m3u8", str(tmp_path), "ep",
        callback=lambda p, t: calls.append((p, t)),
    )

    assert res is None
    assert len(calls) == 1
    assert calls[0][0] == 0.0
    assert "manquant" in calls[0][1]


def test_nm3u8dl_download_invalid_url_returns_none_and_callback(tmp_path, monkeypatch):
    monkeypatch.setattr(nm3u8dl, "_get_nm3u8dl_path", lambda: "N_m3u8DL-RE")

    calls = []
    res = nm3u8dl.nm3u8dl_download(
        "ftp://host/x", str(tmp_path), "ep",
        callback=lambda p, t: calls.append((p, t)),
    )

    assert res is None
    assert calls == [(0.0, "❌ URL invalide")]


def test_nm3u8dl_download_empty_nom_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(nm3u8dl, "_get_nm3u8dl_path", lambda: "N_m3u8DL-RE")

    res = nm3u8dl.nm3u8dl_download("http://host/x.m3u8", str(tmp_path), "")

    assert res is None


def test_nm3u8dl_download_empty_dossier_returns_none(monkeypatch):
    monkeypatch.setattr(nm3u8dl, "_get_nm3u8dl_path", lambda: "N_m3u8DL-RE")

    res = nm3u8dl.nm3u8dl_download("http://host/x.m3u8", "", "ep")

    assert res is None


def test_nm3u8dl_construire_commande_quality_filter_and_referer_cookie(tmp_path):
    tmp_dir = os.path.join(str(tmp_path), "_tmp_ep")
    cmd = nm3u8dl_parsing.construire_commande(
        "N_m3u8DL-RE", "http://host/x.m3u8", str(tmp_path), "ep", tmp_dir,
        {"referer": "http://ref/", "cookie": "sid=1"},
        {"qualite": "720", "thread_count": 8},
    )

    assert _adjacent(cmd, "-sv", "res=x720:for=best")
    assert _adjacent(cmd, "-sa", "best")
    assert "--video-filter" not in cmd
    assert "--auto-select" not in cmd
    assert _adjacent(cmd, "--thread-count", "8")
    assert _adjacent(cmd, "--header", "Referer: http://ref/")
    assert _adjacent(cmd, "--header", "Cookie: sid=1")
    assert _adjacent(cmd, "--save-name", "ep")
    assert _adjacent(cmd, "--tmp-dir", tmp_dir)


def test_nm3u8dl_construire_commande_auto_select_and_default_threads(tmp_path):
    tmp_dir = os.path.join(str(tmp_path), "_tmp_ep")
    cmd = nm3u8dl_parsing.construire_commande(
        "N_m3u8DL-RE", "http://host/x.m3u8", str(tmp_path), "ep", tmp_dir,
        {}, {"qualite": "auto"},
    )

    assert "--auto-select" in cmd
    assert "--video-filter" not in cmd
    assert _adjacent(cmd, "--thread-count", "16")
    assert _adjacent(cmd, "--header", f"User-Agent: {DEFAULT_USER_AGENT}")
    assert "Referer: " not in " ".join(cmd)


def test_nm3u8dl_construire_commande_origin_used_as_referer(tmp_path):
    tmp_dir = os.path.join(str(tmp_path), "_tmp_ep")
    cmd = nm3u8dl_parsing.construire_commande(
        "N_m3u8DL-RE", "http://host/x.m3u8", str(tmp_path), "ep", tmp_dir,
        {"origin": "http://orig/"}, {"qualite": "auto"},
    )

    assert _adjacent(cmd, "--header", "Referer: http://orig/")


def test_nm3u8dl_get_thread_count_clamped_and_invalid():
    assert nm3u8dl_parsing.get_thread_count({"thread_count": 999}) == "32"
    assert nm3u8dl_parsing.get_thread_count({"thread_count": 0}) == "1"
    assert nm3u8dl_parsing.get_thread_count({"thread_count": "bad"}) == "16"
