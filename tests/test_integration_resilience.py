"""Gated real-process fault-injection proofs for the survivability guarantees.

Marked ``integration`` so the default deterministic suite skips them
(``addopts = -m 'not integration'``). Run explicitly with::

    pytest -m integration tests/test_integration_resilience.py

These spawn real OS processes and hard-kill them to prove, end to end, that:
the watchdog kills a hanging process; ``terminate_tree`` / ``kill_all_processes``
leave no orphan grandchildren even when ``taskkill`` fails; and a SIGKILL/
TerminateProcess of a writer mid-download leaves a durable ``current`` row that
``DownloadQueue.restore()`` recovers without loss.
"""

import subprocess
import sys
import time
from pathlib import Path

import pytest

psutil = pytest.importorskip("psutil")

from engine.download import _engine_utils as u
from engine.download.methods import _proc_registry
from engine.download.queue import DownloadQueue
from engine.download.store import DownloadStore

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parent.parent


def _wait_gone(pid, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not psutil.pid_exists(pid):
            return True
        try:
            status = psutil.Process(pid).status()
            if status in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD):
                return True
        except psutil.NoSuchProcess:
            return True
        time.sleep(0.05)
    return False


def _force_kill(pid):
    try:
        psutil.Process(pid).kill()
    except Exception:
        pass


def _spawn_sleeper():
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _spawn_parent_with_grandchild():
    code = (
        "import subprocess, sys, time\n"
        "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "print(c.pid, flush=True)\n"
        "time.sleep(60)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    child_pid = int(proc.stdout.readline().strip())
    return proc, child_pid


def test_watchdog_kills_real_hung_process():
    proc = _spawn_sleeper()
    try:
        assert proc.poll() is None
        stop = u.spawn_proc_watchdog(proc, None, timeout_s=1.0)
        try:
            assert _wait_gone(proc.pid, timeout=8.0), "watchdog did not kill the hung process"
        finally:
            stop.set()
    finally:
        _force_kill(proc.pid)
        try:
            proc.wait(timeout=3)
        except Exception:
            pass


def test_terminate_tree_kills_grandchild_when_taskkill_fails(monkeypatch):
    proc, child_pid = _spawn_parent_with_grandchild()
    try:
        def _taskkill_fails(*a, **k):
            raise subprocess.TimeoutExpired("taskkill", 10)

        monkeypatch.setattr(u.subprocess, "run", _taskkill_fails)

        u.terminate_tree(proc)

        assert _wait_gone(proc.pid), "parent survived terminate_tree"
        assert _wait_gone(child_pid), "orphan grandchild survived terminate_tree"
    finally:
        _force_kill(child_pid)
        _force_kill(proc.pid)
        try:
            proc.wait(timeout=3)
        except Exception:
            pass


def test_kill_all_processes_leaves_no_orphan_tree(monkeypatch):
    proc_a, child_a = _spawn_parent_with_grandchild()
    proc_b, child_b = _spawn_parent_with_grandchild()
    try:
        def _taskkill_fails(*a, **k):
            raise subprocess.TimeoutExpired("taskkill", 10)

        monkeypatch.setattr(u.subprocess, "run", _taskkill_fails)

        with _proc_registry._lock:
            _proc_registry._actifs.update({proc_a, proc_b})

        _proc_registry.kill_all_processes()

        for pid in (proc_a.pid, child_a, proc_b.pid, child_b):
            assert _wait_gone(pid), f"pid {pid} survived kill_all_processes"
    finally:
        with _proc_registry._lock:
            _proc_registry._actifs.discard(proc_a)
            _proc_registry._actifs.discard(proc_b)
        for pid in (child_a, child_b, proc_a.pid, proc_b.pid):
            _force_kill(pid)
        for p in (proc_a, proc_b):
            try:
                p.wait(timeout=3)
            except Exception:
                pass


def test_kill9_midwrite_restore_recovers_inflight(tmp_path):
    db = tmp_path / "downloads.db"
    code = (
        "import sys\n"
        f"sys.path.insert(0, {repr(str(REPO_ROOT))})\n"
        "from engine.download.store import DownloadStore\n"
        f"s = DownloadStore({repr(str(db))})\n"
        "s.save_current_sync({'nom': 'CRASHED', 'ep': 7})\n"
        "print('READY', flush=True)\n"
        "import time; time.sleep(60)\n"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        line = child.stdout.readline().strip()
        assert line == "READY", f"child never committed (got {line!r})"

        child.kill()
        try:
            child.wait(timeout=5)
        except Exception:
            pass
        assert _wait_gone(child.pid), "child process did not die"

        store = DownloadStore(db)
        try:
            q = DownloadQueue()
            q._store = store
            q.restore()
            assert list(q._queue) == [{"nom": "CRASHED", "ep": 7}]
        finally:
            store.close()
    finally:
        _force_kill(child.pid)
