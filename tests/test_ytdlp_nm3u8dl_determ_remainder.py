import subprocess

import pytest

import engine.config.logging_setup  # noqa: F401
import engine.config.user_settings as user_settings
import engine.download.methods.nm3u8dl as nm3u8dl
import engine.download.methods.ytdlp_engine as ytdlp_engine
from engine.domain.exceptions import DownloadCancelled


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


class _ListStdout:
    def __init__(self, lines):
        self._lines = list(lines)
        self._i = 0
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if self._i >= len(self._lines):
            raise StopIteration
        item = self._lines[self._i]
        self._i += 1
        return item

    def close(self):
        self.closed = True


class FakeProc:
    def __init__(self, stdout_lines, returncode=0, wait_raises=0, poll_value="rc"):
        self.returncode = returncode
        self.pid = 4321
        self.stdout = _ListStdout(stdout_lines) if stdout_lines is not None else None
        self._wait_raises_remaining = wait_raises
        self._poll_value = poll_value
        self.kill_calls = 0
        self.terminate_calls = 0
        self.wait_calls = []

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        if self._wait_raises_remaining > 0:
            self._wait_raises_remaining -= 1
            raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout or 0)
        return self.returncode

    def poll(self):
        if self._poll_value == "rc":
            return self.returncode
        return self._poll_value

    def kill(self):
        self.kill_calls += 1

    def terminate(self):
        self.terminate_calls += 1


class FakePopenFactory:
    def __init__(self, proc=None, raises=None):
        self.proc = proc
        self.raises = raises
        self.cmd = None
        self.kwargs = None

    def __call__(self, cmd, *args, **kwargs):
        self.cmd = list(cmd)
        self.kwargs = kwargs
        if self.raises is not None:
            raise self.raises
        return self.proc


def _wire_ytdlp(monkeypatch, factory, final=None):
    monkeypatch.setattr(ytdlp_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp_engine, "_get_aria2c_path", lambda: None)
    monkeypatch.setattr(ytdlp_engine, "_trouver_fichier_final", lambda d, n: final)
    monkeypatch.setattr(ytdlp_engine, "_spawn_proc_watchdog", lambda *a, **k: None)
    monkeypatch.setattr(ytdlp_engine, "register_proc", lambda *a, **k: None)
    monkeypatch.setattr(ytdlp_engine, "unregister_proc", lambda *a, **k: None)
    monkeypatch.setattr(user_settings, "load_settings", lambda: {"qualite": "auto"})


def test_ytdlp_merger_line_emits_assembly_callback(tmp_path, monkeypatch):
    proc = FakeProc(stdout_lines=["[Merger] Merging formats into ep.mp4"], returncode=1)
    factory = FakePopenFactory(proc)
    _wire_ytdlp(monkeypatch, factory, final=None)

    calls = []
    res = ytdlp_engine.ytdlp_download(
        "http://host/v", str(tmp_path), "ep",
        callback=lambda p, t: calls.append((p, t)),
    )

    assert res is None
    assert (97.0, "🔧 Assemblage pistes…") in calls


def test_ytdlp_merging_word_without_merger_tag_emits_assembly(tmp_path, monkeypatch):
    proc = FakeProc(stdout_lines=["Merging audio and video"], returncode=1)
    factory = FakePopenFactory(proc)
    _wire_ytdlp(monkeypatch, factory, final=None)

    calls = []
    ytdlp_engine.ytdlp_download(
        "http://host/v", str(tmp_path), "ep",
        callback=lambda p, t: calls.append((p, t)),
    )

    assert (97.0, "🔧 Assemblage pistes…") in calls


def test_ytdlp_aria2c_line_emits_prefixed_callback(tmp_path, monkeypatch):
    proc = FakeProc(stdout_lines=["[aria2c] downloading fragment 3"], returncode=1)
    factory = FakePopenFactory(proc)
    _wire_ytdlp(monkeypatch, factory, final=None)

    calls = []
    ytdlp_engine.ytdlp_download(
        "http://host/v", str(tmp_path), "ep",
        callback=lambda p, t: calls.append((p, t)),
    )

    aria_calls = [(p, t) for p, t in calls if "accéléré" in t]
    assert aria_calls == [(0.0, "⬇️ Téléchargement accéléré en cours…")]


def test_ytdlp_download_destination_line_no_progress_callback(tmp_path, monkeypatch):
    proc = FakeProc(
        stdout_lines=["[download] Destination: ep.mp4"], returncode=1
    )
    factory = FakePopenFactory(proc)
    _wire_ytdlp(monkeypatch, factory, final=None)

    calls = []
    ytdlp_engine.ytdlp_download(
        "http://host/v", str(tmp_path), "ep",
        callback=lambda p, t: calls.append((p, t)),
    )

    assert all(not t.startswith("[yt-dlp]") for _, t in calls)
    assert all(not t.startswith("[aria2c]") for _, t in calls)


def test_ytdlp_error_line_without_403_logs_info(tmp_path, monkeypatch, caplog):
    proc = FakeProc(stdout_lines=["ERROR: something went sideways"], returncode=1)
    factory = FakePopenFactory(proc)
    _wire_ytdlp(monkeypatch, factory, final=None)

    calls = []
    with caplog.at_level("INFO", logger="engine.download.methods.ytdlp_engine"):
        res = ytdlp_engine.ytdlp_download(
            "http://host/v", str(tmp_path), "ep",
            callback=lambda p, t: calls.append((p, t)),
        )

    assert res is None
    assert "something went sideways" in caplog.text
    assert all("Serveur occupé" not in t for _, t in calls)


def test_ytdlp_wait_timeout_triggers_terminate_after_eof(tmp_path, monkeypatch):
    proc = FakeProc(
        stdout_lines=["[download] Destination: ep.mp4"],
        returncode=0,
        wait_raises=1,
        poll_value=0,
    )
    factory = FakePopenFactory(proc)
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"x" * 64)
    _wire_ytdlp(monkeypatch, factory, final=str(final))

    terminated = []
    monkeypatch.setattr(ytdlp_engine, "_terminate_tree", lambda p: terminated.append(p))

    res = ytdlp_engine.ytdlp_download("http://host/v", str(tmp_path), "ep")

    assert res == str(final)
    assert terminated == [proc]
    assert proc.wait_calls[0] == 30


def test_ytdlp_returncode_nonzero_returns_none_without_lookup(tmp_path, monkeypatch):
    proc = FakeProc(stdout_lines=["[download]  10.0%"], returncode=2, poll_value=2)
    factory = FakePopenFactory(proc)

    def _never(d, n):
        raise AssertionError("_trouver_fichier_final must not run on non-zero rc")

    monkeypatch.setattr(ytdlp_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp_engine, "_get_aria2c_path", lambda: None)
    monkeypatch.setattr(ytdlp_engine, "_trouver_fichier_final", _never)
    monkeypatch.setattr(ytdlp_engine, "_spawn_proc_watchdog", lambda *a, **k: None)
    monkeypatch.setattr(ytdlp_engine, "register_proc", lambda *a, **k: None)
    monkeypatch.setattr(ytdlp_engine, "unregister_proc", lambda *a, **k: None)
    monkeypatch.setattr(user_settings, "load_settings", lambda: {"qualite": "auto"})

    res = ytdlp_engine.ytdlp_download("http://host/v", str(tmp_path), "ep")

    assert res is None


def test_ytdlp_finally_kill_fallback_when_terminate_wait_times_out(tmp_path, monkeypatch):
    proc = FakeProc(
        stdout_lines=["[download]  10.0%"],
        returncode=0,
        wait_raises=2,
        poll_value=None,
    )
    factory = FakePopenFactory(proc)
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"x" * 64)
    _wire_ytdlp(monkeypatch, factory, final=str(final))

    terminated = []
    monkeypatch.setattr(ytdlp_engine, "_terminate_tree", lambda p: terminated.append(p))

    res = ytdlp_engine.ytdlp_download("http://host/v", str(tmp_path), "ep")

    assert res == str(final)
    assert proc in terminated
    assert proc.kill_calls == 1


def test_ytdlp_popen_filenotfound_returns_none(tmp_path, monkeypatch):
    factory = FakePopenFactory(raises=FileNotFoundError("yt-dlp.exe missing"))
    monkeypatch.setattr(ytdlp_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp_engine, "_get_aria2c_path", lambda: None)
    monkeypatch.setattr(ytdlp_engine, "_spawn_proc_watchdog", lambda *a, **k: None)
    monkeypatch.setattr(ytdlp_engine, "register_proc", lambda *a, **k: None)
    monkeypatch.setattr(ytdlp_engine, "unregister_proc", lambda *a, **k: None)
    monkeypatch.setattr(user_settings, "load_settings", lambda: {"qualite": "auto"})

    res = ytdlp_engine.ytdlp_download("http://host/v", str(tmp_path), "ep")

    assert res is None
    assert factory.cmd[0] == "yt-dlp"


def _wire_nm3u8dl(monkeypatch, factory, final=None):
    monkeypatch.setattr(nm3u8dl.subprocess, "Popen", factory)
    monkeypatch.setattr(nm3u8dl, "_get_nm3u8dl_path", lambda: "N_m3u8DL-RE")
    monkeypatch.setattr(nm3u8dl, "_get_user_settings", lambda: {})
    monkeypatch.setattr(nm3u8dl, "_monitor_tmp", lambda *a, **k: None)
    monkeypatch.setattr(nm3u8dl, "_trouver_fichier_final", lambda d, n, avant=None: final)
    monkeypatch.setattr(nm3u8dl, "register_proc", lambda *a, **k: None)
    monkeypatch.setattr(nm3u8dl, "unregister_proc", lambda *a, **k: None)
    monkeypatch.setattr(nm3u8dl, "_lire_stdout_avec_timeout", lambda *a, **k: None)


def test_nm3u8dl_makedirs_oserror_returns_none_and_callback(tmp_path, monkeypatch):
    monkeypatch.setattr(nm3u8dl, "_get_nm3u8dl_path", lambda: "N_m3u8DL-RE")
    monkeypatch.setattr(nm3u8dl, "_get_user_settings", lambda: {})

    def _boom(path, *a, **k):
        raise OSError("read-only fs")

    monkeypatch.setattr(nm3u8dl.os, "makedirs", _boom)

    def _no_popen(*a, **k):
        raise AssertionError("Popen must not run after makedirs failure")

    monkeypatch.setattr(nm3u8dl.subprocess, "Popen", _no_popen)

    calls = []
    res = nm3u8dl.nm3u8dl_download(
        "http://host/x.m3u8", str(tmp_path), "ep",
        callback=lambda p, t: calls.append((p, t)),
    )

    assert res is None
    assert len(calls) == 1
    assert calls[0][0] == 0.0
    assert "Impossible de créer le dossier" in calls[0][1]


def test_nm3u8dl_log_cwd_selected_when_dir_exists(tmp_path, monkeypatch):
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"z" * 64)
    proc = FakeProc(stdout_lines=None, returncode=0, poll_value=0)
    factory = FakePopenFactory(proc)
    _wire_nm3u8dl(monkeypatch, factory, final=str(final))
    remux_calls = []
    monkeypatch.setattr(
        nm3u8dl, "_remux_fix", lambda chemin, cb: remux_calls.append(chemin) or chemin
    )

    real_isdir = nm3u8dl.os.path.isdir
    monkeypatch.setattr(
        nm3u8dl.os.path,
        "isdir",
        lambda p: True if p == nm3u8dl.NM3U8DL_LOG_CWD else real_isdir(p),
    )

    res = nm3u8dl.nm3u8dl_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res == str(final)
    assert factory.kwargs["cwd"] == nm3u8dl.NM3U8DL_LOG_CWD
    assert remux_calls == [str(final)]


def test_nm3u8dl_log_cwd_none_when_dir_absent(tmp_path, monkeypatch):
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"z" * 64)
    proc = FakeProc(stdout_lines=None, returncode=0, poll_value=0)
    factory = FakePopenFactory(proc)
    _wire_nm3u8dl(monkeypatch, factory, final=str(final))
    monkeypatch.setattr(nm3u8dl, "_remux_fix", lambda chemin, cb: chemin)

    real_isdir = nm3u8dl.os.path.isdir
    monkeypatch.setattr(
        nm3u8dl.os.path,
        "isdir",
        lambda p: False if p == nm3u8dl.NM3U8DL_LOG_CWD else real_isdir(p),
    )

    res = nm3u8dl.nm3u8dl_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res == str(final)
    assert factory.kwargs["cwd"] is None


def test_nm3u8dl_wait_timeout_kills_then_returns_none(tmp_path, monkeypatch):
    proc = FakeProc(stdout_lines=None, returncode=1, wait_raises=2, poll_value=1)
    factory = FakePopenFactory(proc)
    _wire_nm3u8dl(monkeypatch, factory, final=None)
    monkeypatch.setattr(nm3u8dl, "_remux_fix", lambda chemin, cb: chemin)

    res = nm3u8dl.nm3u8dl_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res is None
    assert proc.kill_calls == 1
    assert proc.wait_calls[0] == 15


def test_nm3u8dl_success_invokes_remux_and_keeps_no_tmp(tmp_path, monkeypatch):
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"z" * 64)
    proc = FakeProc(stdout_lines=None, returncode=0, poll_value=0)
    factory = FakePopenFactory(proc)
    _wire_nm3u8dl(monkeypatch, factory, final=str(final))
    monkeypatch.setattr(nm3u8dl, "_remux_fix", lambda chemin, cb: chemin + ".remuxed")

    tmp_dir = tmp_path / "_tmp_ep"
    tmp_dir.mkdir()
    (tmp_dir / "seg0.ts").write_bytes(b"s")

    res = nm3u8dl.nm3u8dl_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res == str(final) + ".remuxed"
    assert not tmp_dir.exists()
    assert proc.stdout is None or proc.stdout.closed


def test_nm3u8dl_download_cancelled_removes_tmp_and_reraises(tmp_path, monkeypatch):
    proc = FakeProc(stdout_lines=[], returncode=0, poll_value=0)
    factory = FakePopenFactory(proc)
    _wire_nm3u8dl(monkeypatch, factory, final=None)
    monkeypatch.setattr(nm3u8dl, "_remux_fix", lambda chemin, cb: chemin)

    def _raise(*a, **k):
        raise DownloadCancelled()

    monkeypatch.setattr(nm3u8dl, "_lire_stdout_avec_timeout", _raise)

    tmp_dir = tmp_path / "_tmp_ep"
    tmp_dir.mkdir()
    (tmp_dir / "seg0.ts").write_bytes(b"s")

    with pytest.raises(DownloadCancelled):
        nm3u8dl.nm3u8dl_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert not tmp_dir.exists()


def test_nm3u8dl_download_runtimeerror_keeps_tmp_and_reraises(tmp_path, monkeypatch):
    proc = FakeProc(stdout_lines=[], returncode=0, poll_value=0)
    factory = FakePopenFactory(proc)
    _wire_nm3u8dl(monkeypatch, factory, final=None)
    monkeypatch.setattr(nm3u8dl, "_remux_fix", lambda chemin, cb: chemin)

    def _raise(*a, **k):
        raise RuntimeError("Timeout global du téléchargement")

    monkeypatch.setattr(nm3u8dl, "_lire_stdout_avec_timeout", _raise)

    tmp_dir = tmp_path / "_tmp_ep"
    tmp_dir.mkdir()
    (tmp_dir / "seg0.ts").write_bytes(b"s")

    with pytest.raises(RuntimeError) as exc:
        nm3u8dl.nm3u8dl_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert "Timeout global" in str(exc.value)
    assert tmp_dir.exists()


def test_nm3u8dl_download_filenotfound_returns_none_and_keeps_tmp(tmp_path, monkeypatch):
    proc = FakeProc(stdout_lines=[], returncode=0, poll_value=0)
    factory = FakePopenFactory(proc)
    _wire_nm3u8dl(monkeypatch, factory, final=None)
    monkeypatch.setattr(nm3u8dl, "_remux_fix", lambda chemin, cb: chemin)

    def _raise(*a, **k):
        raise FileNotFoundError("N_m3u8DL-RE gone")

    monkeypatch.setattr(nm3u8dl, "_lire_stdout_avec_timeout", _raise)

    tmp_dir = tmp_path / "_tmp_ep"
    tmp_dir.mkdir()

    res = nm3u8dl.nm3u8dl_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res is None
    assert tmp_dir.exists()


def test_nm3u8dl_download_generic_exception_returns_none_and_keeps_tmp(tmp_path, monkeypatch):
    proc = FakeProc(stdout_lines=[], returncode=0, poll_value=0)
    factory = FakePopenFactory(proc)
    _wire_nm3u8dl(monkeypatch, factory, final=None)
    monkeypatch.setattr(nm3u8dl, "_remux_fix", lambda chemin, cb: chemin)

    def _raise(*a, **k):
        raise ValueError("unexpected parsing failure")

    monkeypatch.setattr(nm3u8dl, "_lire_stdout_avec_timeout", _raise)

    tmp_dir = tmp_path / "_tmp_ep"
    tmp_dir.mkdir()

    res = nm3u8dl.nm3u8dl_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res is None
    assert tmp_dir.exists()


def test_nm3u8dl_main_body_kill_when_wait_timeout(tmp_path, monkeypatch):
    """Main-body wait(15) timeout -> proc.kill(); the finally is skipped because the
    process has already exited (poll() != None), so no terminate/kill there."""
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"z" * 64)
    proc = FakeProc(stdout_lines=None, returncode=0, wait_raises=1, poll_value=0)
    factory = FakePopenFactory(proc)
    _wire_nm3u8dl(monkeypatch, factory, final=str(final))
    monkeypatch.setattr(nm3u8dl, "_remux_fix", lambda chemin, cb: chemin)

    terminated = []
    monkeypatch.setattr(nm3u8dl, "_terminate_tree", lambda p: terminated.append(p))

    res = nm3u8dl.nm3u8dl_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res == str(final)
    assert terminated == []
    assert proc.kill_calls == 1
    assert proc.wait_calls == [15, 5]


def test_nm3u8dl_finally_kill_fallback_when_terminate_wait_times_out(tmp_path, monkeypatch):
    """Process still alive at finally (poll()==None): _terminate_tree then a timing-out
    wait(3) triggers the finally kill() fallback. wait_raises=3 makes every wait()
    time out (main-body 15 -> kill, post-kill 5 swallowed, finally 3 -> kill fallback)."""
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"z" * 64)
    proc = FakeProc(stdout_lines=None, returncode=0, wait_raises=3, poll_value=None)
    factory = FakePopenFactory(proc)
    _wire_nm3u8dl(monkeypatch, factory, final=str(final))
    monkeypatch.setattr(nm3u8dl, "_remux_fix", lambda chemin, cb: chemin)

    terminated = []
    monkeypatch.setattr(nm3u8dl, "_terminate_tree", lambda p: terminated.append(p))

    res = nm3u8dl.nm3u8dl_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res == str(final)
    assert terminated == [proc]
    assert proc.wait_calls == [15, 5, 3]
    assert proc.kill_calls == 2
