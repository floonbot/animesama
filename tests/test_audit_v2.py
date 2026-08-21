
import time

import engine.download._engine_utils as eu
from engine.download.queue import DownloadQueue
from engine.scraping._cache import EP_LOCKS_MAX, ScraperCache


class _FakeProc:
    def __init__(self):
        self.pid = -1

    def poll(self):
        return None

def test_terminate_tree_none_is_noop():
    eu.terminate_tree(None)

def test_watchdog_kills_on_cancel(monkeypatch):
    killed = []
    monkeypatch.setattr(eu, "terminate_tree", lambda p: killed.append(p))
    proc = _FakeProc()
    cancelled = [True]
    stop = eu.spawn_proc_watchdog(proc, cancelled, timeout_s=60)
    deadline = time.time() + 3
    while proc not in killed and time.time() < deadline:
        time.sleep(0.1)
    stop.set()
    assert proc in killed

def test_watchdog_stops_cleanly_when_process_finishes(monkeypatch):
    killed = []
    monkeypatch.setattr(eu, "terminate_tree", lambda p: killed.append(p))
    proc = _FakeProc()
    cancelled = [False]
    stop = eu.spawn_proc_watchdog(proc, cancelled, timeout_s=60)
    stop.set()
    time.sleep(0.7)
    assert proc not in killed

def test_ep_locks_are_per_key():
    c = ScraperCache()
    c.ep_lock("anime-a")
    c.ep_lock("anime-b")
    c.ep_lock("anime-a")
    assert "anime-a" in c._ep_locks
    assert "anime-b" in c._ep_locks
    assert len(c._ep_locks) == 2

def test_ep_locks_are_bounded():
    c = ScraperCache()
    for i in range(EP_LOCKS_MAX + 100):
        c.ep_lock(f"k{i}")
    assert len(c._ep_locks) <= EP_LOCKS_MAX

def test_queue_actions_return_false_without_current():
    q = DownloadQueue()
    assert q.annuler() is False
    assert q.pause() is False

class _FakeResp:
    def __init__(self, chunks):
        self._chunks = chunks

    def iter_content(self, _size):
        yield from self._chunks

def test_http_body_within_cap_returns_bytes():
    from engine.scraping import http_client as hc

    body = hc._lire_corps_borne(_FakeResp([b"abc", b"def"]), "http://x")
    assert body == b"abcdef"

def test_http_body_over_cap_returns_none(monkeypatch):
    from engine.scraping import http_client as hc

    monkeypatch.setattr(hc, "HTTP_MAX_RESPONSE_SIZE", 4)
    body = hc._lire_corps_borne(_FakeResp([b"aa", b"bb", b"cc"]), "http://x")
    assert body is None
