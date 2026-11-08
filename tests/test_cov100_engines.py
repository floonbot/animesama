import importlib
import subprocess
import threading

import pytest

import engine.config.settings as settings_mod
import engine.config.user_settings as user_settings
import engine.download.methods._nm3u8dl_parsing as nm3u8dl_parsing
import engine.scraping.scan as scan_mod
from engine.domain.exceptions import DownloadCancelled
from engine.download.methods import (
    _ffmpeg_parsing,
    _ytdlp_parsing,
    ffmpeg_engine,
    images,
    ytdlp_engine,
)


@pytest.fixture(autouse=True)
def _snapshot_engine_globals():
    ff_path = ffmpeg_engine._FFMPEG_PATH
    ff_taille = ffmpeg_engine.TAILLE_MIN_FICHIER
    yt_path = ytdlp_engine._YTDLP_PATH
    aria_path = ytdlp_engine._ARIA2C_PATH
    yt_taille = ytdlp_engine.TAILLE_MIN_FICHIER
    img_safe = images.is_safe_url
    img_max = images.IMG_MAX_BYTES
    img_retries = images.PAGE_RETRIES
    yield
    ffmpeg_engine._FFMPEG_PATH = ff_path
    ffmpeg_engine.TAILLE_MIN_FICHIER = ff_taille
    ytdlp_engine._YTDLP_PATH = yt_path
    ytdlp_engine._ARIA2C_PATH = aria_path
    ytdlp_engine.TAILLE_MIN_FICHIER = yt_taille
    images.is_safe_url = img_safe
    images.IMG_MAX_BYTES = img_max
    images.PAGE_RETRIES = img_retries


class _ListPipe:
    def __init__(self, items):
        self._items = list(items)

    def __iter__(self):
        return iter(self._items)


class _FakeProc:
    def __init__(
        self,
        stdout_lines=None,
        stderr_lines=None,
        returncode=0,
        poll_value=None,
        wait_script=None,
        kill_raises=False,
    ):
        self.returncode = returncode
        self.pid = 4321
        self._poll_value = poll_value
        self._wait_script = list(wait_script) if wait_script else []
        self._kill_raises = kill_raises
        self.wait_calls = []
        self.kill_calls = 0
        self.stdout = None if stdout_lines is None else _ListPipe(stdout_lines)
        self.stderr = None if stderr_lines is None else _ListPipe(stderr_lines)

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        if self._wait_script:
            action = self._wait_script.pop(0)
            if action == "timeout":
                raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout or 0)
            if action == "boom":
                raise RuntimeError("wait exploded")
        return self.returncode

    def poll(self):
        return self._poll_value

    def kill(self):
        self.kill_calls += 1
        if self._kill_raises:
            raise OSError("kill failed")

    def terminate(self):
        return None


class _FakePopenFactory:
    def __init__(self, proc):
        self.proc = proc
        self.cmd = None
        self.kwargs = None

    def __call__(self, cmd, *args, **kwargs):
        self.cmd = list(cmd)
        self.kwargs = kwargs
        return self.proc


class _FixedClock:
    def __init__(self, value=1000.0):
        self.value = value

    def __call__(self):
        return self.value


def _ecriture_directe():
    raise OSError("ecriture directe")


def _neutralize(monkeypatch, module):
    monkeypatch.setattr(module, "_spawn_proc_watchdog", lambda *a, **k: threading.Event())
    monkeypatch.setattr(module, "register_proc", lambda *a, **k: None)
    monkeypatch.setattr(module, "unregister_proc", lambda *a, **k: None)
    # Ces tests visent l'analyse de la sortie des moteurs : ecriture directe.
    # Le passage par un dossier local : test_ecriture_locale_puis_livraison.py.
    if hasattr(module, "creer_dossier_de_travail"):
        monkeypatch.setattr(module, "creer_dossier_de_travail", _ecriture_directe)


def test_find_ffmpeg_oserror_in_loop_falls_back_to_which(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_mod, "ROOT_DIR", tmp_path)

    def _exists_boom(_p):
        raise OSError("stat denied")

    monkeypatch.setattr(ffmpeg_engine.os.path, "exists", _exists_boom)
    which_seen = []
    monkeypatch.setattr(
        ffmpeg_engine.shutil, "which", lambda n: which_seen.append(n) or "/usr/bin/ffmpeg"
    )

    res = ffmpeg_engine._find_ffmpeg()

    assert res == "/usr/bin/ffmpeg"
    assert which_seen == ["ffmpeg"]


def test_find_ffmpeg_no_match_returns_which(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_mod, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(ffmpeg_engine.os.path, "exists", lambda p: False)
    monkeypatch.setattr(ffmpeg_engine.shutil, "which", lambda n: None)

    assert ffmpeg_engine._find_ffmpeg() is None


def test_get_ffmpeg_path_researches_when_cache_stale(monkeypatch):
    ffmpeg_engine._FFMPEG_PATH = "/stale/ffmpeg"
    monkeypatch.setattr(ffmpeg_engine.os.path, "exists", lambda p: False)
    monkeypatch.setattr(ffmpeg_engine, "_find_ffmpeg", lambda: "/fresh/ffmpeg")

    assert ffmpeg_engine._get_ffmpeg_path() == "/fresh/ffmpeg"
    assert ffmpeg_engine._FFMPEG_PATH == "/fresh/ffmpeg"


def test_ffmpeg_module_else_branch_logs_when_introuvable(monkeypatch, caplog):
    import os as _os
    import shutil as _shutil

    monkeypatch.setattr(_shutil, "which", lambda n: None)
    monkeypatch.setattr(_os.path, "exists", lambda p: False)
    try:
        with caplog.at_level("DEBUG", logger="engine.download.methods.ffmpeg_engine"):
            reloaded = importlib.reload(ffmpeg_engine)
        assert reloaded._FFMPEG_PATH is None
        assert "ffmpeg introuvable" in caplog.text
    finally:
        monkeypatch.undo()
        importlib.reload(ffmpeg_engine)


def test_ffmpeg_stdout_reader_exception_is_swallowed(tmp_path, monkeypatch):
    sortie = tmp_path / "ep.mp4"
    sortie.write_bytes(b"y" * 64)

    proc = _FakeProc(
        stdout_lines=["out_time=00:00:05", "boom-line"],
        stderr_lines=[],
        returncode=0,
        poll_value=0,
    )
    factory = _FakePopenFactory(proc)
    monkeypatch.setattr(ffmpeg_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg_engine, "_estimer_duree_hls", lambda *a: 0.0)
    monkeypatch.setattr(ffmpeg_engine, "TAILLE_MIN_FICHIER", 1)
    monkeypatch.setattr(ffmpeg_engine.time, "time", _FixedClock())

    def _boom_parse(line, state):
        raise ValueError("cannot parse")

    monkeypatch.setattr(ffmpeg_engine, "_parse_progress_line", _boom_parse)
    _neutralize(monkeypatch, ffmpeg_engine)

    res = ffmpeg_engine.ffmpeg_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res == str(sortie)


def test_ffmpeg_empty_stderr_line_is_skipped(tmp_path, monkeypatch):
    sortie = tmp_path / "ep.mp4"
    sortie.write_bytes(b"y" * 64)

    proc = _FakeProc(
        stdout_lines=[],
        stderr_lines=["", "frame=1 fps=1"],
        returncode=0,
        poll_value=0,
    )
    factory = _FakePopenFactory(proc)
    monkeypatch.setattr(ffmpeg_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg_engine, "_estimer_duree_hls", lambda *a: 0.0)
    monkeypatch.setattr(ffmpeg_engine, "TAILLE_MIN_FICHIER", 1)
    monkeypatch.setattr(ffmpeg_engine.time, "time", _FixedClock())
    _neutralize(monkeypatch, ffmpeg_engine)

    res = ffmpeg_engine.ffmpeg_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res == str(sortie)


def test_ffmpeg_cancel_detected_after_stderr_eof(tmp_path, monkeypatch):
    sortie = tmp_path / "ep.mp4"
    sortie.write_bytes(b"y" * 64)

    proc = _FakeProc(
        stdout_lines=[],
        stderr_lines=[],
        returncode=0,
        poll_value=0,
    )
    factory = _FakePopenFactory(proc)
    monkeypatch.setattr(ffmpeg_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg_engine, "_estimer_duree_hls", lambda *a: 0.0)
    monkeypatch.setattr(ffmpeg_engine, "TAILLE_MIN_FICHIER", 1)
    monkeypatch.setattr(ffmpeg_engine, "_terminate_tree", lambda p: None)
    monkeypatch.setattr(ffmpeg_engine.time, "time", _FixedClock())
    _neutralize(monkeypatch, ffmpeg_engine)

    with pytest.raises(DownloadCancelled):
        ffmpeg_engine.ffmpeg_download(
            "http://host/x.m3u8", str(tmp_path), "ep", cancelled=[True],
        )


def test_ffmpeg_undersized_remove_oserror_is_swallowed(tmp_path, monkeypatch):
    sortie = tmp_path / "ep.mp4"
    sortie.write_bytes(b"y" * 8)

    proc = _FakeProc(
        stdout_lines=[],
        stderr_lines=["frame=1 fps=1"],
        returncode=0,
        poll_value=0,
    )
    factory = _FakePopenFactory(proc)
    monkeypatch.setattr(ffmpeg_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg_engine, "_estimer_duree_hls", lambda *a: 0.0)
    monkeypatch.setattr(ffmpeg_engine, "TAILLE_MIN_FICHIER", 1024)
    monkeypatch.setattr(ffmpeg_engine.time, "time", _FixedClock())

    real_remove = ffmpeg_engine.os.remove
    removed = {"main": 0}

    def _remove(path):
        if path == str(sortie):
            removed["main"] += 1
            if removed["main"] == 1:
                raise OSError("locked during main body")
        return real_remove(path)

    monkeypatch.setattr(ffmpeg_engine.os, "remove", _remove)
    _neutralize(monkeypatch, ffmpeg_engine)

    res = ffmpeg_engine.ffmpeg_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res is None


def test_ffmpeg_finally_kill_fallback_and_remove_oserror(tmp_path, monkeypatch):
    sortie = tmp_path / "ep.mp4"
    sortie.write_bytes(b"y" * 8)

    proc = _FakeProc(
        stdout_lines=[],
        stderr_lines=["frame=1 fps=1"],
        returncode=1,
        poll_value=None,
        wait_script=["rc", "timeout"],
        kill_raises=True,
    )
    factory = _FakePopenFactory(proc)
    monkeypatch.setattr(ffmpeg_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg_engine, "_estimer_duree_hls", lambda *a: 0.0)
    monkeypatch.setattr(ffmpeg_engine, "TAILLE_MIN_FICHIER", 1024)
    monkeypatch.setattr(ffmpeg_engine, "_terminate_tree", lambda p: None)
    monkeypatch.setattr(ffmpeg_engine.time, "time", _FixedClock())

    def _getsize_boom(path):
        raise OSError("size unavailable")

    monkeypatch.setattr(ffmpeg_engine.os.path, "getsize", _getsize_boom)
    monkeypatch.setattr(ffmpeg_engine, "register_proc", lambda *a, **k: None)
    monkeypatch.setattr(ffmpeg_engine, "unregister_proc", lambda *a, **k: None)
    monkeypatch.setattr(ffmpeg_engine, "_spawn_proc_watchdog", lambda *a, **k: threading.Event())

    res = ffmpeg_engine.ffmpeg_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res is None
    assert proc.kill_calls == 1


def test_ffmpeg_finally_outer_exception_swallowed(tmp_path, monkeypatch):
    sortie = tmp_path / "ep.mp4"
    sortie.write_bytes(b"y" * 4096)

    proc = _FakeProc(
        stdout_lines=[],
        stderr_lines=["frame=1 fps=1"],
        returncode=1,
        poll_value=None,
        wait_script=["rc", "boom"],
    )
    factory = _FakePopenFactory(proc)
    monkeypatch.setattr(ffmpeg_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg_engine, "_estimer_duree_hls", lambda *a: 0.0)
    monkeypatch.setattr(ffmpeg_engine, "TAILLE_MIN_FICHIER", 1)
    monkeypatch.setattr(ffmpeg_engine, "_terminate_tree", lambda p: None)
    monkeypatch.setattr(ffmpeg_engine.time, "time", _FixedClock())
    monkeypatch.setattr(ffmpeg_engine, "register_proc", lambda *a, **k: None)
    monkeypatch.setattr(ffmpeg_engine, "unregister_proc", lambda *a, **k: None)
    monkeypatch.setattr(ffmpeg_engine, "_spawn_proc_watchdog", lambda *a, **k: threading.Event())

    res = ffmpeg_engine.ffmpeg_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res is None
    assert proc.kill_calls == 0


def test_find_exe_importerror_yields_no_roots(monkeypatch):
    import builtins as _b

    real_import = _b.__import__

    def _fake_import(name, glb=None, loc=None, fromlist=(), level=0):
        if name == "engine.config.settings" and fromlist and "ROOT_DIR" in fromlist:
            raise ImportError("settings unavailable")
        return real_import(name, glb, loc, fromlist, level)

    monkeypatch.setattr(ytdlp_engine.shutil, "which", lambda n: None)
    monkeypatch.setattr(_b, "__import__", _fake_import)

    res = ytdlp_engine._find_exe(["yt-dlp.exe", "yt-dlp"])

    assert res is None


def test_ytdlp_module_else_branches_log_when_absent(monkeypatch, caplog):
    import os as _os
    import shutil as _shutil

    monkeypatch.setattr(_shutil, "which", lambda n: None)
    monkeypatch.setattr(_os.path, "exists", lambda p: False)
    try:
        with caplog.at_level("DEBUG", logger="engine.download.methods.ytdlp_engine"):
            reloaded = importlib.reload(ytdlp_engine)
        assert reloaded._YTDLP_PATH is None
        assert reloaded._ARIA2C_PATH is None
        assert "yt-dlp introuvable" in caplog.text
        assert "aria2c non trouvé" in caplog.text
    finally:
        monkeypatch.undo()
        importlib.reload(ytdlp_engine)


def test_ytdlp_trouver_fichier_listdir_getsize_oserror(tmp_path, monkeypatch):
    monkeypatch.setattr(ytdlp_engine, "TAILLE_MIN_FICHIER", 50)
    candidate = tmp_path / "ep.partial.mkv"
    candidate.write_bytes(b"y" * 100)

    real_getsize = ytdlp_engine.os.path.getsize

    def _getsize(path):
        if path == str(candidate):
            raise OSError("size unavailable")
        return real_getsize(path)

    monkeypatch.setattr(ytdlp_engine.os.path, "getsize", _getsize)

    assert ytdlp_engine._trouver_fichier_final(str(tmp_path), "ep") is None


def test_ytdlp_empty_stdout_line_is_skipped(tmp_path, monkeypatch):
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"x" * 64)

    proc = _FakeProc(stdout_lines=["", "[download]  10.0%"], returncode=0, poll_value=0)
    factory = _FakePopenFactory(proc)
    monkeypatch.setattr(ytdlp_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp_engine, "_get_aria2c_path", lambda: None)
    monkeypatch.setattr(ytdlp_engine, "_trouver_fichier_final", lambda d, n, avant=None: str(final))
    monkeypatch.setattr(user_settings, "load_settings", lambda: {"qualite": "auto"})
    _neutralize(monkeypatch, ytdlp_engine)

    res = ytdlp_engine.ytdlp_download("http://host/v", str(tmp_path), "ep")

    assert res == str(final)


def test_ytdlp_cancel_detected_after_stdout_eof(tmp_path, monkeypatch):
    proc = _FakeProc(stdout_lines=[], returncode=0, poll_value=0)
    factory = _FakePopenFactory(proc)
    monkeypatch.setattr(ytdlp_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp_engine, "_get_aria2c_path", lambda: None)
    monkeypatch.setattr(ytdlp_engine, "_trouver_fichier_final", lambda d, n, avant=None: None)
    monkeypatch.setattr(ytdlp_engine, "_terminate_tree", lambda p: None)
    monkeypatch.setattr(user_settings, "load_settings", lambda: {"qualite": "auto"})
    _neutralize(monkeypatch, ytdlp_engine)

    with pytest.raises(DownloadCancelled):
        ytdlp_engine.ytdlp_download(
            "http://host/v", str(tmp_path), "ep", cancelled=[True],
        )


def test_ytdlp_zero_rc_but_file_missing_logs_warning(tmp_path, monkeypatch, caplog):
    proc = _FakeProc(stdout_lines=["[download] 100%"], returncode=0, poll_value=0)
    factory = _FakePopenFactory(proc)
    monkeypatch.setattr(ytdlp_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp_engine, "_get_aria2c_path", lambda: None)
    monkeypatch.setattr(ytdlp_engine, "_trouver_fichier_final", lambda d, n, avant=None: None)
    monkeypatch.setattr(user_settings, "load_settings", lambda: {"qualite": "auto"})
    _neutralize(monkeypatch, ytdlp_engine)

    with caplog.at_level("WARNING", logger="engine.download.methods.ytdlp_engine"):
        res = ytdlp_engine.ytdlp_download("http://host/v", str(tmp_path), "ep")

    assert res is None
    assert "fichier introuvable" in caplog.text


def test_ytdlp_generic_exception_in_body_returns_none(tmp_path, monkeypatch):
    proc = _FakeProc(stdout_lines=["[download]  10.0%"], returncode=0, poll_value=0)
    factory = _FakePopenFactory(proc)
    monkeypatch.setattr(ytdlp_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp_engine, "_get_aria2c_path", lambda: None)
    monkeypatch.setattr(user_settings, "load_settings", lambda: {"qualite": "auto"})

    def _boom(d, n, avant=None):
        raise ValueError("lookup exploded")

    monkeypatch.setattr(ytdlp_engine, "_trouver_fichier_final", _boom)
    _neutralize(monkeypatch, ytdlp_engine)

    res = ytdlp_engine.ytdlp_download("http://host/v", str(tmp_path), "ep")

    assert res is None


def test_ytdlp_finally_kill_failure_swallowed(tmp_path, monkeypatch):
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"x" * 64)

    proc = _FakeProc(
        stdout_lines=["[download]  10.0%"],
        returncode=0,
        poll_value=None,
        wait_script=["rc", "timeout"],
        kill_raises=True,
    )
    factory = _FakePopenFactory(proc)
    monkeypatch.setattr(ytdlp_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp_engine, "_get_aria2c_path", lambda: None)
    monkeypatch.setattr(ytdlp_engine, "_trouver_fichier_final", lambda d, n, avant=None: str(final))
    monkeypatch.setattr(ytdlp_engine, "_terminate_tree", lambda p: None)
    monkeypatch.setattr(user_settings, "load_settings", lambda: {"qualite": "auto"})
    monkeypatch.setattr(ytdlp_engine, "register_proc", lambda *a, **k: None)
    monkeypatch.setattr(ytdlp_engine, "unregister_proc", lambda *a, **k: None)
    monkeypatch.setattr(ytdlp_engine, "_spawn_proc_watchdog", lambda *a, **k: threading.Event())

    res = ytdlp_engine.ytdlp_download("http://host/v", str(tmp_path), "ep")

    assert res == str(final)
    assert proc.kill_calls == 1


def test_ytdlp_finally_outer_exception_swallowed(tmp_path, monkeypatch):
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"x" * 64)

    proc = _FakeProc(
        stdout_lines=["[download]  10.0%"],
        returncode=0,
        poll_value=None,
        wait_script=["rc", "boom"],
    )
    factory = _FakePopenFactory(proc)
    monkeypatch.setattr(ytdlp_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp_engine, "_get_aria2c_path", lambda: None)
    monkeypatch.setattr(ytdlp_engine, "_trouver_fichier_final", lambda d, n, avant=None: str(final))
    monkeypatch.setattr(ytdlp_engine, "_terminate_tree", lambda p: None)
    monkeypatch.setattr(user_settings, "load_settings", lambda: {"qualite": "auto"})
    monkeypatch.setattr(ytdlp_engine, "register_proc", lambda *a, **k: None)
    monkeypatch.setattr(ytdlp_engine, "unregister_proc", lambda *a, **k: None)
    monkeypatch.setattr(ytdlp_engine, "_spawn_proc_watchdog", lambda *a, **k: threading.Event())

    res = ytdlp_engine.ytdlp_download("http://host/v", str(tmp_path), "ep")

    assert res == str(final)
    assert proc.kill_calls == 0


class _ScriptedSession:
    def __init__(self, script):
        self._script = list(script)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class _ImgResp:
    def __init__(self, status_code, content_type=None, chunks=()):
        self.status_code = status_code
        self.headers = {"Content-Type": content_type} if content_type is not None else {}
        self._chunks = list(chunks)
        self.closed = False

    def iter_content(self, n):
        yield from self._chunks

    def close(self):
        self.closed = True


def test_est_annule_list_index_error_returns_false():
    assert images._est_annule([]) is False


def test_telecharger_image_empty_chunk_skipped(monkeypatch):
    monkeypatch.setattr(images, "is_safe_url", lambda url: True)
    resp = _ImgResp(200, "image/png", [b"", b"AB", b"", b"CD"])
    session = _ScriptedSession([resp])

    out = images._telecharger_image(session, "https://h/p.png")

    assert out == (b"ABCD", ".png")
    assert resp.closed is True


def test_telecharger_image_empty_data_returns_none(monkeypatch):
    monkeypatch.setattr(images, "is_safe_url", lambda url: True)
    resp = _ImgResp(200, "image/png", [b"", b""])
    session = _ScriptedSession([resp])

    out = images._telecharger_image(session, "https://h/p.png")

    assert out is None
    assert resp.closed is True


def test_scan_download_httpadapter_failure_is_logged(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(scan_mod, "get_pages_sync", lambda *a, **k: [{"page": 1, "url": "https://h/p.jpg"}])
    monkeypatch.setattr(images, "_telecharger_image", lambda *a, **k: (b"IMG", ".jpg"))

    import requests.adapters as adapters_mod

    def _boom(*a, **k):
        raise RuntimeError("adapter init failed")

    monkeypatch.setattr(adapters_mod, "HTTPAdapter", _boom)

    with caplog.at_level("DEBUG", logger="engine.download.scan_images"):
        res = images.scan_download("oeuvre", "vf", ["1"], str(tmp_path))

    import os
    assert res == os.path.join(str(tmp_path), "Chapitre 1.cbz")
    assert "HTTPAdapter non configuré" in caplog.text


def test_scan_download_inner_page_cancel_cleans_part(tmp_path, monkeypatch):
    monkeypatch.setattr(
        scan_mod, "get_pages_sync",
        lambda *a, **k: [{"page": 1, "url": "https://h/p1.jpg"}],
    )
    monkeypatch.setattr(images, "_telecharger_image", lambda *a, **k: (b"IMG", ".jpg"))

    class _Token:
        def __init__(self):
            self.checks = 0

        def is_cancelled(self):
            self.checks += 1
            return self.checks >= 2

    import os
    with pytest.raises(DownloadCancelled):
        images.scan_download(
            "oeuvre", "vf", ["1"], str(tmp_path), cancelled=_Token()
        )

    assert not os.path.exists(os.path.join(str(tmp_path), "Chapitre 1.cbz.part"))


def test_scan_download_part_remove_oserror_swallowed(tmp_path, monkeypatch):
    monkeypatch.setattr(
        scan_mod, "get_pages_sync",
        lambda *a, **k: [{"page": 1, "url": "https://h/p1.jpg"}],
    )
    monkeypatch.setattr(images, "_telecharger_image", lambda *a, **k: None)

    real_remove = images.os.remove

    def _remove(path):
        if path.endswith(".part"):
            raise OSError("locked part file")
        return real_remove(path)

    monkeypatch.setattr(images.os, "remove", _remove)

    result = images.scan_download("oeuvre", "vf", ["1"], str(tmp_path))
    assert result is None


class _FakeSession:
    def __init__(self):
        self.headers = {}
        self.closed_attempts = 0

    def mount(self, prefix, adapter):
        return None

    def close(self):
        self.closed_attempts += 1
        raise RuntimeError("close failed")


def test_scan_download_session_close_failure_swallowed(tmp_path, monkeypatch):
    monkeypatch.setattr(scan_mod, "get_pages_sync", lambda *a, **k: [])

    failing = _FakeSession()
    monkeypatch.setattr(images.requests, "Session", lambda: failing)

    res = images.scan_download("oeuvre", "vf", ["1"], str(tmp_path))

    assert res is None
    assert failing.closed_attempts == 1


def test_ffmpeg_parsing_size_units_and_bitrate():
    st = _ffmpeg_parsing.ProgressState()
    st.total_size = 2 * 1024 * 1024 * 1024
    st.bitrate = 800.0
    st.speed = 0.0
    _pct, txt = _ffmpeg_parsing.construire_texte_progress(st, 0.0)
    assert "GB" in txt
    assert "800 kb/s" in txt

    st2 = _ffmpeg_parsing.ProgressState()
    st2.total_size = 500
    st2.bitrate = 0.0
    st2.speed = 0.0
    _pct2, txt2 = _ffmpeg_parsing.construire_texte_progress(st2, 0.0)
    assert "KB" in txt2
    assert "kb/s" not in txt2


def test_ffmpeg_parsing_mb_size_and_speed_suffix():
    st = _ffmpeg_parsing.ProgressState()
    st.total_size = 5 * 1024 * 1024
    st.bitrate = 0.0
    st.speed = 2.5
    _pct, txt = _ffmpeg_parsing.construire_texte_progress(st, 0.0)
    assert "MB" in txt
    assert txt.endswith("2.5x")


def test_ytdlp_parsing_get_domain_exception_returns_empty(monkeypatch):
    def _boom(_u):
        raise ValueError("bad url")

    monkeypatch.setattr(_ytdlp_parsing, "urlparse", _boom)

    assert _ytdlp_parsing.get_domain("http://host/v") == ""


def test_ytdlp_parsing_insecure_env_adds_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("YTDLP_INSECURE", "yes")
    cmd = _ytdlp_parsing.construire_commande(
        "yt-dlp", "http://host/v", str(tmp_path), "ep", {}, qualite="auto",
    )
    assert "--no-check-certificates" in cmd


def test_nm3u8dl_parsing_segments_total_value_error_swallowed(monkeypatch):
    state = {"phase": "init", "total_segs": 0}

    class _BadMatch:
        def group(self, _n):
            return "not-an-int"

    class _Re:
        def search(self, _ligne):
            return _BadMatch()

    monkeypatch.setattr(nm3u8dl_parsing, "RE_SEGMENTS", _Re())
    nm3u8dl_parsing.interpreter_ligne("250 Segments", state, None)

    assert state["total_segs"] == 0
    assert state["phase"] == "downloading"
