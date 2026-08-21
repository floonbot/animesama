import threading

import engine.download._engine_utils as u
import engine.download.methods._proc_registry as proc_registry
from engine.download.methods import ffmpeg_engine, ytdlp_engine


class _FakeProc:
    def __init__(self, poll_value=None, stderr_lines=None, stdout_lines=None, returncode=0):
        self._poll_value = poll_value
        self.returncode = returncode
        self.pid = 4321
        self.stderr = iter(stderr_lines) if stderr_lines is not None else None
        self.stdout = iter(stdout_lines) if stdout_lines is not None else None

    def poll(self):
        return self._poll_value

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        return None

    def terminate(self):
        return None


class _FakePopenFactory:
    def __init__(self, proc):
        self.proc = proc

    def __call__(self, cmd, *a, **k):
        return self.proc


class _FakeThread:
    instances: list = []

    def __init__(self, target=None, daemon=None, name=None, **kwargs):
        self.target = target
        _FakeThread.instances.append(self)

    def start(self):
        return None


class _ScriptedWait:
    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.calls = []

    def __call__(self, timeout):
        self.calls.append(timeout)
        return self.scripted.pop(0) if self.scripted else True


class _ScriptedClock:
    def __init__(self, values):
        self.values = list(values)

    def __call__(self):
        return self.values.pop(0) if self.values else 0.0


class _FakeClock:
    def __init__(self, start=1000.0, step=5.0):
        self.now = start
        self.step = step

    def __call__(self):
        v = self.now
        self.now += self.step
        return v


def test_watchdog_kills_on_continuous_stall(monkeypatch, caplog):
    _FakeThread.instances = []
    monkeypatch.setattr(u.threading, "Thread", _FakeThread)
    killed = []
    monkeypatch.setattr(u, "terminate_tree", lambda p: killed.append(p))
    monkeypatch.setattr(proc_registry, "is_suspended", lambda p: False)
    monkeypatch.setattr(
        u.time, "time",
        _ScriptedClock([1000.0, 1000.0, 1001.0, 1002.0, 1003.0, 1004.0]),
    )

    activity = [1000.0]
    proc = _FakeProc(poll_value=None)
    stop = u.spawn_proc_watchdog(proc, None, 100000.0, activity, 3.0)
    monkeypatch.setattr(stop, "wait", _ScriptedWait([False, False, False, False]))

    with caplog.at_level("ERROR", logger="engine.download.engine_utils"):
        _FakeThread.instances[0].target()

    assert killed == [proc]
    assert "stall" in caplog.text.lower()


def test_watchdog_treats_large_jump_as_sleep_not_stall(monkeypatch):
    _FakeThread.instances = []
    monkeypatch.setattr(u.threading, "Thread", _FakeThread)
    killed = []
    monkeypatch.setattr(u, "terminate_tree", lambda p: killed.append(p))
    monkeypatch.setattr(proc_registry, "is_suspended", lambda p: False)
    monkeypatch.setattr(u.time, "time", _ScriptedClock([1000.0, 1000.0, 1400.0]))

    activity = [1000.0]
    proc = _FakeProc(poll_value=None)
    stop = u.spawn_proc_watchdog(proc, None, 100000.0, activity, 300.0)
    monkeypatch.setattr(stop, "wait", _ScriptedWait([False, True]))

    _FakeThread.instances[0].target()

    assert killed == []


def test_watchdog_does_not_kill_when_activity_is_fresh(monkeypatch):
    _FakeThread.instances = []
    monkeypatch.setattr(u.threading, "Thread", _FakeThread)
    killed = []
    monkeypatch.setattr(u, "terminate_tree", lambda p: killed.append(p))
    monkeypatch.setattr(proc_registry, "is_suspended", lambda p: False)
    monkeypatch.setattr(u.time, "time", _ScriptedClock([1000.0, 1000.0, 1001.0]))

    activity = [1050.0]
    proc = _FakeProc(poll_value=None)
    stop = u.spawn_proc_watchdog(proc, None, 100000.0, activity, 300.0)
    monkeypatch.setattr(stop, "wait", _ScriptedWait([False, True]))

    _FakeThread.instances[0].target()

    assert killed == []


def test_ffmpeg_wires_stall_watchdog_and_updates_activity(tmp_path, monkeypatch):
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"x" * 16)
    captured = {}

    def fake_watchdog(proc, cancelled, timeout_s, activity=None, stall_s=0.0):
        captured["activity"] = activity
        captured["stall_s"] = stall_s
        captured["initial"] = activity[0] if activity is not None else None
        return threading.Event()

    monkeypatch.setattr(ffmpeg_engine, "_spawn_proc_watchdog", fake_watchdog)
    monkeypatch.setattr(
        ffmpeg_engine.subprocess, "Popen",
        _FakePopenFactory(_FakeProc(stderr_lines=["frame=1 ", "frame=2 "], returncode=0)),
    )
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg_engine, "_estimer_duree_hls", lambda url, h: 0.0)
    monkeypatch.setattr(ffmpeg_engine, "register_proc", lambda *a, **k: None)
    monkeypatch.setattr(ffmpeg_engine, "unregister_proc", lambda *a, **k: None)
    monkeypatch.setattr(ffmpeg_engine, "_valider_sortie_ffmpeg", lambda *a: str(final))
    monkeypatch.setattr(ffmpeg_engine.time, "time", _FakeClock(start=1000.0, step=5.0))

    ffmpeg_engine.ffmpeg_download("http://h/v.m3u8", str(tmp_path), "ep")

    assert captured["stall_s"] > 0
    assert isinstance(captured["activity"], list)
    assert captured["activity"][0] > captured["initial"]


def test_ytdlp_wires_stall_watchdog(tmp_path, monkeypatch):
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"x" * 16)
    captured = {}

    def fake_watchdog(proc, cancelled, timeout_s, activity=None, stall_s=0.0):
        captured["activity"] = activity
        captured["stall_s"] = stall_s
        return threading.Event()

    monkeypatch.setattr(ytdlp_engine, "_spawn_proc_watchdog", fake_watchdog)
    monkeypatch.setattr(
        ytdlp_engine.subprocess, "Popen",
        _FakePopenFactory(_FakeProc(stdout_lines=["[download]  1.0%", "[download]  2.0%"], returncode=0)),
    )
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp_engine, "_get_aria2c_path", lambda: None)
    monkeypatch.setattr(ytdlp_engine, "_trouver_fichier_final", lambda d, n: str(final))
    monkeypatch.setattr(ytdlp_engine, "register_proc", lambda *a, **k: None)
    monkeypatch.setattr(ytdlp_engine, "unregister_proc", lambda *a, **k: None)

    import engine.config.user_settings as user_settings
    monkeypatch.setattr(user_settings, "load_settings", lambda: {"qualite": "720"})

    ytdlp_engine.ytdlp_download("http://host/video", str(tmp_path), "ep")

    assert captured["stall_s"] > 0
    assert isinstance(captured["activity"], list)
