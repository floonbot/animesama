import engine.download._engine_utils as u


class _FakeProc:
    def __init__(self, pid=42, poll_value=None):
        self.pid = pid
        self._poll = poll_value
        self.terminated = False
        self.killed = False
        self.waited = []

    def poll(self):
        return self._poll

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        self.waited.append(timeout)


def test_kill_process_group_kills_distinct_group(monkeypatch):
    killed = []
    monkeypatch.setattr(u.os, "killpg", lambda pgid, sig: killed.append((pgid, sig)), raising=False)
    monkeypatch.setattr(u.os, "getpgid", lambda pid: 555, raising=False)
    monkeypatch.setattr(u.os, "getpgrp", lambda: 999, raising=False)

    assert u._kill_process_group(_FakeProc(pid=42)) is True
    assert len(killed) == 1
    assert killed[0][0] == 555


def test_kill_process_group_refuses_own_group(monkeypatch):
    killed = []
    monkeypatch.setattr(u.os, "killpg", lambda pgid, sig: killed.append(pgid), raising=False)
    monkeypatch.setattr(u.os, "getpgid", lambda pid: 777, raising=False)
    monkeypatch.setattr(u.os, "getpgrp", lambda: 777, raising=False)

    assert u._kill_process_group(_FakeProc(pid=42)) is False
    assert killed == []


def test_kill_process_group_false_when_killpg_absent(monkeypatch):
    monkeypatch.delattr(u.os, "killpg", raising=False)
    assert u._kill_process_group(_FakeProc(pid=42)) is False


def test_kill_process_group_swallows_lookup_error(monkeypatch):
    def _boom(_pid):
        raise ProcessLookupError("gone")

    monkeypatch.setattr(u.os, "killpg", lambda *a: None, raising=False)
    monkeypatch.setattr(u.os, "getpgid", _boom, raising=False)
    monkeypatch.setattr(u.os, "getpgrp", lambda: 1, raising=False)

    assert u._kill_process_group(_FakeProc(pid=42)) is False


def test_terminate_tree_posix_prefers_process_group(monkeypatch):
    monkeypatch.setattr(u.os, "name", "posix")
    killed = []
    monkeypatch.setattr(u.os, "killpg", lambda pgid, sig: killed.append(pgid), raising=False)
    monkeypatch.setattr(u.os, "getpgid", lambda pid: 600, raising=False)
    monkeypatch.setattr(u.os, "getpgrp", lambda: 1, raising=False)

    proc = _FakeProc(pid=42)
    u.terminate_tree(proc)

    assert killed == [600]
    assert proc.terminated is False
