import types

import pytest

import engine.download.methods._proc_registry as pr


@pytest.fixture(autouse=True)
def _isoler_etat():
    actifs_snap = set(pr._actifs)
    cancel_snap = pr._cancel_en_cours
    pause_snap = pr._pause_en_cours
    psutil_snap = pr._psutil
    pr._actifs.clear()
    pr._cancel_en_cours = False
    pr._pause_en_cours = False
    try:
        yield
    finally:
        pr._actifs.clear()
        pr._actifs.update(actifs_snap)
        pr._cancel_en_cours = cancel_snap
        pr._pause_en_cours = pause_snap
        pr._psutil = psutil_snap


class _FakeProc:
    def __init__(self, pid=1, code=None):
        self.pid = pid
        self._code = code

    def poll(self):
        return self._code


class _FakePsutilProc:
    def __init__(self, pid, on_suspend):
        self.pid = pid
        self.suspended = 0
        self._on_suspend = on_suspend

    def children(self, recursive=True):
        return []

    def suspend(self):
        self._on_suspend()
        self.suspended += 1


def _fake_psutil_module(registry):
    mod = types.ModuleType("fake_psutil")
    mod.STATUS_STOPPED = "stopped"

    def _Process(pid):
        return registry[pid]

    mod.Process = _Process
    return mod


def test_register_proc_suspend_sous_pause_tient_le_verrou(monkeypatch):
    lock_state = {}

    def _record_lock():
        lock_state["held"] = pr._lock.locked()

    parent = _FakePsutilProc(200, on_suspend=_record_lock)
    monkeypatch.setattr(pr, "_psutil", _fake_psutil_module({200: parent}))
    pr.set_pause_state(True)

    pr.register_proc(_FakeProc(pid=200, code=None))

    assert parent.suspended == 1
    assert lock_state.get("held") is True
