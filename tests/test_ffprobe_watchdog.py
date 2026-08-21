import json

import engine.download._engine_utils as u
import engine.download.methods._proc_registry as proc_registry
from engine.config.settings import DEFAULT_USER_AGENT
from engine.download.methods import ffmpeg_engine


class _FakeCompleted:
    def __init__(self, returncode, stdout):
        self.returncode = returncode
        self.stdout = stdout


class _RunRecorder:
    def __init__(self, result=None, exc=None):
        self.result = result
        self.exc = exc
        self.calls = []

    def __call__(self, cmd, *args, **kwargs):
        self.calls.append(list(cmd))
        if self.exc is not None:
            raise self.exc
        return self.result


def test_estimer_duree_no_ffprobe_returns_zero_without_run(monkeypatch):
    recorder = _RunRecorder(result=_FakeCompleted(0, "{}"))
    monkeypatch.setattr(ffmpeg_engine.shutil, "which", lambda name: None)
    monkeypatch.setattr(ffmpeg_engine.subprocess, "run", recorder)

    out = ffmpeg_engine._estimer_duree_hls("http://host/x.m3u8", {})

    assert out == 0.0
    assert recorder.calls == []


def test_estimer_duree_parses_duration(monkeypatch):
    recorder = _RunRecorder(
        result=_FakeCompleted(0, json.dumps({"format": {"duration": "123.5"}}))
    )
    monkeypatch.setattr(ffmpeg_engine.shutil, "which", lambda name: "ffprobe")
    monkeypatch.setattr(ffmpeg_engine.subprocess, "run", recorder)

    out = ffmpeg_engine._estimer_duree_hls("http://host/x.m3u8", {})

    assert out == 123.5
    assert len(recorder.calls) == 1


def test_estimer_duree_nonzero_returncode_returns_zero(monkeypatch):
    recorder = _RunRecorder(
        result=_FakeCompleted(1, json.dumps({"format": {"duration": "123.5"}}))
    )
    monkeypatch.setattr(ffmpeg_engine.shutil, "which", lambda name: "ffprobe")
    monkeypatch.setattr(ffmpeg_engine.subprocess, "run", recorder)

    out = ffmpeg_engine._estimer_duree_hls("http://host/x.m3u8", {})

    assert out == 0.0


def test_estimer_duree_run_raises_returns_zero(monkeypatch):
    recorder = _RunRecorder(exc=OSError("boom"))
    monkeypatch.setattr(ffmpeg_engine.shutil, "which", lambda name: "ffprobe")
    monkeypatch.setattr(ffmpeg_engine.subprocess, "run", recorder)

    out = ffmpeg_engine._estimer_duree_hls("http://host/x.m3u8", {})

    assert out == 0.0
    assert len(recorder.calls) == 1


def test_estimer_duree_zero_or_absent_returns_zero(monkeypatch):
    recorder = _RunRecorder(result=_FakeCompleted(0, json.dumps({"format": {}})))
    monkeypatch.setattr(ffmpeg_engine.shutil, "which", lambda name: "ffprobe")
    monkeypatch.setattr(ffmpeg_engine.subprocess, "run", recorder)

    assert ffmpeg_engine._estimer_duree_hls("http://host/x.m3u8", {}) == 0.0

    recorder_zero = _RunRecorder(
        result=_FakeCompleted(0, json.dumps({"format": {"duration": "0"}}))
    )
    monkeypatch.setattr(ffmpeg_engine.subprocess, "run", recorder_zero)

    assert ffmpeg_engine._estimer_duree_hls("http://host/x.m3u8", {}) == 0.0


def test_estimer_duree_cmd_contains_ffprobe_url_and_user_agent_no_referer(monkeypatch):
    recorder = _RunRecorder(
        result=_FakeCompleted(0, json.dumps({"format": {"duration": "10"}}))
    )
    monkeypatch.setattr(ffmpeg_engine.shutil, "which", lambda name: "ffprobe")
    monkeypatch.setattr(ffmpeg_engine.subprocess, "run", recorder)

    ffmpeg_engine._estimer_duree_hls("http://host/clip.m3u8", {})

    cmd = recorder.calls[0]
    assert cmd[0] == "ffprobe"
    assert "http://host/clip.m3u8" in cmd
    assert "-user_agent" in cmd
    assert cmd[cmd.index("-user_agent") + 1] == DEFAULT_USER_AGENT
    assert "-referer" not in cmd


def test_estimer_duree_cmd_includes_referer_when_header_present(monkeypatch):
    recorder = _RunRecorder(
        result=_FakeCompleted(0, json.dumps({"format": {"duration": "10"}}))
    )
    monkeypatch.setattr(ffmpeg_engine.shutil, "which", lambda name: "ffprobe")
    monkeypatch.setattr(ffmpeg_engine.subprocess, "run", recorder)

    ffmpeg_engine._estimer_duree_hls(
        "http://host/clip.m3u8",
        {"user-agent": "CustomUA", "referer": "http://ref.example/"},
    )

    cmd = recorder.calls[0]
    assert "-referer" in cmd
    assert cmd[cmd.index("-referer") + 1] == "http://ref.example/"
    assert cmd[cmd.index("-user_agent") + 1] == "CustomUA"


class _FakeProc:
    def __init__(self, poll_value):
        self._poll_value = poll_value
        self.pid = 4321

    def poll(self):
        return self._poll_value


class _FakeThread:
    instances = []

    def __init__(self, target=None, daemon=None, name=None, **kwargs):
        self.target = target
        self.daemon = daemon
        self.name = name
        self.started = False
        _FakeThread.instances.append(self)

    def start(self):
        self.started = True


class _ScriptedWait:
    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.calls = []

    def __call__(self, timeout):
        self.calls.append(timeout)
        if self.scripted:
            return self.scripted.pop(0)
        return True


class _ScriptedClock:
    def __init__(self, values):
        self.values = list(values)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.values:
            return self.values.pop(0)
        return 0.0


def _capture_target(monkeypatch):
    _FakeThread.instances = []
    monkeypatch.setattr(u.threading, "Thread", _FakeThread)


def test_watchdog_timeout_terminates_and_logs(monkeypatch, caplog):
    _capture_target(monkeypatch)
    killed = []
    monkeypatch.setattr(u, "terminate_tree", lambda p: killed.append(p))
    monkeypatch.setattr(proc_registry, "is_suspended", lambda p: False)
    monkeypatch.setattr(u.time, "time", _ScriptedClock([1000.0, 9999.0]))

    proc = _FakeProc(poll_value=None)
    stop = u.spawn_proc_watchdog(proc, None, 10.0)
    monkeypatch.setattr(stop, "wait", _ScriptedWait([False]))

    thread = _FakeThread.instances[0]
    assert thread.started is True
    with caplog.at_level("ERROR", logger="engine.download.engine_utils"):
        thread.target()

    assert killed == [proc]
    assert "timeout" in caplog.text.lower()


def test_watchdog_cancelled_terminates_without_timeout_log(monkeypatch, caplog):
    _capture_target(monkeypatch)
    killed = []
    monkeypatch.setattr(u, "terminate_tree", lambda p: killed.append(p))
    monkeypatch.setattr(proc_registry, "is_suspended", lambda p: False)
    monkeypatch.setattr(u.time, "time", _ScriptedClock([1000.0, 1000.0]))

    proc = _FakeProc(poll_value=None)
    stop = u.spawn_proc_watchdog(proc, [True], 100000.0)
    monkeypatch.setattr(stop, "wait", _ScriptedWait([False]))

    with caplog.at_level("ERROR", logger="engine.download.engine_utils"):
        _FakeThread.instances[0].target()

    assert killed == [proc]
    assert "timeout" not in caplog.text.lower()


def test_watchdog_suspended_extends_deadline_to_survive(monkeypatch):
    """The +=0.5 suspension extension must push the deadline past a clock value that would otherwise expire."""
    _capture_target(monkeypatch)
    killed = []
    monkeypatch.setattr(u, "terminate_tree", lambda p: killed.append(p))
    suspended = iter([True, False])
    monkeypatch.setattr(proc_registry, "is_suspended", lambda p: next(suspended))
    monkeypatch.setattr(u.time, "time", _ScriptedClock([1000.0, 1010.2]))

    proc = _FakeProc(poll_value=None)
    stop = u.spawn_proc_watchdog(proc, None, 10.0)
    scripted = _ScriptedWait([False, False])
    monkeypatch.setattr(stop, "wait", scripted)

    _FakeThread.instances[0].target()

    assert killed == []
    assert scripted.calls == [0.5, 0.5, 0.5]


def test_watchdog_proc_already_done_returns_without_terminate(monkeypatch):
    _capture_target(monkeypatch)
    killed = []
    monkeypatch.setattr(u, "terminate_tree", lambda p: killed.append(p))
    monkeypatch.setattr(proc_registry, "is_suspended", lambda p: False)
    monkeypatch.setattr(u.time, "time", _ScriptedClock([1000.0]))

    proc = _FakeProc(poll_value=0)
    stop = u.spawn_proc_watchdog(proc, [True], 10.0)
    monkeypatch.setattr(stop, "wait", _ScriptedWait([False]))

    _FakeThread.instances[0].target()

    assert killed == []
