import os
import threading

from engine.download.methods import nm3u8dl


class _FakeProc:
    def __init__(self, poll_value=0, stdout=None):
        self._poll = poll_value
        self.stdout = stdout
        self.wait_calls = 0
        self.kill_calls = 0

    def poll(self):
        return self._poll

    def wait(self, timeout=None):
        self.wait_calls += 1

    def kill(self):
        self.kill_calls += 1


def _make_tmp(tmp_path):
    d = tmp_path / "_tmp_ep"
    d.mkdir()
    (d / "seg.ts").write_bytes(b"x")
    return str(d)


def test_cleanup_keeps_tmp_when_not_succeeded_and_not_cancelled(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(nm3u8dl, "unregister_proc", lambda *a, **k: None)
    tmp = _make_tmp(tmp_path)
    with caplog.at_level("INFO", logger="engine.download.methods.nm3u8dl"):
        nm3u8dl._cleanup_run(None, None, threading.Event(), None, tmp, False, False)
    assert os.path.isdir(tmp)
    assert "Segments conservés" in caplog.text


def test_cleanup_removes_tmp_when_succeeded(tmp_path, monkeypatch):
    monkeypatch.setattr(nm3u8dl, "unregister_proc", lambda *a, **k: None)
    tmp = _make_tmp(tmp_path)
    nm3u8dl._cleanup_run(None, None, threading.Event(), None, tmp, True, False)
    assert not os.path.exists(tmp)


def test_cleanup_removes_tmp_when_cancelled(tmp_path, monkeypatch):
    monkeypatch.setattr(nm3u8dl, "unregister_proc", lambda *a, **k: None)
    tmp = _make_tmp(tmp_path)
    nm3u8dl._cleanup_run(None, None, threading.Event(), None, tmp, False, True)
    assert not os.path.exists(tmp)


def test_cleanup_terminates_running_proc_before_unregister(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(nm3u8dl, "unregister_proc", lambda p: calls.append(("unregister", p)))
    monkeypatch.setattr(nm3u8dl, "_terminate_tree", lambda p: calls.append(("terminate", p)))
    proc = _FakeProc(poll_value=None)
    nm3u8dl._cleanup_run(proc, None, threading.Event(), None, _make_tmp(tmp_path), True, False)
    assert ("terminate", proc) in calls
    assert calls[-1] == ("unregister", proc)
    assert proc.wait_calls == 1
    assert proc.kill_calls == 0


def test_cleanup_unregisters_even_when_proc_already_finished(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(nm3u8dl, "unregister_proc", lambda p: calls.append(p))
    monkeypatch.setattr(nm3u8dl, "_terminate_tree", lambda p: calls.append("terminate"))
    proc = _FakeProc(poll_value=0)
    nm3u8dl._cleanup_run(proc, None, threading.Event(), None, _make_tmp(tmp_path), True, False)
    assert "terminate" not in calls
    assert calls == [proc]


def test_cleanup_sets_watchdog_and_stop_monitor(tmp_path, monkeypatch):
    monkeypatch.setattr(nm3u8dl, "unregister_proc", lambda *a, **k: None)
    watchdog = threading.Event()
    stop_monitor = threading.Event()
    nm3u8dl._cleanup_run(None, watchdog, stop_monitor, None, str(tmp_path / "missing"), True, False)
    assert watchdog.is_set()
    assert stop_monitor.is_set()
