import pytest

import engine.auth.manager as mgr_mod
from engine.auth.manager import _KEEPALIVE_INTERVAL, AuthManager


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


class AliveThread:
    def __init__(self):
        self.is_alive_calls = 0

    def is_alive(self):
        self.is_alive_calls += 1
        return True

    def start(self):
        raise AssertionError("start() must not be called on an existing alive thread")


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


def _capture_loop(mgr, monkeypatch):
    monkeypatch.setattr(mgr_mod.threading, "Thread", FakeThread)
    mgr.start_keepalive_loop()
    assert len(FakeThread.instances) == 1
    thread = FakeThread.instances[0]
    assert thread.started is True
    assert thread.daemon is True
    assert thread.name == "auth_keepalive"
    assert mgr._keepalive_thread is thread
    return thread.target


def test_one_successful_iteration_keeps_base_interval(mgr, monkeypatch):
    mgr._logged_in = True
    stop = FakeStop([False, True])
    mgr._keepalive_stop = stop

    calls = []
    monkeypatch.setattr(mgr, "keepalive_session", lambda: calls.append(1) or True)

    loop = _capture_loop(mgr, monkeypatch)
    loop()

    assert len(calls) == 1
    assert stop.wait_intervals == [_KEEPALIVE_INTERVAL, _KEEPALIVE_INTERVAL]


def test_success_after_failure_resets_backoff(mgr, monkeypatch):
    """A failure grows the interval; a subsequent success resets echecs so the next interval is base again."""
    mgr._logged_in = True
    stop = FakeStop([False, False, True])
    mgr._keepalive_stop = stop

    outcomes = iter([False, True])
    monkeypatch.setattr(mgr, "keepalive_session", lambda: next(outcomes))

    loop = _capture_loop(mgr, monkeypatch)
    loop()

    assert stop.wait_intervals == [
        _KEEPALIVE_INTERVAL,
        min(_KEEPALIVE_INTERVAL * 2, 7200),
        _KEEPALIVE_INTERVAL,
    ]


def test_backoff_clamped_at_ceiling(mgr, monkeypatch):
    """Repeated failures clamp the interval at the 7200s ceiling."""
    mgr._logged_in = True
    stop = FakeStop([False, False, False, False, False, True])
    mgr._keepalive_stop = stop

    monkeypatch.setattr(mgr, "keepalive_session", lambda: False)

    loop = _capture_loop(mgr, monkeypatch)
    loop()

    assert max(stop.wait_intervals) == 7200
    assert all(i <= 7200 for i in stop.wait_intervals)


def test_backoff_grows_on_failure(mgr, monkeypatch):
    mgr._logged_in = True
    stop = FakeStop([False, False, True])
    mgr._keepalive_stop = stop

    monkeypatch.setattr(mgr, "keepalive_session", lambda: False)

    loop = _capture_loop(mgr, monkeypatch)
    loop()

    first, second, third = stop.wait_intervals
    assert first == _KEEPALIVE_INTERVAL
    assert second == min(_KEEPALIVE_INTERVAL * 2, 7200)
    assert second > first
    assert third == min(_KEEPALIVE_INTERVAL * 4, 7200)


def test_not_logged_in_skips_keepalive(mgr, monkeypatch):
    mgr._logged_in = False
    stop = FakeStop([False, True])
    mgr._keepalive_stop = stop

    calls = []
    monkeypatch.setattr(mgr, "keepalive_session", lambda: calls.append(1) or True)

    loop = _capture_loop(mgr, monkeypatch)
    loop()

    assert calls == []
    assert stop.wait_intervals == [_KEEPALIVE_INTERVAL, _KEEPALIVE_INTERVAL]


def test_reentrancy_guard_skips_when_thread_alive(mgr, monkeypatch):
    alive = AliveThread()
    mgr._keepalive_thread = alive
    monkeypatch.setattr(mgr_mod.threading, "Thread", FakeThread)

    mgr.start_keepalive_loop()

    assert alive.is_alive_calls == 1
    assert FakeThread.instances == []
    assert mgr._keepalive_thread is alive


def test_stop_sets_event(mgr):
    stop = FakeStop([])
    mgr._keepalive_stop = stop

    mgr.stop_keepalive_loop()

    assert stop.set_calls == 1


def test_start_clears_stop_before_launch(mgr, monkeypatch):
    stop = FakeStop([True])
    mgr._keepalive_stop = stop

    _capture_loop(mgr, monkeypatch)

    assert stop.clear_calls == 1


def test_relogin_after_stop_restarts_keepalive(mgr, monkeypatch):
    mgr._keepalive_thread = AliveThread()
    mgr.stop_keepalive_loop()
    assert mgr._keepalive_stop.is_set() is True

    monkeypatch.setattr(mgr_mod.threading, "Thread", FakeThread)
    mgr.start_keepalive_loop()

    assert len(FakeThread.instances) == 1
    assert mgr._keepalive_stop.is_set() is False
