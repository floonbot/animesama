import threading

import pytest

import engine.config.logging_setup  # noqa: F401
from engine.domain.exceptions import DownloadCancelled
from engine.download.methods import ffmpeg_engine, nm3u8dl, ytdlp_engine


class _GatedIter:
    def __init__(self, items, wait_event=None, done_event=None):
        self._items = list(items)
        self._i = 0
        self._wait_event = wait_event
        self._done_event = done_event

    def __iter__(self):
        return self

    def __next__(self):
        if self._wait_event is not None and self._i == 0:
            self._wait_event.wait(timeout=5)
        if self._i >= len(self._items):
            if self._done_event is not None:
                self._done_event.set()
            raise StopIteration
        item = self._items[self._i]
        self._i += 1
        return item

    def close(self):
        return None


class FakeProc:
    def __init__(self, stdout_lines=None, stderr_lines=None, returncode=0,
                 stderr_wait_event=None, stdout_done_event=None):
        self.returncode = returncode
        self.pid = 4321
        self._stdout_done_event = stdout_done_event
        if stdout_lines is None:
            self.stdout = None
        else:
            self.stdout = _GatedIter(stdout_lines, done_event=stdout_done_event)
        if stderr_lines is None:
            self.stderr = None
        else:
            self.stderr = _GatedIter(stderr_lines, wait_event=stderr_wait_event)

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        return None

    def terminate(self):
        return None


class FakePopenFactory:
    def __init__(self, proc):
        self.proc = proc
        self.cmd = None
        self.kwargs = None

    def __call__(self, cmd, *args, **kwargs):
        self.cmd = list(cmd)
        self.kwargs = kwargs
        return self.proc


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


@pytest.fixture(autouse=True)
def _reset_nm3u8dl_settings_cache():
    nm3u8dl._settings_cache = None
    nm3u8dl._settings_cache_ts = 0.0
    yield
    nm3u8dl._settings_cache = None
    nm3u8dl._settings_cache_ts = 0.0


def test_ytdlp_success_returns_file_and_reports_progress(tmp_path, monkeypatch):
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"x" * 16)

    factory = FakePopenFactory(FakeProc(
        stdout_lines=["[download]  42.5% of ~100.00MiB at 5.00MiB/s ETA 00:30"],
        returncode=0,
    ))
    monkeypatch.setattr(ytdlp_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp_engine, "_get_aria2c_path", lambda: None)
    monkeypatch.setattr(ytdlp_engine, "_trouver_fichier_final", lambda d, n, avant=None: str(final))
    _neutralize(monkeypatch, ytdlp_engine)

    import engine.config.user_settings as user_settings
    monkeypatch.setattr(user_settings, "load_settings", lambda: {"qualite": "720"})

    calls = []
    res = ytdlp_engine.ytdlp_download(
        "http://host/video", str(tmp_path), "ep",
        callback=lambda p, t: calls.append((p, t)),
    )

    assert res == str(final)
    assert "yt-dlp" in factory.cmd
    assert "http://host/video" in factory.cmd
    assert any(abs(p - 42.5) < 1e-6 for p, _ in calls)
    assert any(t == "✅ Téléchargement terminé !" for _, t in calls)


def test_ytdlp_failure_returns_none(tmp_path, monkeypatch):
    factory = FakePopenFactory(FakeProc(stdout_lines=["[download]  10.0%"], returncode=1))
    monkeypatch.setattr(ytdlp_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp_engine, "_get_aria2c_path", lambda: None)
    monkeypatch.setattr(ytdlp_engine, "_trouver_fichier_final", lambda d, n, avant=None: None)
    _neutralize(monkeypatch, ytdlp_engine)

    import engine.config.user_settings as user_settings
    monkeypatch.setattr(user_settings, "load_settings", lambda: {"qualite": "720"})

    res = ytdlp_engine.ytdlp_download("http://host/video", str(tmp_path), "ep")
    assert res is None


def test_ytdlp_403_raises_ratelimit(tmp_path, monkeypatch):
    factory = FakePopenFactory(FakeProc(
        stdout_lines=["ERROR: unable to download: HTTP Error 403: Forbidden"],
        returncode=0,
    ))
    monkeypatch.setattr(ytdlp_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp_engine, "_get_aria2c_path", lambda: None)
    monkeypatch.setattr(ytdlp_engine, "_trouver_fichier_final", lambda d, n, avant=None: None)
    _neutralize(monkeypatch, ytdlp_engine)

    import engine.config.user_settings as user_settings
    monkeypatch.setattr(user_settings, "load_settings", lambda: {"qualite": "720"})

    with pytest.raises(ytdlp_engine.RateLimitError) as exc:
        ytdlp_engine.ytdlp_download("http://host.example/video", str(tmp_path), "ep")
    assert exc.value.domain == "host.example"


def test_dispatch_still_detects_403():
    assert ytdlp_engine._dispatch_ligne_ytdlp(
        "ERROR: unable to download: HTTP Error 403: Forbidden", "h.tld", None
    ) is True

def test_dispatch_detects_429_too_many_requests():
    assert ytdlp_engine._dispatch_ligne_ytdlp(
        "ERROR: unable to download: HTTP Error 429: Too Many Requests", "h.tld", None
    ) is True

def test_dispatch_detects_503_service_unavailable():
    assert ytdlp_engine._dispatch_ligne_ytdlp(
        "ERROR: unable to download: HTTP Error 503: Service Unavailable", "h.tld", None
    ) is True

def test_dispatch_progress_with_429_in_size_is_not_throttle():
    assert ytdlp_engine._dispatch_ligne_ytdlp(
        "[download]  42.9% of 429.00MiB at 5.03MiB/s ETA 00:30", "h.tld", None
    ) is False

def test_dispatch_progress_with_503_in_percent_is_not_throttle():
    assert ytdlp_engine._dispatch_ligne_ytdlp(
        "[download]  50.3% of 200.00MiB at 1.00MiB/s ETA 01:00", "h.tld", None
    ) is False


def test_ytdlp_cancellation_raises(tmp_path, monkeypatch):
    factory = FakePopenFactory(FakeProc(
        stdout_lines=["[download]   1.0%"], returncode=0,
    ))
    monkeypatch.setattr(ytdlp_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp_engine, "_get_aria2c_path", lambda: None)
    monkeypatch.setattr(ytdlp_engine, "_trouver_fichier_final", lambda d, n, avant=None: None)
    monkeypatch.setattr(ytdlp_engine, "_terminate_tree", lambda p: None)
    _neutralize(monkeypatch, ytdlp_engine)

    import engine.config.user_settings as user_settings
    monkeypatch.setattr(user_settings, "load_settings", lambda: {"qualite": "720"})

    with pytest.raises(DownloadCancelled):
        ytdlp_engine.ytdlp_download(
            "http://host/video", str(tmp_path), "ep", cancelled=[True],
        )


class _FakeClock:
    def __init__(self, start=1000.0, step=1.0):
        self.t = start
        self.step = step

    def __call__(self):
        cur = self.t
        self.t += self.step
        return cur


def test_ffmpeg_success_returns_output_and_final_callback(tmp_path, monkeypatch):
    sortie = tmp_path / "ep.mp4"
    sortie.write_bytes(b"y" * 64)

    factory = FakePopenFactory(FakeProc(
        stdout_lines=[],
        stderr_lines=["frame=  100 fps=50"],
        returncode=0,
    ))
    monkeypatch.setattr(ffmpeg_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg_engine, "_estimer_duree_hls", lambda *a: 100.0)
    monkeypatch.setattr(ffmpeg_engine, "TAILLE_MIN_FICHIER", 1)
    monkeypatch.setattr(ffmpeg_engine.time, "time", _FakeClock())
    _neutralize(monkeypatch, ffmpeg_engine)

    calls = []
    res = ffmpeg_engine.ffmpeg_download(
        "http://host/x.m3u8", str(tmp_path), "ep",
        callback=lambda p, t: calls.append((p, t)),
    )

    assert res == str(sortie)
    assert "ffmpeg" in factory.cmd
    assert "http://host/x.m3u8" in factory.cmd
    assert str(sortie) in factory.cmd
    assert any(t == "✅ Téléchargement terminé !" and p == 100.0 for p, t in calls)


def test_ffmpeg_emits_progress_from_stderr(tmp_path, monkeypatch):
    sortie = tmp_path / "ep.mp4"
    sortie.write_bytes(b"y" * 64)

    stderr_gate = threading.Event()
    stdout_done = threading.Event()
    proc = FakeProc(
        stdout_lines=["out_time=00:00:50", "total_size=1048576", "progress=continue"],
        stderr_lines=["frame=1 fps=1", "frame=2 fps=2"],
        returncode=0,
        stderr_wait_event=stderr_gate,
        stdout_done_event=stdout_done,
    )

    def _link():
        stdout_done.wait(timeout=5)
        stderr_gate.set()

    threading.Thread(target=_link, daemon=True).start()

    factory = FakePopenFactory(proc)
    monkeypatch.setattr(ffmpeg_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg_engine, "_estimer_duree_hls", lambda *a: 100.0)
    monkeypatch.setattr(ffmpeg_engine, "TAILLE_MIN_FICHIER", 1)
    monkeypatch.setattr(ffmpeg_engine.time, "time", _FakeClock(step=1.0))
    _neutralize(monkeypatch, ffmpeg_engine)

    calls = []
    ffmpeg_engine.ffmpeg_download(
        "http://host/x.m3u8", str(tmp_path), "ep",
        callback=lambda p, t: calls.append((p, t)),
    )

    assert stdout_done.is_set()
    progress = [(p, t) for p, t in calls if t.startswith("⬇️")]
    assert progress
    assert any(abs(p - 50.0) < 1.0 for p, _ in progress)


def test_ffmpeg_nonzero_returncode_returns_none(tmp_path, monkeypatch):
    factory = FakePopenFactory(FakeProc(
        stdout_lines=[], stderr_lines=["fatal error"], returncode=1,
    ))
    monkeypatch.setattr(ffmpeg_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg_engine, "_estimer_duree_hls", lambda *a: 100.0)
    monkeypatch.setattr(ffmpeg_engine, "TAILLE_MIN_FICHIER", 1)
    monkeypatch.setattr(ffmpeg_engine.time, "time", _FakeClock())
    _neutralize(monkeypatch, ffmpeg_engine)

    res = ffmpeg_engine.ffmpeg_download("http://host/x.m3u8", str(tmp_path), "ep")
    assert res is None


def test_ffmpeg_undersized_output_is_rejected_and_removed(tmp_path, monkeypatch):
    sortie = tmp_path / "ep.mp4"
    sortie.write_bytes(b"y" * 64)

    factory = FakePopenFactory(FakeProc(
        stdout_lines=[], stderr_lines=["frame=1 fps=1"], returncode=0,
    ))
    monkeypatch.setattr(ffmpeg_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg_engine, "_estimer_duree_hls", lambda *a: 100.0)
    monkeypatch.setattr(ffmpeg_engine.time, "time", _FakeClock())
    _neutralize(monkeypatch, ffmpeg_engine)

    res = ffmpeg_engine.ffmpeg_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res is None
    assert not sortie.exists()


def test_ffmpeg_cancellation_raises(tmp_path, monkeypatch):
    factory = FakePopenFactory(FakeProc(
        stdout_lines=[], stderr_lines=["frame=1 fps=1"], returncode=0,
    ))
    monkeypatch.setattr(ffmpeg_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg_engine, "_estimer_duree_hls", lambda *a: 100.0)
    monkeypatch.setattr(ffmpeg_engine, "TAILLE_MIN_FICHIER", 1)
    monkeypatch.setattr(ffmpeg_engine, "_terminate_tree", lambda p: None)
    monkeypatch.setattr(ffmpeg_engine.time, "time", _FakeClock())
    _neutralize(monkeypatch, ffmpeg_engine)

    with pytest.raises(DownloadCancelled):
        ffmpeg_engine.ffmpeg_download(
            "http://host/x.m3u8", str(tmp_path), "ep", cancelled=[True],
        )


def test_nm3u8dl_success_returns_file_and_parses_progress(tmp_path, monkeypatch):
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"z" * 64)

    factory = FakePopenFactory(FakeProc(
        stdout_lines=["Total 5 Segments found", "Binary merging into output", "Done"],
        returncode=0,
    ))
    monkeypatch.setattr(nm3u8dl.subprocess, "Popen", factory)
    monkeypatch.setattr(nm3u8dl, "_get_nm3u8dl_path", lambda: "N_m3u8DL-RE")
    monkeypatch.setattr(nm3u8dl, "_get_user_settings", lambda: {})
    monkeypatch.setattr(nm3u8dl, "_monitor_tmp", lambda *a, **k: None)
    monkeypatch.setattr(nm3u8dl, "_trouver_fichier_final", lambda d, n, avant=None: str(final))
    monkeypatch.setattr(nm3u8dl, "_remux_fix", lambda chemin, cb: chemin)

    calls = []
    res = nm3u8dl.nm3u8dl_download(
        "http://host/x.m3u8", str(tmp_path), "ep",
        callback=lambda p, t: calls.append((p, t)),
    )

    assert res == str(final)
    assert factory.cmd[0] == "N_m3u8DL-RE"
    assert factory.cmd[1] == "http://host/x.m3u8"
    assert factory.cmd[factory.cmd.index("--save-name") + 1] == "ep"
    assert factory.cmd[factory.cmd.index("--save-dir") + 1] == str(tmp_path)
    assert (96.0, "🔧 Assemblage des segments…") in calls
    assert (100.0, "✅ Terminé !") in calls


def test_nm3u8dl_no_file_returns_none(tmp_path, monkeypatch):
    factory = FakePopenFactory(FakeProc(
        stdout_lines=["Total 5 Segments found"],
        returncode=1,
    ))
    monkeypatch.setattr(nm3u8dl.subprocess, "Popen", factory)
    monkeypatch.setattr(nm3u8dl, "_get_nm3u8dl_path", lambda: "N_m3u8DL-RE")
    monkeypatch.setattr(nm3u8dl, "_get_user_settings", lambda: {})
    monkeypatch.setattr(nm3u8dl, "_monitor_tmp", lambda *a, **k: None)
    monkeypatch.setattr(nm3u8dl, "_trouver_fichier_final", lambda d, n, avant=None: None)
    monkeypatch.setattr(nm3u8dl, "_remux_fix", lambda chemin, cb: chemin)

    res = nm3u8dl.nm3u8dl_download("http://host/x.m3u8", str(tmp_path), "ep")
    assert res is None


def test_nm3u8dl_cancellation_raises(tmp_path, monkeypatch):
    factory = FakePopenFactory(FakeProc(
        stdout_lines=["Total 5 Segments found"],
        returncode=0,
    ))
    monkeypatch.setattr(nm3u8dl.subprocess, "Popen", factory)
    monkeypatch.setattr(nm3u8dl, "_get_nm3u8dl_path", lambda: "N_m3u8DL-RE")
    monkeypatch.setattr(nm3u8dl, "_get_user_settings", lambda: {})
    monkeypatch.setattr(nm3u8dl, "_monitor_tmp", lambda *a, **k: None)
    monkeypatch.setattr(nm3u8dl, "_trouver_fichier_final", lambda d, n, avant=None: None)
    monkeypatch.setattr(nm3u8dl, "_remux_fix", lambda chemin, cb: chemin)
    monkeypatch.setattr(nm3u8dl, "_terminate_tree", lambda p: None)

    with pytest.raises(DownloadCancelled):
        nm3u8dl.nm3u8dl_download(
            "http://host/x.m3u8", str(tmp_path), "ep", cancelled=[True],
        )


def test_nm3u8dl_attaches_global_watchdog(tmp_path, monkeypatch):
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"z" * 64)

    calls = []

    def _fake_watchdog(proc, cancelled, timeout):
        calls.append((proc, timeout))
        return threading.Event()

    factory = FakePopenFactory(FakeProc(
        stdout_lines=["Total 5 Segments found", "Done"],
        returncode=0,
    ))
    monkeypatch.setattr(nm3u8dl.subprocess, "Popen", factory)
    monkeypatch.setattr(nm3u8dl, "_get_nm3u8dl_path", lambda: "N_m3u8DL-RE")
    monkeypatch.setattr(nm3u8dl, "_get_user_settings", lambda: {})
    monkeypatch.setattr(nm3u8dl, "_monitor_tmp", lambda *a, **k: None)
    monkeypatch.setattr(nm3u8dl, "_trouver_fichier_final", lambda d, n, avant=None: str(final))
    monkeypatch.setattr(nm3u8dl, "_remux_fix", lambda chemin, cb: chemin)
    monkeypatch.setattr(nm3u8dl, "_spawn_proc_watchdog", _fake_watchdog)

    res = nm3u8dl.nm3u8dl_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res == str(final)
    assert calls and calls[0][0] is factory.proc
    assert calls[0][1] == nm3u8dl.TIMEOUT_GLOBAL_DOWNLOAD


def test_engines_spawn_in_new_session_for_group_kill(tmp_path, monkeypatch):
    import engine.config.user_settings as user_settings
    monkeypatch.setattr(user_settings, "load_settings", lambda: {"qualite": "720"})

    yt_final = tmp_path / "yt.mp4"
    yt_final.write_bytes(b"x" * 16)
    yt_factory = FakePopenFactory(FakeProc(stdout_lines=["[download] 1.0%"], returncode=0))
    monkeypatch.setattr(ytdlp_engine.subprocess, "Popen", yt_factory)
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp_engine, "_get_aria2c_path", lambda: None)
    monkeypatch.setattr(ytdlp_engine, "_trouver_fichier_final", lambda d, n, avant=None: str(yt_final))
    _neutralize(monkeypatch, ytdlp_engine)
    ytdlp_engine.ytdlp_download("http://host/v", str(tmp_path), "ep")
    assert yt_factory.kwargs.get("start_new_session") is True

    ff_factory = FakePopenFactory(FakeProc(stdout_lines=[], stderr_lines=["frame=1"], returncode=0))
    monkeypatch.setattr(ffmpeg_engine.subprocess, "Popen", ff_factory)
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg_engine, "_estimer_duree_hls", lambda *a: 100.0)
    monkeypatch.setattr(ffmpeg_engine, "TAILLE_MIN_FICHIER", 1)
    _neutralize(monkeypatch, ffmpeg_engine)
    ffmpeg_engine.ffmpeg_download("http://host/x.m3u8", str(tmp_path), "ep")
    assert ff_factory.kwargs.get("start_new_session") is True

    nm_final = tmp_path / "nm.mp4"
    nm_final.write_bytes(b"z" * 64)
    nm_factory = FakePopenFactory(FakeProc(stdout_lines=["Total 5 Segments found", "Done"], returncode=0))
    monkeypatch.setattr(nm3u8dl.subprocess, "Popen", nm_factory)
    monkeypatch.setattr(nm3u8dl, "_get_nm3u8dl_path", lambda: "N_m3u8DL-RE")
    monkeypatch.setattr(nm3u8dl, "_get_user_settings", lambda: {})
    monkeypatch.setattr(nm3u8dl, "_monitor_tmp", lambda *a, **k: None)
    monkeypatch.setattr(nm3u8dl, "_trouver_fichier_final", lambda d, n, avant=None: str(nm_final))
    monkeypatch.setattr(nm3u8dl, "_remux_fix", lambda chemin, cb: chemin)
    monkeypatch.setattr(nm3u8dl, "_spawn_proc_watchdog", lambda *a, **k: threading.Event())
    nm3u8dl.nm3u8dl_download("http://host/x.m3u8", str(tmp_path), "ep")
    assert nm_factory.kwargs.get("start_new_session") is True


def test_nm3u8dl_watchdog_attached_when_stdout_none(tmp_path, monkeypatch):
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"z" * 64)

    calls = []

    def _fake_watchdog(proc, cancelled, timeout):
        calls.append((proc, timeout))
        return threading.Event()

    factory = FakePopenFactory(FakeProc(stdout_lines=None, returncode=0))
    monkeypatch.setattr(nm3u8dl.subprocess, "Popen", factory)
    monkeypatch.setattr(nm3u8dl, "_get_nm3u8dl_path", lambda: "N_m3u8DL-RE")
    monkeypatch.setattr(nm3u8dl, "_get_user_settings", lambda: {})
    monkeypatch.setattr(nm3u8dl, "_monitor_tmp", lambda *a, **k: None)
    monkeypatch.setattr(nm3u8dl, "_trouver_fichier_final", lambda d, n, avant=None: str(final))
    monkeypatch.setattr(nm3u8dl, "_remux_fix", lambda chemin, cb: chemin)
    monkeypatch.setattr(nm3u8dl, "_spawn_proc_watchdog", _fake_watchdog)

    res = nm3u8dl.nm3u8dl_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res == str(final)
    assert calls and calls[0][1] == nm3u8dl.TIMEOUT_GLOBAL_DOWNLOAD
