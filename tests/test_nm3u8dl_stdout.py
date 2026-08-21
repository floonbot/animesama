import threading

import pytest

import engine.download.methods.nm3u8dl as nm3u8dl
from engine.domain.exceptions import DownloadCancelled


class _FakeProc:
    def __init__(self, lines, returncode=0):
        self.stdout = iter(list(lines))
        self.returncode = returncode
        self.killed = False

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True


def _state(now):
    return {
        "total_segs": 0,
        "start_time": now,
        "last_size": 0,
        "last_time": now,
        "speed_bps": 0.0,
        "phase": "init",
    }


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr(nm3u8dl.time, "sleep", lambda *_a, **_k: None)


def test_global_timeout_raises_and_terminates(monkeypatch):
    monkeypatch.setattr(nm3u8dl, "is_suspended", lambda _p: False)
    terminated = []
    monkeypatch.setattr(nm3u8dl, "_terminate_tree", lambda p: terminated.append(p))

    proc = _FakeProc([])
    state = _state(100.0)

    with pytest.raises(RuntimeError) as exc:
        nm3u8dl._lire_stdout_avec_timeout(proc, None, None, state, timeout_s=0)

    assert "Timeout global" in str(exc.value)
    assert not isinstance(exc.value, DownloadCancelled)
    assert terminated == [proc]


def test_cancel_after_interpreting_line_raises_cancelled(monkeypatch):
    monkeypatch.setattr(nm3u8dl, "is_suspended", lambda _p: False)
    terminated = []
    monkeypatch.setattr(nm3u8dl, "_terminate_tree", lambda p: terminated.append(p))

    cancelled = [False]
    seen = []

    def callback(pct, ligne):
        seen.append((pct, ligne))
        cancelled[0] = True

    proc = _FakeProc(["Done"], returncode=None)
    state = _state(100.0)

    with pytest.raises(DownloadCancelled):
        nm3u8dl._lire_stdout_avec_timeout(
            proc, cancelled, callback, state, timeout_s=3600
        )

    assert seen == [(100.0, "✅ Terminé !")]
    assert state["phase"] == "done"
    assert terminated == [proc]


def test_suspended_with_cancel_raises_cancelled(monkeypatch):
    monkeypatch.setattr(nm3u8dl, "is_suspended", lambda _p: True)
    terminated = []
    monkeypatch.setattr(nm3u8dl, "_terminate_tree", lambda p: terminated.append(p))

    proc = _FakeProc([])
    state = _state(100.0)

    with pytest.raises(DownloadCancelled):
        nm3u8dl._lire_stdout_avec_timeout(
            proc, [True], None, state, timeout_s=3600
        )

    assert terminated == [proc]


def test_normal_completion_returns_none_and_interprets(monkeypatch):
    monkeypatch.setattr(nm3u8dl, "is_suspended", lambda _p: False)
    monkeypatch.setattr(nm3u8dl, "_terminate_tree", lambda _p: None)

    seen = []

    def callback(pct, ligne):
        seen.append((pct, ligne))

    proc = _FakeProc(["Total 5 Segments found", "Done"], returncode=None)
    state = _state(100.0)

    result = nm3u8dl._lire_stdout_avec_timeout(
        proc, None, callback, state, timeout_s=3600
    )

    assert result is None
    assert state["total_segs"] == 5
    assert state["phase"] == "done"
    assert (100.0, "✅ Terminé !") in seen


class _BlockingStdout:
    def __init__(self):
        self._ev = threading.Event()

    def __iter__(self):
        return self

    def __next__(self):
        self._ev.wait(timeout=30)
        raise StopIteration


class _AliveProc:
    def __init__(self):
        self.stdout = _BlockingStdout()
        self.killed = False

    def poll(self):
        return None

    def kill(self):
        self.killed = True


class _Clock:
    def __init__(self, values):
        self._values = list(values)
        self._last = self._values[-1] if self._values else 0.0

    def __call__(self):
        if self._values:
            self._last = self._values.pop(0)
        return self._last


def test_stall_timeout_kills_inactive_process(monkeypatch):
    monkeypatch.setattr(nm3u8dl, "is_suspended", lambda _p: False)
    monkeypatch.setattr(nm3u8dl, "STALL_TIMEOUT", 600)
    terminated = []
    monkeypatch.setattr(nm3u8dl, "_terminate_tree", lambda p: terminated.append(p))
    monkeypatch.setattr(nm3u8dl.time, "time", _Clock([0.0, 0.0, 0.0, 700.0]))

    proc = _AliveProc()
    state = _state(0.0)

    with pytest.raises(RuntimeError) as exc:
        nm3u8dl._lire_stdout_avec_timeout(proc, None, None, state, timeout_s=10000)

    assert "Stall" in str(exc.value)
    assert not isinstance(exc.value, DownloadCancelled)
    assert terminated == [proc]
