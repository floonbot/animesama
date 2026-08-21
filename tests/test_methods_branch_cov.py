import os

import pytest

import engine.config.user_settings as user_settings
import engine.download.methods.nm3u8dl as nm3u8dl
import engine.scraping.scan as scan_mod
from engine.domain.exceptions import UnsafeUrlError
from engine.download.methods import (
    _nm3u8dl_parsing,
    ffmpeg_engine,
    images,
    ytdlp_engine,
)


@pytest.fixture(autouse=True)
def _snapshot_nm3u8dl_globals(monkeypatch):
    """Restaure les singletons de module nm3u8dl et neutralise time.sleep."""
    saved = (
        nm3u8dl._NM3U8DL_PATH,
        nm3u8dl._NM3U8DL_LAST_SEARCH_TS,
        nm3u8dl._settings_cache,
        nm3u8dl._settings_cache_ts,
    )
    monkeypatch.setattr(nm3u8dl.time, "sleep", lambda *_a, **_k: None)
    yield
    (
        nm3u8dl._NM3U8DL_PATH,
        nm3u8dl._NM3U8DL_LAST_SEARCH_TS,
        nm3u8dl._settings_cache,
        nm3u8dl._settings_cache_ts,
    ) = saved


@pytest.fixture(autouse=True)
def _snapshot_engine_globals():
    """Restaure les chemins d'exécutable singletons des moteurs ffmpeg/yt-dlp."""
    ff_path = ffmpeg_engine._FFMPEG_PATH
    yt_path = ytdlp_engine._YTDLP_PATH
    aria_path = ytdlp_engine._ARIA2C_PATH
    yield
    ffmpeg_engine._FFMPEG_PATH = ff_path
    ytdlp_engine._YTDLP_PATH = yt_path
    ytdlp_engine._ARIA2C_PATH = aria_path


def _dl_state(now=1000.0):
    return {
        "total_segs": 0,
        "start_time": now,
        "last_size": 0,
        "last_time": now,
        "speed_bps": 0.0,
        "phase": "init",
    }


class _ListPipe:
    def __init__(self, items):
        self._items = list(items)

    def __iter__(self):
        return iter(self._items)


class _FakeProc:
    def __init__(self, stdout_lines=None, stderr_lines=None, returncode=0, poll_value=None):
        self.returncode = returncode
        self.pid = 7777
        self._poll_value = poll_value
        self.kill_calls = 0
        self.wait_calls = []
        self.stdout = None if stdout_lines is None else _ListPipe(stdout_lines)
        self.stderr = None if stderr_lines is None else _ListPipe(stderr_lines)

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        return self.returncode

    def poll(self):
        return self._poll_value

    def kill(self):
        self.kill_calls += 1

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
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


def _neutralize(monkeypatch, module):
    import threading

    monkeypatch.setattr(module, "_spawn_proc_watchdog", lambda *a, **k: threading.Event())
    monkeypatch.setattr(module, "register_proc", lambda *a, **k: None)
    monkeypatch.setattr(module, "unregister_proc", lambda *a, **k: None)


def test_get_nm3u8dl_path_late_search_misses_returns_none(monkeypatch):
    """116->118 : recherche tardive échouée saute le log debug et renvoie None."""
    nm3u8dl._NM3U8DL_PATH = None
    nm3u8dl._NM3U8DL_LAST_SEARCH_TS = 0.0
    monkeypatch.setattr(nm3u8dl.time, "time", _FixedClock(10_000.0))
    monkeypatch.setattr(nm3u8dl, "_find_nm3u8dl", lambda: None)

    assert nm3u8dl._get_nm3u8dl_path() is None
    assert nm3u8dl._NM3U8DL_PATH is None


def test_preparer_no_exe_without_callback_returns_none(monkeypatch, tmp_path):
    """283->288 : exe absent et callback None saute le bloc callback puis renvoie None."""
    monkeypatch.setattr(nm3u8dl, "_get_nm3u8dl_path", lambda: None)

    res = nm3u8dl._preparer_nm3u8dl(
        "http://host/x.m3u8", str(tmp_path), "ep", None, None
    )

    assert res is None


def test_preparer_invalid_url_without_callback_returns_none(monkeypatch, tmp_path):
    """292->297 : URL non-http et callback None saute le bloc callback puis renvoie None."""
    monkeypatch.setattr(nm3u8dl, "_get_nm3u8dl_path", lambda: "N_m3u8DL-RE")

    res = nm3u8dl._preparer_nm3u8dl(
        "ftp://host/x", str(tmp_path), "ep", None, None
    )

    assert res is None


def test_preparer_makedirs_oserror_without_callback_returns_none(monkeypatch, tmp_path):
    """311->316 : makedirs en échec et callback None saute le bloc callback puis renvoie None."""
    monkeypatch.setattr(nm3u8dl, "_get_nm3u8dl_path", lambda: "N_m3u8DL-RE")
    monkeypatch.setattr(nm3u8dl, "_get_user_settings", lambda: {})

    def _boom(path, *a, **k):
        raise OSError("read-only")

    monkeypatch.setattr(nm3u8dl.os, "makedirs", _boom)

    res = nm3u8dl._preparer_nm3u8dl(
        "http://host/x.m3u8", str(tmp_path), "ep", None, None
    )

    assert res is None


def test_download_popen_raises_finally_handles_all_none(tmp_path, monkeypatch):
    """431->433, 434->441, 441->461 : Popen échoue, watchdog/monitor/proc restent None."""
    monkeypatch.setattr(nm3u8dl, "_get_nm3u8dl_path", lambda: "N_m3u8DL-RE")
    monkeypatch.setattr(nm3u8dl, "_get_user_settings", lambda: {})
    monkeypatch.setattr(nm3u8dl, "register_proc", lambda *a, **k: None)
    monkeypatch.setattr(nm3u8dl, "unregister_proc", lambda *a, **k: None)

    def _boom(*a, **k):
        raise ValueError("popen exploded before assignment")

    monkeypatch.setattr(nm3u8dl.subprocess, "Popen", _boom)

    tmp_dir = tmp_path / "_tmp_ep"
    tmp_dir.mkdir()

    res = nm3u8dl.nm3u8dl_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res is None
    assert tmp_dir.exists()


def test_monitor_tmp_returns_immediately_when_already_stopped(tmp_path):
    """475->exit : stop déjà positionné fait sortir la boucle sans aucun tour."""
    state = _dl_state()

    class _Stop:
        def is_set(self):
            return True

        def wait(self, _timeout=None):
            raise AssertionError("wait must not run when already stopped")

    nm3u8dl._monitor_tmp(str(tmp_path), state, _Stop(), None)


def test_monitor_tmp_non_regular_file_is_skipped(tmp_path):
    """Une entrée non-fichier portant une extension de segment n'est pas comptabilisée."""
    state = _dl_state()
    target = tmp_path / "_tmp_ep"
    target.mkdir()
    (target / "seg0.ts").mkdir()

    class _Stop:
        def __init__(self):
            self._set_seq = iter([False])

        def is_set(self):
            return next(self._set_seq, True)

        def wait(self, _timeout=None):
            return True

    nm3u8dl._monitor_tmp(str(target), state, _Stop(), None)

    assert state["last_size"] == 0


def test_monitor_tmp_progress_without_dt_and_without_eta(tmp_path, monkeypatch):
    """506->512, 518->520, 525->475 : dt<1.0 saute la vitesse, ETA vide, puis reboucle."""
    now = 5000.0
    state = _dl_state(now)
    state["total_segs"] = 4
    state["phase"] = "downloading"
    target = tmp_path / "_tmp_ep"
    target.mkdir()
    (target / "seg0.ts").write_bytes(b"x" * 16)

    monkeypatch.setattr(nm3u8dl.time, "time", _FixedClock(now))

    class _Stop:
        def __init__(self):
            self._set_seq = iter([False, True])
            self._wait_seq = iter([False])

        def is_set(self):
            return next(self._set_seq, True)

        def wait(self, _timeout=None):
            return next(self._wait_seq, True)

    calls = []
    nm3u8dl._monitor_tmp(str(target), state, _Stop(), lambda p, t: calls.append((p, t)))

    assert calls
    pct, ligne = calls[0]
    assert pct == 25.0
    assert "ETA" not in ligne
    assert state["last_size"] == 0


def test_remux_mkdtemp_raises_finally_tmpdir_none(monkeypatch, tmp_path):
    """592->598 : mkdtemp échoue, tmpdir reste None, le finally saute rmtree."""
    chemin = tmp_path / "ep.mp4"
    chemin.write_bytes(b"z" * 64)
    monkeypatch.setattr(nm3u8dl.shutil, "which", lambda n: "ffmpeg")

    import tempfile

    def _boom(*a, **k):
        raise OSError("no temp space")

    monkeypatch.setattr(tempfile, "mkdtemp", _boom)

    def _no_rmtree(*a, **k):
        raise AssertionError("rmtree must not run when tmpdir is None")

    monkeypatch.setattr(nm3u8dl.shutil, "rmtree", _no_rmtree)

    res = nm3u8dl._remux_fix(str(chemin))

    assert res == str(chemin)


def test_nm3u8dl_parsing_segments_when_already_downloading(monkeypatch):
    """_nm3u8dl_parsing 75->79 : segments revus alors que la phase est déjà downloading."""
    state = {"phase": "downloading", "total_segs": 5}
    logged = []
    monkeypatch.setattr(_nm3u8dl_parsing.log, "info", lambda *a, **k: logged.append(a))

    _nm3u8dl_parsing.interpreter_ligne("Total 12 Segments found", state, None)

    assert state["total_segs"] == 12
    assert state["phase"] == "downloading"
    assert logged == []


def test_nm3u8dl_parsing_merge_when_already_merging():
    """_nm3u8dl_parsing 80->83 : merge revu alors que la phase est déjà merging."""
    calls = []
    state = {"phase": "merging", "total_segs": 5}
    cb = lambda p, t: calls.append((p, t))

    _nm3u8dl_parsing.interpreter_ligne("Binary merging parts", state, cb)

    assert state["phase"] == "merging"
    assert (96.0, "🔧 Assemblage des segments…") in calls


def test_ffmpeg_blank_stdout_line_is_skipped(tmp_path, monkeypatch):
    """ffmpeg 141->139 : ligne stdout vide ignorée sans appel au parseur."""
    sortie = tmp_path / "ep.mp4"
    sortie.write_bytes(b"y" * 64)

    proc = _FakeProc(
        stdout_lines=["", "out_time=00:00:01"],
        stderr_lines=[],
        returncode=0,
        poll_value=0,
    )
    factory = _FakePopenFactory(proc)
    monkeypatch.setattr(ffmpeg_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg_engine, "_estimer_duree_hls", lambda *a: 0.0)
    monkeypatch.setattr(ffmpeg_engine, "TAILLE_MIN_FICHIER", 1)
    monkeypatch.setattr(ffmpeg_engine.time, "time", _FixedClock(2000.0))

    parsed = []

    def _parse(line, state):
        parsed.append(line)

    monkeypatch.setattr(ffmpeg_engine, "_parse_progress_line", _parse)
    _neutralize(monkeypatch, ffmpeg_engine)

    res = ffmpeg_engine.ffmpeg_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res == str(sortie)
    assert "" not in parsed
    assert parsed == ["out_time=00:00:01"]


def test_ffmpeg_no_stderr_pipe_skips_loop(tmp_path, monkeypatch):
    """ffmpeg 176->196 : stderr absent saute la boucle de progression."""
    sortie = tmp_path / "ep.mp4"
    sortie.write_bytes(b"y" * 64)

    proc = _FakeProc(
        stdout_lines=[],
        stderr_lines=None,
        returncode=0,
        poll_value=0,
    )
    factory = _FakePopenFactory(proc)
    monkeypatch.setattr(ffmpeg_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg_engine, "_estimer_duree_hls", lambda *a: 0.0)
    monkeypatch.setattr(ffmpeg_engine, "TAILLE_MIN_FICHIER", 1)
    monkeypatch.setattr(ffmpeg_engine.time, "time", _FixedClock(2000.0))
    _neutralize(monkeypatch, ffmpeg_engine)

    res = ffmpeg_engine.ffmpeg_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res == str(sortie)


def test_ytdlp_trouver_fichier_listdir_prefix_mismatch_skipped(tmp_path, monkeypatch):
    """ytdlp 105->104 : un fichier au préfixe différent est ignoré et la boucle continue."""
    monkeypatch.setattr(ytdlp_engine, "TAILLE_MIN_FICHIER", 10)
    (tmp_path / "autrefilm.mp4").write_bytes(b"y" * 100)

    assert ytdlp_engine._trouver_fichier_final(str(tmp_path), "ep") is None


def test_ytdlp_no_stdout_pipe_skips_loop(tmp_path, monkeypatch):
    """ytdlp 189->217 : stdout absent saute la boucle de lecture."""
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"x" * 64)

    proc = _FakeProc(stdout_lines=None, returncode=0, poll_value=0)
    factory = _FakePopenFactory(proc)
    monkeypatch.setattr(ytdlp_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp_engine, "_get_aria2c_path", lambda: None)
    monkeypatch.setattr(ytdlp_engine, "_trouver_fichier_final", lambda d, n: str(final))
    monkeypatch.setattr(user_settings, "load_settings", lambda: {"qualite": "auto"})
    _neutralize(monkeypatch, ytdlp_engine)

    res = ytdlp_engine.ytdlp_download("http://host/v", str(tmp_path), "ep")

    assert res == str(final)


def test_ytdlp_neutral_stdout_line_falls_through(tmp_path, monkeypatch):
    """ytdlp 214->190 : ligne neutre ne déclenche aucune branche et reboucle."""
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"x" * 64)

    proc = _FakeProc(
        stdout_lines=["[hls] Total fragments: 10"],
        returncode=0,
        poll_value=0,
    )
    factory = _FakePopenFactory(proc)
    monkeypatch.setattr(ytdlp_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp_engine, "_get_aria2c_path", lambda: None)
    monkeypatch.setattr(ytdlp_engine, "_trouver_fichier_final", lambda d, n: str(final))
    monkeypatch.setattr(user_settings, "load_settings", lambda: {"qualite": "auto"})
    _neutralize(monkeypatch, ytdlp_engine)

    calls = []
    res = ytdlp_engine.ytdlp_download(
        "http://host/v", str(tmp_path), "ep",
        callback=lambda p, t: calls.append((p, t)),
    )

    assert res == str(final)
    assert all(not t.startswith("[yt-dlp]") for _, t in calls)
    assert all(not t.startswith("[aria2c]") for _, t in calls)


def test_images_pin_target_unsafe_returns_none(monkeypatch):
    """images 69-70 : pin_target levant UnsafeUrlError loggue et renvoie None."""
    monkeypatch.setattr(images, "is_safe_url", lambda url: True)

    def _boom(_url):
        raise UnsafeUrlError("pinned host refused")

    monkeypatch.setattr(images, "pin_target", _boom)

    class _Session:
        def get(self, *a, **k):
            raise AssertionError("session.get must not run when pin is refused")

    out = images._telecharger_image(_Session(), "https://h/p.png")

    assert out is None


def test_scan_download_zip_open_failure_part_absent_reraises(tmp_path, monkeypatch):
    """images 182->186 : échec d'ouverture du zip, le .part n'existe pas, l'exception remonte."""
    monkeypatch.setattr(
        scan_mod, "get_pages_sync",
        lambda *a, **k: [{"page": 1, "url": "https://h/p1.jpg"}],
    )

    def _boom(*a, **k):
        raise RuntimeError("cannot open zip")

    monkeypatch.setattr(images.zipfile, "ZipFile", _boom)

    removed = []
    real_remove = images.os.remove

    def _remove(path):
        removed.append(path)
        return real_remove(path)

    monkeypatch.setattr(images.os, "remove", _remove)

    result = images.scan_download("oeuvre", "vf", ["1"], str(tmp_path))

    assert result is None
    assert not os.path.exists(os.path.join(str(tmp_path), "Chapitre 1.cbz.part"))
    assert removed == []