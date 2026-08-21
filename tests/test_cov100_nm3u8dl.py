import importlib
import subprocess
import tempfile

import pytest

import engine.config.logging_setup  # noqa: F401
import engine.config.settings as settings_mod
import engine.config.user_settings as user_settings
import engine.download.methods.nm3u8dl as nm3u8dl
from engine.domain.exceptions import DownloadCancelled

_queue_mod = nm3u8dl._queue_mod


@pytest.fixture(autouse=True)
def _snapshot_module_state(monkeypatch):
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


def _state(now=100.0):
    return {
        "total_segs": 0,
        "start_time": now,
        "last_size": 0,
        "last_time": now,
        "speed_bps": 0.0,
        "phase": "init",
    }


class _RaisingStdout:
    def __iter__(self):
        return self

    def __next__(self):
        raise RuntimeError("pipe exploded")

    def close(self):
        return None


class _ScriptedProc:
    def __init__(self, actions, poll_seq):
        self._actions = list(actions)
        self._poll_seq = list(poll_seq)
        self.stdout = None
        self.pid = 999

    def poll(self):
        if len(self._poll_seq) == 1:
            return self._poll_seq[0]
        return self._poll_seq.pop(0)

    def kill(self):
        return None

    def terminate(self):
        return None

    def wait(self, timeout=None):
        return 0


class _ScriptedQueue:
    actions = []

    def __init__(self):
        pass

    def put(self, item):
        return None

    def get(self, timeout=None):
        action = type(self).actions.pop(0)
        if action == "EMPTY":
            raise _queue_mod.Empty
        return action


def test_find_nm3u8dl_import_error_on_root_dir(monkeypatch):
    monkeypatch.delattr(settings_mod, "ROOT_DIR", raising=True)
    monkeypatch.setattr(nm3u8dl.sys, "argv", ["main.py"])
    monkeypatch.setattr(nm3u8dl.os.path, "exists", lambda p: False)
    monkeypatch.setattr(nm3u8dl.shutil, "which", lambda n: None)

    assert nm3u8dl._find_nm3u8dl() is None


def test_find_nm3u8dl_abspath_exception(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_mod, "ROOT_DIR", tmp_path)

    def _boom(_p):
        raise OSError("argv broken")

    monkeypatch.setattr(nm3u8dl.os.path, "abspath", _boom)
    monkeypatch.setattr(nm3u8dl.os.path, "exists", lambda p: False)
    monkeypatch.setattr(nm3u8dl.shutil, "which", lambda n: None)

    assert nm3u8dl._find_nm3u8dl() is None


def test_module_warns_when_exe_absent_on_reload(monkeypatch, caplog):
    monkeypatch.setattr(nm3u8dl.os.path, "exists", lambda p: False)
    monkeypatch.setattr(nm3u8dl.shutil, "which", lambda n: None)
    monkeypatch.setattr(settings_mod, "ROOT_DIR", "Z:/definitely/missing")
    saved_path = nm3u8dl._NM3U8DL_PATH
    saved_ts = nm3u8dl._NM3U8DL_LAST_SEARCH_TS
    saved_cache = nm3u8dl._settings_cache
    saved_cache_ts = nm3u8dl._settings_cache_ts
    try:
        with caplog.at_level("WARNING", logger="engine.download.methods.nm3u8dl"):
            importlib.reload(nm3u8dl)
        assert nm3u8dl._NM3U8DL_PATH is None
        assert "introuvable" in caplog.text
    finally:
        importlib.reload(nm3u8dl)
        nm3u8dl._NM3U8DL_PATH = saved_path
        nm3u8dl._NM3U8DL_LAST_SEARCH_TS = saved_ts
        nm3u8dl._settings_cache = saved_cache
        nm3u8dl._settings_cache_ts = saved_cache_ts


def test_get_nm3u8dl_path_inner_lock_returns_when_exists(monkeypatch):
    nm3u8dl._NM3U8DL_PATH = "/late/N_m3u8DL-RE"
    seq = iter([False, True])
    monkeypatch.setattr(nm3u8dl.os.path, "exists", lambda p: next(seq))

    def _boom():
        raise AssertionError("research must not run when inner check passes")

    monkeypatch.setattr(nm3u8dl, "_find_nm3u8dl", _boom)

    assert nm3u8dl._get_nm3u8dl_path() == "/late/N_m3u8DL-RE"


def test_get_user_settings_loads_and_caches(monkeypatch):
    nm3u8dl._settings_cache = None
    nm3u8dl._settings_cache_ts = 0.0
    monkeypatch.setattr(
        user_settings, "load_settings", lambda: {"qualite": "1080", "thread_count": 8}
    )

    first = nm3u8dl._get_user_settings()

    assert first == {"qualite": "1080", "thread_count": 8}
    assert nm3u8dl._settings_cache == {"qualite": "1080", "thread_count": 8}

    def _boom():
        raise AssertionError("cache hit must not reload")

    monkeypatch.setattr(user_settings, "load_settings", _boom)
    second = nm3u8dl._get_user_settings()
    assert second == {"qualite": "1080", "thread_count": 8}
    assert second is not first


def test_get_user_settings_non_dict_falls_back(monkeypatch):
    nm3u8dl._settings_cache = None
    nm3u8dl._settings_cache_ts = 0.0
    monkeypatch.setattr(user_settings, "load_settings", lambda: ["not", "a", "dict"])

    res = nm3u8dl._get_user_settings()

    assert res == {"qualite": "auto", "thread_count": 16, "downloads_dir": ""}


def test_get_user_settings_exception_falls_back(monkeypatch):
    nm3u8dl._settings_cache = None
    nm3u8dl._settings_cache_ts = 0.0

    def _boom():
        raise RuntimeError("settings unreadable")

    monkeypatch.setattr(user_settings, "load_settings", _boom)

    res = nm3u8dl._get_user_settings()

    assert res == {"qualite": "auto", "thread_count": 16, "downloads_dir": ""}


def test_trouver_fichier_final_stat_oserror_continues(monkeypatch, tmp_path):
    """Un stat en échec ne doit ni remonter ni faire passer le fichier."""
    monkeypatch.setattr(nm3u8dl, "TAILLE_MIN_FICHIER", 1)
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"x" * 100)

    def _stat(_p, **k):
        raise OSError("stat failed")

    monkeypatch.setattr(nm3u8dl.os, "stat", _stat)

    assert nm3u8dl._trouver_fichier_final(str(tmp_path), "ep") is None


def test_purge_inner_getmtime_oserror_continues(monkeypatch, tmp_path):
    root = tmp_path / "dl"
    stale = root / "_tmp_old"
    stale.mkdir(parents=True)
    monkeypatch.setattr(settings_mod, "get_downloads_dir", lambda: root)
    monkeypatch.setattr(nm3u8dl.time, "time", lambda: 10_000_000.0)

    def _getmtime(_p):
        raise OSError("no mtime")

    monkeypatch.setattr(nm3u8dl.os.path, "getmtime", _getmtime)

    removed = []
    monkeypatch.setattr(
        nm3u8dl.shutil, "rmtree", lambda p, **k: removed.append(p)
    )

    assert nm3u8dl.purge_stale_tmp_dirs() == 0
    assert removed == []


def test_purge_outer_walk_oserror_returns_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_mod, "get_downloads_dir", lambda: tmp_path)

    def _walk(_root):
        raise OSError("walk failed")
        yield

    monkeypatch.setattr(nm3u8dl.os, "walk", _walk)

    assert nm3u8dl.purge_stale_tmp_dirs() == 0


def test_purge_removes_stale_dir(monkeypatch, tmp_path):
    root = tmp_path / "dl"
    stale = root / "_tmp_old"
    stale.mkdir(parents=True)
    keep = root / "_tmp_fresh"
    keep.mkdir()
    monkeypatch.setattr(settings_mod, "get_downloads_dir", lambda: root)
    monkeypatch.setattr(nm3u8dl.time, "time", lambda: 10_000_000.0)

    def _getmtime(p):
        if p.endswith("_tmp_old"):
            return 0.0
        return 9_999_999.0

    monkeypatch.setattr(nm3u8dl.os.path, "getmtime", _getmtime)
    removed = []
    monkeypatch.setattr(
        nm3u8dl.shutil, "rmtree", lambda p, **k: removed.append(p)
    )

    assert nm3u8dl.purge_stale_tmp_dirs() == 1
    assert removed == [str(stale)]


def test_reader_exception_is_logged_then_loop_breaks(monkeypatch):
    monkeypatch.setattr(nm3u8dl, "is_suspended", lambda _p: False)
    monkeypatch.setattr(nm3u8dl, "_terminate_tree", lambda _p: None)

    class _Proc:
        stdout = _RaisingStdout()

        def poll(self):
            return None

    proc = _Proc()
    state = _state()

    result = nm3u8dl._lire_stdout_avec_timeout(proc, None, None, state, timeout_s=3600)

    assert result is None


def test_suspended_without_cancel_sleeps_then_continues(monkeypatch):
    susp_seq = iter([True, True, False])
    monkeypatch.setattr(
        nm3u8dl, "is_suspended", lambda _p: next(susp_seq, False)
    )
    monkeypatch.setattr(nm3u8dl, "_terminate_tree", lambda _p: None)

    proc = _ScriptedProc([], poll_seq=[0])
    state = _state()

    _ScriptedQueue.actions = ["Done", None]
    monkeypatch.setattr(_queue_mod, "Queue", _ScriptedQueue)

    seen = []
    result = nm3u8dl._lire_stdout_avec_timeout(
        proc, [False], lambda p, t: seen.append((p, t)), state, timeout_s=3600
    )

    assert result is None
    assert state["phase"] == "done"


def test_empty_queue_then_cancel_raises(monkeypatch):
    monkeypatch.setattr(nm3u8dl, "is_suspended", lambda _p: False)
    terminated = []
    monkeypatch.setattr(nm3u8dl, "_terminate_tree", lambda p: terminated.append(p))

    proc = _ScriptedProc([], poll_seq=[None])
    state = _state()

    _ScriptedQueue.actions = ["EMPTY"]
    monkeypatch.setattr(_queue_mod, "Queue", _ScriptedQueue)

    with pytest.raises(DownloadCancelled):
        nm3u8dl._lire_stdout_avec_timeout(
            proc, [True], None, state, timeout_s=3600
        )

    assert terminated == [proc]


def test_empty_queue_proc_finished_breaks(monkeypatch):
    monkeypatch.setattr(nm3u8dl, "is_suspended", lambda _p: False)
    monkeypatch.setattr(nm3u8dl, "_terminate_tree", lambda _p: None)

    proc = _ScriptedProc([], poll_seq=[0])
    state = _state()

    _ScriptedQueue.actions = ["EMPTY"]
    monkeypatch.setattr(_queue_mod, "Queue", _ScriptedQueue)

    result = nm3u8dl._lire_stdout_avec_timeout(
        proc, [False], None, state, timeout_s=3600
    )

    assert result is None


def test_empty_queue_proc_running_continues_then_break(monkeypatch):
    monkeypatch.setattr(nm3u8dl, "is_suspended", lambda _p: False)
    monkeypatch.setattr(nm3u8dl, "_terminate_tree", lambda _p: None)

    proc = _ScriptedProc([], poll_seq=[None, None])
    state = _state()

    _ScriptedQueue.actions = ["EMPTY", None]
    monkeypatch.setattr(_queue_mod, "Queue", _ScriptedQueue)

    result = nm3u8dl._lire_stdout_avec_timeout(
        proc, None, None, state, timeout_s=3600
    )

    assert result is None


def test_blank_line_is_skipped(monkeypatch):
    monkeypatch.setattr(nm3u8dl, "is_suspended", lambda _p: False)
    monkeypatch.setattr(nm3u8dl, "_terminate_tree", lambda _p: None)

    proc = _ScriptedProc([], poll_seq=[None])
    state = _state()

    _ScriptedQueue.actions = ["   ", None]
    monkeypatch.setattr(_queue_mod, "Queue", _ScriptedQueue)

    seen = []
    result = nm3u8dl._lire_stdout_avec_timeout(
        proc, None, lambda p, t: seen.append((p, t)), state, timeout_s=3600
    )

    assert result is None
    assert seen == []


class _DownloadProc:
    def __init__(self, stdout, wait_script, poll_value):
        self.stdout = stdout
        self._wait_script = list(wait_script)
        self._poll_value = poll_value
        self.pid = 4242
        self.kill_calls = 0
        self.wait_calls = []

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        if self._wait_script:
            exc = self._wait_script.pop(0)
            if exc is not None:
                raise exc
        return 0

    def poll(self):
        return self._poll_value

    def kill(self):
        self.kill_calls += 1

    def terminate(self):
        return None


class _ClosableStdout:
    def __init__(self, close_raises=False):
        self.close_raises = close_raises
        self.closed = False

    def __bool__(self):
        return True

    def close(self):
        if self.close_raises:
            raise OSError("close failed")
        self.closed = True


def _wire_download(monkeypatch, proc):
    factory_cmd = {}

    def _popen(cmd, *a, **k):
        factory_cmd["cmd"] = list(cmd)
        factory_cmd["kwargs"] = k
        return proc

    monkeypatch.setattr(nm3u8dl.subprocess, "Popen", _popen)
    monkeypatch.setattr(nm3u8dl, "_get_nm3u8dl_path", lambda: "N_m3u8DL-RE")
    monkeypatch.setattr(nm3u8dl, "_get_user_settings", lambda: {})
    monkeypatch.setattr(nm3u8dl, "_monitor_tmp", lambda *a, **k: None)
    monkeypatch.setattr(nm3u8dl, "_lire_stdout_avec_timeout", lambda *a, **k: None)
    monkeypatch.setattr(nm3u8dl, "register_proc", lambda *a, **k: None)
    monkeypatch.setattr(nm3u8dl, "unregister_proc", lambda *a, **k: None)
    monkeypatch.setattr(nm3u8dl, "_remux_fix", lambda chemin, cb: chemin)
    return factory_cmd


def test_download_no_exe_callback_raises_is_swallowed(tmp_path, monkeypatch):
    monkeypatch.setattr(nm3u8dl, "_get_nm3u8dl_path", lambda: None)

    def _cb(_p, _t):
        raise RuntimeError("cb boom")

    res = nm3u8dl.nm3u8dl_download(
        "http://host/x.m3u8", str(tmp_path), "ep", callback=_cb
    )
    assert res is None


def test_download_invalid_url_callback_raises_is_swallowed(tmp_path, monkeypatch):
    monkeypatch.setattr(nm3u8dl, "_get_nm3u8dl_path", lambda: "N_m3u8DL-RE")

    def _cb(_p, _t):
        raise RuntimeError("cb boom")

    res = nm3u8dl.nm3u8dl_download(
        "ftp://host/x", str(tmp_path), "ep", callback=_cb
    )
    assert res is None


def test_download_makedirs_oserror_callback_raises_is_swallowed(tmp_path, monkeypatch):
    monkeypatch.setattr(nm3u8dl, "_get_nm3u8dl_path", lambda: "N_m3u8DL-RE")
    monkeypatch.setattr(nm3u8dl, "_get_user_settings", lambda: {})

    def _boom(path, *a, **k):
        raise OSError("read-only")

    monkeypatch.setattr(nm3u8dl.os, "makedirs", _boom)

    def _no_popen(*a, **k):
        raise AssertionError("Popen must not run")

    monkeypatch.setattr(nm3u8dl.subprocess, "Popen", _no_popen)

    def _cb(_p, _t):
        raise RuntimeError("cb boom")

    res = nm3u8dl.nm3u8dl_download(
        "http://host/x.m3u8", str(tmp_path), "ep", callback=_cb
    )
    assert res is None


def test_download_success_getsize_oserror_taille_zero(tmp_path, monkeypatch):
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"z" * 64)
    proc = _DownloadProc(stdout=None, wait_script=[None], poll_value=0)
    _wire_download(monkeypatch, proc)
    monkeypatch.setattr(nm3u8dl, "_trouver_fichier_final", lambda d, n, avant=None: str(final))

    def _getsize(_p):
        raise OSError("stat failed")

    monkeypatch.setattr(nm3u8dl.os.path, "getsize", _getsize)

    res = nm3u8dl.nm3u8dl_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res == str(final)


def test_download_finally_monitor_still_alive_logs(tmp_path, monkeypatch, caplog):
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"z" * 64)
    proc = _DownloadProc(stdout=None, wait_script=[None], poll_value=0)
    _wire_download(monkeypatch, proc)
    monkeypatch.setattr(nm3u8dl, "_trouver_fichier_final", lambda d, n, avant=None: str(final))

    class _FakeThread:
        def __init__(self, *a, **k):
            pass

        def start(self):
            return None

        def join(self, timeout=None):
            return None

        def is_alive(self):
            return True

    monkeypatch.setattr(nm3u8dl.threading, "Thread", _FakeThread)

    with caplog.at_level("DEBUG", logger="engine.download.methods.nm3u8dl"):
        res = nm3u8dl.nm3u8dl_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res == str(final)
    assert "monitor_thread n'a pas terminé" in caplog.text


def test_download_finally_monitor_join_raises_is_swallowed(tmp_path, monkeypatch):
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"z" * 64)
    proc = _DownloadProc(stdout=None, wait_script=[None], poll_value=0)
    _wire_download(monkeypatch, proc)
    monkeypatch.setattr(nm3u8dl, "_trouver_fichier_final", lambda d, n, avant=None: str(final))

    class _FakeThread:
        def __init__(self, *a, **k):
            pass

        def start(self):
            return None

        def join(self, timeout=None):
            raise RuntimeError("join boom")

        def is_alive(self):
            return False

    monkeypatch.setattr(nm3u8dl.threading, "Thread", _FakeThread)

    res = nm3u8dl.nm3u8dl_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res == str(final)


def test_download_finally_stdout_close_raises_is_swallowed(tmp_path, monkeypatch):
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"z" * 64)
    stdout = _ClosableStdout(close_raises=True)
    proc = _DownloadProc(stdout=stdout, wait_script=[None], poll_value=0)
    _wire_download(monkeypatch, proc)
    monkeypatch.setattr(nm3u8dl, "_trouver_fichier_final", lambda d, n, avant=None: str(final))

    res = nm3u8dl.nm3u8dl_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res == str(final)


def test_download_finally_terminate_timeout_then_kill_raises(tmp_path, monkeypatch):
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"z" * 64)
    proc = _DownloadProc(
        stdout=None,
        wait_script=[
            None,
            subprocess.TimeoutExpired(cmd="m", timeout=3),
        ],
        poll_value=None,
    )

    def _kill():
        proc.kill_calls += 1
        raise OSError("kill failed")

    proc.kill = _kill
    _wire_download(monkeypatch, proc)
    monkeypatch.setattr(nm3u8dl, "_trouver_fichier_final", lambda d, n, avant=None: str(final))
    monkeypatch.setattr(nm3u8dl, "_terminate_tree", lambda p: None)

    res = nm3u8dl.nm3u8dl_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res == str(final)
    assert proc.kill_calls == 1


def test_download_finally_terminate_generic_exception_then_kill_raises(tmp_path, monkeypatch):
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"z" * 64)
    proc = _DownloadProc(
        stdout=None,
        wait_script=[
            None,
            RuntimeError("wait blew up"),
        ],
        poll_value=None,
    )

    def _kill():
        proc.kill_calls += 1
        raise OSError("kill failed")

    proc.kill = _kill
    _wire_download(monkeypatch, proc)
    monkeypatch.setattr(nm3u8dl, "_trouver_fichier_final", lambda d, n, avant=None: str(final))
    monkeypatch.setattr(nm3u8dl, "_terminate_tree", lambda p: None)

    res = nm3u8dl.nm3u8dl_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res == str(final)
    assert proc.kill_calls == 1


def test_monitor_tmp_missing_dir_continue_then_return(tmp_path, monkeypatch):
    state = _state()
    missing = str(tmp_path / "nope")

    class _Stop:
        def __init__(self):
            self.set_seq = iter([False, False])
            self.wait_seq = iter([False, True])

        def is_set(self):
            return next(self.set_seq, True)

        def wait(self, _timeout=None):
            return next(self.wait_seq, True)

    nm3u8dl._monitor_tmp(missing, state, _Stop(), None)


def test_monitor_tmp_listdir_oserror_then_stop(tmp_path, monkeypatch):
    state = _state()
    target = tmp_path / "_tmp_ep"
    target.mkdir()

    def _listdir(_p):
        raise OSError("listdir failed")

    monkeypatch.setattr(nm3u8dl.os, "listdir", _listdir)

    class _Stop:
        def __init__(self):
            self.set_seq = iter([False, False])
            self.wait_seq = iter([False, True])

        def is_set(self):
            return next(self.set_seq, True)

        def wait(self, _timeout=None):
            return next(self.wait_seq, True)

    nm3u8dl._monitor_tmp(str(target), state, _Stop(), None)


def test_monitor_tmp_getsize_oserror_continues(tmp_path, monkeypatch):
    state = _state()
    target = tmp_path / "_tmp_ep"
    target.mkdir()
    (target / "seg0.ts").write_bytes(b"s")

    def _getsize(_p):
        raise OSError("getsize failed")

    monkeypatch.setattr(nm3u8dl.os.path, "getsize", _getsize)

    class _Stop:
        def __init__(self):
            self.set_seq = iter([False])

        def is_set(self):
            return next(self.set_seq, True)

        def wait(self, _timeout=None):
            return True

    nm3u8dl._monitor_tmp(str(target), state, _Stop(), None)


def test_monitor_tmp_inner_exception_logged(tmp_path, monkeypatch, caplog):
    target = tmp_path / "_tmp_ep"
    target.mkdir()
    (target / "seg0.ts").write_bytes(b"s")
    broken_state = {"total_segs": 0, "start_time": 100.0, "last_size": 0}

    class _Stop:
        def __init__(self):
            self.set_seq = iter([False])

        def is_set(self):
            return next(self.set_seq, True)

        def wait(self, _timeout=None):
            return True

    with caplog.at_level("DEBUG", logger="engine.download.methods.nm3u8dl"):
        nm3u8dl._monitor_tmp(str(target), broken_state, _Stop(), None)

    assert "[monitor_tmp]" in caplog.text


def _wire_remux(monkeypatch, tmp_path, run_result=None, run_exc=None):
    monkeypatch.setattr(nm3u8dl.shutil, "which", lambda n: "ffmpeg")
    workdir = tmp_path / "remux_work"
    workdir.mkdir()
    monkeypatch.setattr(tempfile, "mkdtemp", lambda prefix="": str(workdir))
    monkeypatch.setattr(nm3u8dl.shutil, "copy2", lambda s, d: None)

    class _FakeProc:
        def wait(self, timeout=None):
            if run_exc is not None:
                raise run_exc
            return run_result.returncode

        def poll(self):
            return None

        def kill(self):
            pass

    monkeypatch.setattr(nm3u8dl.subprocess, "Popen", lambda cmd, *a, **k: _FakeProc())
    return workdir


class _RunResult:
    def __init__(self, returncode):
        self.returncode = returncode


def test_remux_ffmpeg_missing_returns_original(monkeypatch, tmp_path):
    monkeypatch.setattr(nm3u8dl.shutil, "which", lambda n: None)
    monkeypatch.setattr(nm3u8dl, "_find_ffmpeg", lambda: None)
    chemin = str(tmp_path / "ep.mp4")
    assert nm3u8dl._remux_fix(chemin) == chemin


def test_remux_success_replace_oserror_supprime(monkeypatch, tmp_path):
    chemin = tmp_path / "ep.mp4"
    chemin.write_bytes(b"z" * 64)
    workdir = _wire_remux(monkeypatch, tmp_path, run_result=_RunResult(0))
    out_local = workdir / ("out_" + chemin.name)
    out_local.write_bytes(b"o" * 32)

    def _replace(_s, _d):
        raise OSError("replace failed")

    monkeypatch.setattr(nm3u8dl.os, "replace", _replace)
    supprimes = []
    monkeypatch.setattr(
        nm3u8dl, "_supprimer_silencieux", lambda p: supprimes.append(p)
    )
    monkeypatch.setattr(nm3u8dl.shutil, "rmtree", lambda p, **k: None)

    res = nm3u8dl._remux_fix(str(chemin))

    assert res == str(chemin)
    assert len(supprimes) == 1


def test_remux_nonzero_returncode_keeps_original(monkeypatch, tmp_path):
    chemin = tmp_path / "ep.mp4"
    chemin.write_bytes(b"z" * 64)
    _wire_remux(monkeypatch, tmp_path, run_result=_RunResult(1))
    monkeypatch.setattr(nm3u8dl.shutil, "rmtree", lambda p, **k: None)

    res = nm3u8dl._remux_fix(str(chemin))

    assert res == str(chemin)


def test_remux_timeout_keeps_original(monkeypatch, tmp_path):
    chemin = tmp_path / "ep.mp4"
    chemin.write_bytes(b"z" * 64)
    _wire_remux(
        monkeypatch,
        tmp_path,
        run_exc=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=300),
    )
    monkeypatch.setattr(nm3u8dl.shutil, "rmtree", lambda p, **k: None)

    res = nm3u8dl._remux_fix(str(chemin))

    assert res == str(chemin)


def test_remux_generic_exception_keeps_original(monkeypatch, tmp_path):
    chemin = tmp_path / "ep.mp4"
    chemin.write_bytes(b"z" * 64)
    _wire_remux(monkeypatch, tmp_path, run_exc=ValueError("boom"))
    monkeypatch.setattr(nm3u8dl.shutil, "rmtree", lambda p, **k: None)

    res = nm3u8dl._remux_fix(str(chemin))

    assert res == str(chemin)


def test_remux_finally_rmtree_raises_is_swallowed(monkeypatch, tmp_path):
    chemin = tmp_path / "ep.mp4"
    chemin.write_bytes(b"z" * 64)
    _wire_remux(monkeypatch, tmp_path, run_exc=ValueError("boom"))

    def _rmtree(_p, **_k):
        raise OSError("rmtree failed")

    monkeypatch.setattr(nm3u8dl.shutil, "rmtree", _rmtree)

    res = nm3u8dl._remux_fix(str(chemin))

    assert res == str(chemin)
