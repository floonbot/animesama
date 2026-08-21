"""Regression: pause must hold between episodes (not only while a download
subprocess is already registered). Two mechanisms:
1. _traiter_episode awaits _attendre_reprise before starting each episode, so a
   pause during scraping/interception/anti-ban of the next episode is honoured.
2. register_proc suspends a subprocess spawned *during* an active pause window,
   and queue.pause()/reprendre() toggle that _proc_registry pause flag.

Order-safe: proc-registry globals (_actifs, _pause_en_cours) are snapshotted and
restored; the autouse conftest fixture also resets the pause flag.
"""

import asyncio
import threading
import types

import pytest

import engine.download.methods._proc_registry as pr
import engine.download.worker as worker


class _FakeQ:
    def __init__(self):
        self._paused = threading.Event()


def test_attendre_reprise_noop_without_paused_attr():
    asyncio.run(worker._attendre_reprise(object()))


def test_attendre_reprise_returns_when_not_paused():
    asyncio.run(worker._attendre_reprise(_FakeQ()))


def test_attendre_reprise_exits_on_cancel(monkeypatch):
    q = _FakeQ()
    q._paused.set()
    monkeypatch.setattr(worker, "_est_annule", lambda queue: True)
    asyncio.run(worker._attendre_reprise(q))


def test_attendre_reprise_blocks_until_resumed(monkeypatch):
    q = _FakeQ()
    q._paused.set()
    monkeypatch.setattr(worker, "_est_annule", lambda queue: False)

    async def scenario():
        task = asyncio.ensure_future(worker._attendre_reprise(q))
        await asyncio.sleep(0.05)
        assert not task.done()
        q._paused.clear()
        await asyncio.wait_for(task, timeout=3.0)

    asyncio.run(scenario())


class _FakePsutilProc:
    def __init__(self, pid, children=None):
        self.pid = pid
        self._children = children or []
        self.suspended = 0

    def children(self, recursive=True):
        return list(self._children)

    def suspend(self):
        self.suspended += 1

    def poll(self):
        return None


@pytest.fixture
def _isolate_pr():
    actifs_snap = set(pr._actifs)
    pause_snap = pr._pause_en_cours
    pr._actifs.clear()
    yield
    pr._actifs.clear()
    pr._actifs.update(actifs_snap)
    pr.set_pause_state(pause_snap)


def test_register_proc_suspends_new_proc_when_paused(monkeypatch, _isolate_pr):
    child = _FakePsutilProc(pid=601)
    parent = _FakePsutilProc(pid=600, children=[child])
    mod = types.ModuleType("fake_psutil")
    mod.STATUS_STOPPED = "stopped"
    mod.Process = lambda pid: parent if pid == 600 else _FakePsutilProc(pid)
    monkeypatch.setattr(pr, "_psutil", mod)

    pr.set_pause_state(True)
    proc = _FakePsutilProc(pid=600)
    pr.register_proc(proc)

    assert proc in pr._actifs
    assert parent.suspended == 1
    assert child.suspended == 1


def test_register_proc_does_not_suspend_when_not_paused(monkeypatch, _isolate_pr):
    parent = _FakePsutilProc(pid=610)
    mod = types.ModuleType("fake_psutil")
    mod.STATUS_STOPPED = "stopped"
    mod.Process = lambda pid: parent if pid == 610 else _FakePsutilProc(pid)
    monkeypatch.setattr(pr, "_psutil", mod)

    pr.set_pause_state(False)
    proc = _FakePsutilProc(pid=610)
    pr.register_proc(proc)

    assert proc in pr._actifs
    assert parent.suspended == 0


def test_queue_pause_toggles_proc_pause_flag(_isolate_pr):
    from engine.download.queue import DownloadQueue

    q = DownloadQueue()
    q._current = {"titre": "X"}

    assert pr._pause_en_cours is False
    q.pause()
    assert pr._pause_en_cours is True
    q.reprendre()
    assert pr._pause_en_cours is False
