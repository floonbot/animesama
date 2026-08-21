import pytest

import engine.auth.manager as mgr_mod
from engine.auth.manager import AuthManager


class FakeStorage:
    pass


class FakeThread:
    instances = []

    def __init__(self, target=None, daemon=None, name=None):
        self.target = target
        self.daemon = daemon
        self.name = name
        self.started = False
        FakeThread.instances.append(self)

    def start(self):
        self.started = True

    def is_alive(self):
        return False


class FakeStop:
    def __init__(self, wait_returns):
        self._wait_returns = list(wait_returns)
        self.wait_intervals = []
        self.clear_calls = 0
        self.set_calls = 0

    def clear(self):
        self.clear_calls += 1

    def set(self):
        self.set_calls += 1

    def wait(self, interval):
        self.wait_intervals.append(interval)
        if self._wait_returns:
            return self._wait_returns.pop(0)
        return True


@pytest.fixture(autouse=True)
def _reset_module_globals(monkeypatch):
    saved_storage = mgr_mod.AuthStorage
    saved_thread = mgr_mod.threading.Thread
    FakeThread.instances = []
    yield
    mgr_mod.AuthStorage = saved_storage
    mgr_mod.threading.Thread = saved_thread
    FakeThread.instances = []


@pytest.fixture
def mgr(monkeypatch):
    monkeypatch.setattr(mgr_mod, "AuthStorage", FakeStorage)
    return AuthManager()


def _start_capture(mgr, monkeypatch, stop):
    mgr._keepalive_stop = stop
    monkeypatch.setattr(mgr_mod.threading, "Thread", FakeThread)
    before = len(FakeThread.instances)
    mgr.start_keepalive_loop()
    assert len(FakeThread.instances) == before + 1
    return FakeThread.instances[-1].target


def test_old_generation_stops_after_restart(mgr, monkeypatch):
    mgr._logged_in = True
    monkeypatch.setattr(mgr, "keepalive_session", lambda: True)

    old_stop = FakeStop([False, False, False])
    old_loop = _start_capture(mgr, monkeypatch, old_stop)
    old_gen = mgr._keepalive_gen

    new_stop = FakeStop([False, True])
    new_loop = _start_capture(mgr, monkeypatch, new_stop)
    assert mgr._keepalive_gen == old_gen + 1

    old_loop()
    assert len(old_stop.wait_intervals) == 1

    new_loop()
    assert len(new_stop.wait_intervals) == 2


def test_set_on_old_generation_does_not_disturb_new(mgr, monkeypatch):
    mgr._logged_in = True
    monkeypatch.setattr(mgr, "keepalive_session", lambda: True)

    old_stop = FakeStop([False, False])
    _start_capture(mgr, monkeypatch, old_stop)

    new_stop = FakeStop([False, True])
    new_loop = _start_capture(mgr, monkeypatch, new_stop)

    old_stop.set()
    new_loop()
    assert len(new_stop.wait_intervals) == 2
