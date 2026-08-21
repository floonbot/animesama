import sys
import types

import engine.download._engine_utils as u


class _FakeProc:
    def __init__(self, poll_value=None, pid=10):
        self._poll_value = poll_value
        self.pid = pid
        self.terminated = False
        self.killed = False
        self.waited = []

    def poll(self):
        return self._poll_value

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        self.waited.append(timeout)


def _install_fake_psutil(monkeypatch, killed, children_pids=(11, 12)):
    class _FakeChild:
        def __init__(self, pid):
            self.pid = pid

        def kill(self):
            killed.append(self.pid)

    class _FakeParent:
        def children(self, recursive=True):
            return [_FakeChild(p) for p in children_pids]

    fake = types.ModuleType("psutil")
    fake.Process = lambda pid: _FakeParent()
    monkeypatch.setitem(sys.modules, "psutil", fake)


def test_posix_fallback_kills_children_then_parent(monkeypatch):
    monkeypatch.setattr(u.os, "name", "posix")
    killed: list[int] = []
    _install_fake_psutil(monkeypatch, killed)

    proc = _FakeProc(poll_value=None, pid=10)
    u.terminate_tree(proc)

    assert killed == [11, 12]
    assert proc.terminated is True
    assert proc.waited == [3]


def test_nt_taskkill_failure_falls_back_to_tree_kill(monkeypatch):
    monkeypatch.setattr(u.os, "name", "nt")

    def _boom(*a, **k):
        raise OSError("no taskkill")

    monkeypatch.setattr(u.subprocess, "run", _boom)
    killed: list[int] = []
    _install_fake_psutil(monkeypatch, killed)

    proc = _FakeProc(poll_value=None, pid=10)
    u.terminate_tree(proc)

    assert killed == [11, 12]
    assert proc.terminated is True


def test_nt_taskkill_success_skips_tree_kill(monkeypatch):
    monkeypatch.setattr(u.os, "name", "nt")
    monkeypatch.setattr(u.subprocess, "run", lambda *a, **k: None)
    killed: list[int] = []
    _install_fake_psutil(monkeypatch, killed)

    proc = _FakeProc(poll_value=None, pid=10)
    u.terminate_tree(proc)

    assert killed == []
    assert proc.terminated is False


def test_child_kill_failure_is_swallowed(monkeypatch):
    monkeypatch.setattr(u.os, "name", "posix")

    class _BadChild:
        pid = 99

        def kill(self):
            raise RuntimeError("permission denied")

    class _Parent:
        def children(self, recursive=True):
            return [_BadChild()]

    fake = types.ModuleType("psutil")
    fake.Process = lambda pid: _Parent()
    monkeypatch.setitem(sys.modules, "psutil", fake)

    proc = _FakeProc(poll_value=None, pid=10)
    u.terminate_tree(proc)

    assert proc.terminated is True


def test_psutil_absent_still_terminates_parent(monkeypatch):
    monkeypatch.setattr(u.os, "name", "posix")
    monkeypatch.setitem(sys.modules, "psutil", None)

    proc = _FakeProc(poll_value=None, pid=10)
    u.terminate_tree(proc)

    assert proc.terminated is True
